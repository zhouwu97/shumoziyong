"""封存已完成运行的证据清单，避免初始化脚手架中的哈希被误作最终证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from atomic_io import atomic_write_bytes
from run_workflow import (
    OPTIONAL_GATE_EVIDENCE_SPECS,
    ROOT,
    build_run_evidence_manifest,
    evidence_artifact_specs_for_workflow,
    evidence_required_artifacts_for_workflow,
    replay_transition_log,
    validate_workflow_evidence_purpose,
    write_json,
)


OPTIONAL_EVIDENCE_ARTIFACTS = {
    role: filename for filename, role in OPTIONAL_GATE_EVIDENCE_SPECS
}
OPTIONAL_EVIDENCE_ARTIFACTS.update(
    {f"gate_{gate}_artifact_manifest": f"gate_artifacts/gate_{gate}.manifest.json" for gate in range(6)}
)

KNOWN_EVIDENCE_ARTIFACTS = dict(OPTIONAL_EVIDENCE_ARTIFACTS)
for _workflow in ("full_replay", "new_problem"):
    KNOWN_EVIDENCE_ARTIFACTS.update(
        {
            role: filename
            for filename, role, _media_type in evidence_artifact_specs_for_workflow(_workflow)
        }
    )


def load_policy() -> dict[str, Any]:
    """读取晋级策略中的固定证据角色契约。"""
    path = ROOT / "policies" / "promotion_policy.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_evidence_manifest(
    run_dir: Path,
    evidence_manifest: Mapping[str, Any],
    required_artifacts: Mapping[str, str],
    content_overrides: Mapping[str, bytes] | None = None,
) -> list[str]:
    """校验角色绑定、路径安全、文件大小及内容哈希，返回全部错误。"""
    errors: list[str] = []
    artifacts = evidence_manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return ["run_evidence_manifest.artifacts 必须是数组"]

    run_root = run_dir.resolve()
    seen_roles: set[str] = set()
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("run_evidence_manifest.artifacts 包含非对象项")
            continue
        role = artifact.get("role")
        path_text = artifact.get("path")
        if not isinstance(role, str) or not isinstance(path_text, str):
            errors.append("run_evidence_manifest 证据项缺少 role 或 path")
            continue
        if role in seen_roles:
            errors.append(f"run_evidence_manifest.role 重复：{role}")
        seen_roles.add(role)
        if path_text in seen_paths:
            errors.append(f"run_evidence_manifest.path 重复：{path_text}")
        seen_paths.add(path_text)
        expected_path = required_artifacts.get(role, KNOWN_EVIDENCE_ARTIFACTS.get(role))
        if expected_path is None:
            errors.append(f"run_evidence_manifest 包含未知证据角色：{role}")
        elif path_text != expected_path:
            errors.append(f"run_evidence_manifest 角色 {role} 必须对应固定文件：{expected_path}")

        artifact_path = (run_dir / path_text).resolve()
        if not artifact_path.is_relative_to(run_root):
            errors.append(f"run_evidence_manifest 路径位于运行目录外：{path_text}")
            continue
        content = content_overrides.get(path_text) if content_overrides else None
        if content is None:
            if not artifact_path.is_file():
                errors.append(f"run_evidence_manifest 引用文件不存在：{path_text}")
                continue
            content = artifact_path.read_bytes()
        if artifact.get("size_bytes") != len(content):
            errors.append(f"run_evidence_manifest.size_bytes 不匹配：{path_text}")
        if artifact.get("sha256") != hashlib.sha256(content).hexdigest():
            errors.append(f"run_evidence_manifest.sha256 不匹配：{path_text}")

    missing_roles = set(required_artifacts) - seen_roles
    if missing_roles:
        errors.append(f"run_evidence_manifest 缺少证据角色：{', '.join(sorted(missing_roles))}")
    missing_paths = set(required_artifacts.values()) - seen_paths
    if missing_paths:
        errors.append(f"run_evidence_manifest 缺少固定证据文件：{', '.join(sorted(missing_paths))}")
    return errors


def finalize_run_evidence(run_dir: Path) -> dict[str, Any]:
    """预校验后封存证据；任何预校验失败都不会覆盖原有清单。"""
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise ValueError(f"运行目录不存在：{run_dir}")

    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    run_id = run_manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_manifest.run_id 不能为空")
    runtime_manifest = json.loads(
        (run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8")
    )
    purpose_error = validate_workflow_evidence_purpose(run_manifest, runtime_manifest)
    if purpose_error:
        raise ValueError(purpose_error)
    workflow = run_manifest.get("workflow")
    assert isinstance(workflow, str)
    required_artifacts = evidence_required_artifacts_for_workflow(
        workflow,
        completed=True,
        runtime_manifest_version=str(runtime_manifest.get("manifest_version")),
    )
    immutable_manifest = run_manifest.get("manifest_version") == "2.0.0"
    if immutable_manifest:
        if run_manifest.get("initial_state") != "initialized":
            raise ValueError("run_manifest.initial_state 必须为 initialized 才能封存证据")
        if (run_dir / "seal_record.json").exists():
            raise ValueError("运行已经封存，不能重复生成 seal_record.json")
    else:
        if run_manifest.get("run_status") != "completed":
            raise ValueError("run_manifest.run_status 必须为 completed 才能封存证据")
        if run_manifest.get("integrity_status") != "unsealed":
            raise ValueError("run_manifest.integrity_status 必须为 unsealed 才能封存证据")
    try:
        state = replay_transition_log(run_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Gate 状态机记录无效，不能封存证据：{exc}") from exc
    if not state["completed"] or state["max_gate"] != 5:
        raise ValueError("仅允许封存已完成 Gate 0-5 全流程的运行")
    missing_files = [
        filename for filename in sorted(set(required_artifacts.values())) if not (run_dir / filename).is_file()
    ]
    if missing_files:
        raise ValueError(f"缺少 workflow 必需证据文件：{', '.join(missing_files)}")

    metadata = json.loads((run_dir / "ai_run_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("status") != "completed":
        raise ValueError("ai_run_metadata.status 必须为 completed 才能封存证据")

    if immutable_manifest:
        run_manifest_bytes = (run_dir / "run_manifest.json").read_bytes()
        overrides: dict[str, bytes] = {}
    else:
        run_manifest["integrity_status"] = "sealed"
        run_manifest_bytes = (
            json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        overrides = {"run_manifest.json": run_manifest_bytes}
    evidence_manifest = build_run_evidence_manifest(run_dir, run_id, overrides)
    errors = validate_evidence_manifest(run_dir, evidence_manifest, required_artifacts, overrides)
    if errors:
        raise ValueError("；".join(errors))

    # 仅在全部预校验通过后写入；失败时保留旧的 run_evidence_manifest.json。
    if not immutable_manifest:
        atomic_write_bytes(run_dir / "run_manifest.json", run_manifest_bytes)
    write_json(run_dir / "run_evidence_manifest.json", evidence_manifest)

    if immutable_manifest:
        evidence_bytes = (run_dir / "run_evidence_manifest.json").read_bytes()
        write_json(
            run_dir / "seal_record.json",
            {
                "seal_version": "1.0.0",
                "run_id": run_id,
                "sealed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "run_manifest_sha256": hashlib.sha256(run_manifest_bytes).hexdigest(),
                "transitions_sha256": hashlib.sha256(
                    (run_dir / "transitions.jsonl").read_bytes()
                ).hexdigest(),
                "evidence_manifest_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
            },
        )

    errors = validate_evidence_manifest(run_dir, evidence_manifest, required_artifacts)
    if errors:  # pragma: no cover - 防御性检查，避免 I/O 异常后错误报告成功
        raise RuntimeError("封存后的证据清单校验失败：" + "；".join(errors))
    return evidence_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="封存旧题运行目录的最终证据清单。")
    parser.add_argument("--run-dir", required=True, help="待封存的 runs/<run_id> 目录。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        evidence_manifest = finalize_run_evidence(Path(args.run_dir))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[BLOCKED] 证据封存失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(f"[SEALED] 已封存 {evidence_manifest['run_id']}，共 {len(evidence_manifest['artifacts'])} 项证据。")


if __name__ == "__main__":
    main()
