from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from atomic_io import atomic_write_bytes, atomic_write_text
from export_runtime_pack import build_manifest, build_pack
from model_validation import validate_model_and_execution
from verify_materials import MaterialVerificationResult, verify_materials

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover - 依赖缺失时由命令行明确报告
    raise SystemExit("缺少 jsonschema，请先执行：python -m pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parents[1]


def normalize_problem_dir(problem: str) -> str:
    """将题号规范为 official_materials 下使用的目录名。"""
    return re.sub(r"[^A-Za-z0-9]+", "_", problem).strip("_")


def write_json(path: Path, data: object) -> None:
    """以临时文件、fsync 和 os.replace 原子写入 JSON，并回读确认。"""
    content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, content)


def sha256_bytes(content: bytes) -> str:
    """计算内容哈希。"""
    return hashlib.sha256(content).hexdigest()


def chain_transition_event(
    event: Mapping[str, Any], previous_event_sha256: str | None
) -> dict[str, Any]:
    """为转换事件绑定前序哈希并计算自身哈希。"""
    chained = dict(event)
    chained["previous_event_sha256"] = previous_event_sha256
    chained.pop("event_sha256", None)
    canonical = json.dumps(
        chained, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    chained["event_sha256"] = sha256_bytes(canonical)
    return chained


def _validate_transition_hash_chain(entries: list[dict[str, Any]]) -> None:
    previous: str | None = None
    for index, entry in enumerate(entries, start=1):
        expected = chain_transition_event(entry, previous)
        if entry.get("previous_event_sha256") != previous:
            raise ValueError(f"第 {index} 条转换记录 previous_event_sha256 不匹配")
        if entry.get("event_sha256") != expected["event_sha256"]:
            raise ValueError(f"第 {index} 条转换记录 event_sha256 不匹配")
        previous = str(entry["event_sha256"])


def _append_transition_event(path: Path, event: Mapping[str, Any]) -> None:
    entries = _read_transition_entries(path) if path.is_file() else []
    previous = entries[-1].get("event_sha256") if entries else None
    if previous is not None and not isinstance(previous, str):
        raise ValueError("上一条转换记录缺少合法 event_sha256")
    chained = chain_transition_event(event, previous)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    atomic_write_text(
        path,
        existing + json.dumps(chained, ensure_ascii=False) + "\n",
    )


COMMON_EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("run_manifest.json", "run_manifest", "application/json"),
    ("request.json", "request", "application/json"),
    ("response.json", "model_response", "application/json"),
    ("runtime_pack.md", "runtime_pack", "text/markdown"),
    ("runtime_pack.manifest.json", "runtime_pack_manifest", "application/json"),
    ("problem_manifest.json", "problem_manifest", "application/json"),
    ("automatic_evaluation.json", "automatic_evaluation", "application/json"),
    ("ai_run_metadata.json", "ai_run_metadata", "application/json"),
    ("human_review.md", "human_review", "text/markdown"),
    ("transitions.jsonl", "transitions", "application/jsonlines"),
    ("gate_5_review.json", "gate_5_review", "application/json"),
)

FULL_REPLAY_EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("score.json", "score", "application/json"),
    ("failure_labels.json", "failure_labels", "application/json"),
)

NEW_PROBLEM_EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("competition_process_review.md", "competition_process_review", "text/markdown"),
)

OPTIONAL_GATE_EVIDENCE_SPECS: tuple[tuple[str, str], ...] = (
    ("runtime_profile.snapshot.json", "runtime_profile_snapshot"),
    ("patch_selection.snapshot.json", "patch_selection_snapshot"),
    ("diagnosis.json", "gate_0_diagnosis"),
    ("model_route.json", "gate_1_model_route"),
    ("code_plan.json", "gate_2_code_plan"),
    ("result_report.json", "gate_3_result_report"),
    ("result_manifest.json", "gate_3_result_manifest"),
    ("paper_claim_map.json", "gate_4_paper_claim_map"),
)


def build_run_evidence_manifest(
    run_dir: Path,
    run_id: str,
    content_overrides: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """为运行目录中的晋级证据生成可验证的路径、大小和内容哈希清单。"""
    run_manifest_path = run_dir / "run_manifest.json"
    try:
        workflow = json.loads(run_manifest_path.read_text(encoding="utf-8")).get("workflow")
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法确定运行工作流：{run_manifest_path}（{exc}）") from exc
    artifact_specs = list(COMMON_EVIDENCE_ARTIFACT_SPECS)
    if workflow == "full_replay":
        artifact_specs.extend(FULL_REPLAY_EVIDENCE_ARTIFACT_SPECS)
    elif workflow == "new_problem":
        artifact_specs.extend(NEW_PROBLEM_EVIDENCE_ARTIFACT_SPECS)
    else:
        raise ValueError(f"Gate 运行不支持的 workflow：{workflow!r}")

    artifacts: list[dict[str, Any]] = []
    for filename, role, media_type in artifact_specs:
        path = run_dir / filename
        if content_overrides and filename in content_overrides:
            content = content_overrides[filename]
        else:
            content = path.read_bytes()
        artifacts.append(
            {
                "path": filename,
                "sha256": sha256_bytes(content),
                "media_type": media_type,
                "size_bytes": len(content),
                "role": role,
            }
        )
    gate_artifacts_dir = run_dir / "gate_artifacts"
    for filename, role in OPTIONAL_GATE_EVIDENCE_SPECS:
        path = run_dir / filename
        if not path.is_file():
            continue
        content = path.read_bytes()
        artifacts.append(
            {
                "path": filename,
                "sha256": sha256_bytes(content),
                "media_type": "application/json",
                "size_bytes": len(content),
                "role": role,
            }
        )
    if gate_artifacts_dir.is_dir():
        for path in sorted(gate_artifacts_dir.glob("gate_*.manifest.json")):
            content = path.read_bytes()
            gate_name = path.name.removeprefix("gate_").removesuffix(".manifest.json")
            artifacts.append(
                {
                    "path": path.relative_to(run_dir).as_posix(),
                    "sha256": sha256_bytes(content),
                    "media_type": "application/json",
                    "size_bytes": len(content),
                    "role": f"gate_{gate_name}_artifact_manifest",
                }
            )
    return {
        "evidence_manifest_version": "2.0.0",
        "run_id": run_id,
        "artifacts": artifacts,
    }


def repo_relative(path: Path) -> str:
    """优先记录仓库相对路径；外部材料目录保留绝对路径以确保可追溯。"""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_problem_manifest(
    problem_id: str,
    material_path: Path,
    verification: MaterialVerificationResult,
) -> dict[str, Any]:
    """从材料校验结果生成运行固定的题目快照。

    只记录机器清单中明确声明且哈希校验通过的文件；不再递归扫描目录并把“目录存在”误判为材料就绪。
    """
    files: list[dict[str, Any]] = []
    for item in verification.files:
        relative_file = item["path"]
        resolved = material_path / relative_file
        files.append(
            {
                "category": item["category"],
                "path": repo_relative(resolved),
                "size": item["size"],
                "sha256": item["sha256"],
            }
        )
    files.sort(key=lambda item: (item["category"], item["path"]))

    digest_input = "".join(
        f"{item['category']}:{item['path']}:{item['size']}:{item['sha256']}" for item in files
    )
    content_digest = sha256_bytes(digest_input.encode("utf-8")) if files else None
    return {
        "problem_id": problem_id,
        "material_root": repo_relative(material_path),
        "material_manifest": repo_relative(verification.manifest_path),
        "material_manifest_sha256": verification.manifest_sha256,
        "material_exists": material_path.is_dir(),
        "material_status": verification.status,
        "categories": {
            name: category.to_dict() for name, category in verification.categories.items()
        },
        "files": files,
        "content_digest": content_digest,
        "errors": verification.errors,
    }


def _experiment_kind(candidate_patches: list[str], excluded_patches: list[str]) -> str:
    if excluded_patches and not candidate_patches:
        return "isolation"
    if candidate_patches:
        return "candidate_experiment"
    return "standard"


def _resolve_run_directory(args: argparse.Namespace) -> tuple[str, Path]:
    """解析当前阶段的运行目录；显式重复 ID 必须立即阻断。"""
    run_id = args.run_id or f"{date.today().isoformat()}_{normalize_problem_dir(args.problem)}_gate{args.gates}"
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"运行目录已存在：{run_dir}")
    return run_id, run_dir


def _resolve_material_path(args: argparse.Namespace) -> Path:
    """解析材料根目录，保持旧题默认材料目录与新题显式材料目录兼容。"""
    material_path = (
        Path(args.materials)
        if args.materials
        else ROOT / "official_materials" / normalize_problem_dir(args.problem)
    )
    if not material_path.is_absolute():
        material_path = ROOT / material_path
    return material_path.resolve()


def _load_profile_state(profile: str) -> dict[str, Any]:
    """读取已注册 Runtime Profile，避免目录初始化后才发现 Profile 不存在。"""
    profile_state_path = ROOT / "runtime_profiles" / f"{profile}.json"
    if not profile_state_path.is_file():
        raise FileNotFoundError(f"runtime profile 状态不存在：{profile_state_path}")
    profile_state = json.loads(profile_state_path.read_text(encoding="utf-8"))
    if not isinstance(profile_state, dict):
        raise ValueError(f"runtime profile 必须是 JSON 对象：{profile_state_path}")
    return profile_state


def _initialize_common_gate_artifacts(run_dir: Path, profile_state: Mapping[str, Any]) -> None:
    """创建两个 Gate 工作流共享的业务产物和 AI 运行证据脚手架。"""
    atomic_write_text(run_dir / "diagnosis.md", "# Gate 0：题目与材料诊断\n\n待执行。\n")
    write_json(
        run_dir / "diagnosis.json",
        {"stage": "diagnosis", "_note": "待执行；完成后须符合 schemas/diagnosis.schema.json"},
    )
    for filename, artifact_type in (
        ("model_route.json", "model_route"),
        ("code_plan.json", "code_plan"),
        ("result_report.json", "result_report"),
        ("result_manifest.json", "result_manifest"),
        ("paper_claim_map.json", "paper_claim_map"),
    ):
        write_json(
            run_dir / filename,
            {
                "artifact_type": artifact_type,
                "_note": "待执行；离开对应 Gate 前必须替换为符合业务 Schema 的真实产物。",
            },
        )
    (run_dir / "gate_artifacts").mkdir()
    write_json(
        run_dir / "gate_5_review.json",
        {"_note": "待 Gate 5 通过后填写；完成记录必须符合 schemas/gate_5_review.schema.json。"},
    )
    write_json(
        run_dir / "request.json",
        {
            "_note": "待填写：发送给 AI 的提示词",
            "prompt": "",
            "model": "",
            "runtime_version": profile_state["version"],
            "source": "pending",
            "response_reference": None,
        },
    )
    atomic_write_text(run_dir / "response.md", "# AI 输出（Markdown）\n\n待填写。\n")
    write_json(
        run_dir / "response.json",
        {"_note": "待填写：AI 结构化 JSON 输出，须符合 diagnosis.schema.json"},
    )
    write_json(
        run_dir / "automatic_evaluation.json",
        {"_note": "待生成：由 evaluate_prompt_response.py 产出", "case_id": "", "errors": []},
    )
    atomic_write_text(
        run_dir / "human_review.md",
        "# 人工审核\n\n待填写。至少写明：\n"
        "- 是否出现 patch 特有机制\n"
        "- 是否改变正确题型\n"
        "- 是否相比 baseline 发生跑偏\n"
        "- 最终判定 pass/fail\n"
        "- 判断理由\n",
    )
    write_json(
        run_dir / "ai_run_metadata.json",
        {
            "metadata_version": "1.0.0",
            "status": "pending",
            "note": "待填写真实运行数据；pending 元数据不能作为晋级证据。",
            "provider": None,
            "model": None,
            "model_snapshot": None,
            "client": None,
            "client_version": None,
            "reasoning_effort": None,
            "temperature": None,
            "seed": None,
            "started_at": None,
            "completed_at": None,
            "prompt_sha256": None,
            "runtime_pack_sha256": None,
            "problem_material_digest": None,
            "tool_permissions": None,
            "working_directory_mode": None,
        },
    )


def create_gate_run_core(
    args: argparse.Namespace,
    *,
    workflow: str,
    evidence_purpose: str,
) -> tuple[Path, MaterialVerificationResult, dict[str, Any], dict[str, Any], Path]:
    """初始化 full_replay 与 new_problem 共用的材料、运行包和 Gate 基础现场。"""
    if getattr(args, "material_file", []):
        raise ValueError("不再支持 --material-file：旧题运行必须校验完整材料清单，不能用子集绕过附件或模板检查")
    if workflow not in {"full_replay", "new_problem"}:
        raise ValueError(f"不支持的 Gate workflow：{workflow!r}")
    run_id, run_dir = _resolve_run_directory(args)
    material_path = _resolve_material_path(args)
    material_verification = verify_materials(
        material_path,
        expected_problem_id=args.problem,
    )
    profile_state = _load_profile_state(args.profile)
    candidate_patches = list(getattr(args, "candidate_patch", []))
    excluded_patches = list(getattr(args, "exclude_patch", []))
    pack_content = build_pack(args.profile, candidate_patches, excluded_patches)
    pack_manifest = build_manifest(args.profile, pack_content, candidate_patches, excluded_patches)

    run_dir.mkdir(parents=True)
    atomic_write_text(run_dir / "runtime_pack.md", pack_content)
    write_json(run_dir / "runtime_pack.manifest.json", pack_manifest)
    write_json(run_dir / "runtime_profile.snapshot.json", profile_state)
    patch_selection_snapshot = {
        "selected_patches": [item["patch_id"] for item in pack_manifest.get("patches", [])],
        "candidate_patches": candidate_patches,
        "excluded_patches": excluded_patches,
    }
    write_json(run_dir / "patch_selection.snapshot.json", patch_selection_snapshot)

    problem_manifest = build_problem_manifest(args.problem, material_path, material_verification)
    write_json(run_dir / "problem_manifest.json", problem_manifest)

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    initial_state = "initialized" if material_verification.ready else "blocked"
    mode = getattr(args, "mode", "standard")
    confirmation_gates = {
        "strict": [0, 1, 2, 3, 4, 5],
        "standard": [0, 2, 5],
        "emergency": [0, 5],
    }[mode]
    manifest_data: dict[str, Any] = {
        "manifest_version": "2.0.0",
        "run_id": run_id,
        "workflow": workflow,
        "mode": mode,
        "human_confirmation_gates": confirmation_gates,
        "created_at": created_at,
        "problem_id": args.problem,
        "profile": args.profile,
        "runtime_version": profile_state["version"],
        "runtime_pack_sha256": pack_manifest["runtime_pack_sha256"],
        "gates": args.gates,
        "materials": repo_relative(material_path),
        "material_manifest": repo_relative(material_verification.manifest_path),
        "material_manifest_sha256": material_verification.manifest_sha256,
        "material_status": material_verification.status,
        "material_error_count": len(material_verification.errors)
        + sum(len(category.errors) for category in material_verification.categories.values()),
        "candidate_patches": candidate_patches,
        "excluded_patches": excluded_patches,
        "evidence_purpose": evidence_purpose,
        "initial_state": initial_state,
        "runtime_profile_snapshot_sha256": sha256_bytes(
            (run_dir / "runtime_profile.snapshot.json").read_bytes()
        ),
        "patch_selection_snapshot_sha256": sha256_bytes(
            (run_dir / "patch_selection.snapshot.json").read_bytes()
        ),
    }

    write_json(run_dir / "run_manifest.json", manifest_data)
    material_report = material_verification.to_dict()
    material_report["material_path"] = repo_relative(material_path)
    material_report["manual_review_required"] = True
    write_json(run_dir / "material_review.json", material_report)

    _initialize_common_gate_artifacts(run_dir, profile_state)
    _init_transitions(run_dir, args.gates, material_verification.ready)
    return run_dir, material_verification, profile_state, pack_manifest, material_path


def create_full_replay_run(args: argparse.Namespace) -> tuple[Path, bool]:
    """初始化旧题训练运行，并写入训练与 Patch 晋级专属产物。"""
    run_dir, material_verification, profile_state, _pack_manifest, material_path = create_gate_run_core(
        args,
        workflow="full_replay",
        evidence_purpose="training_validation",
    )
    manifest_path = run_dir / "run_manifest.json"
    manifest_data = _load_json_object(manifest_path, "run_manifest.json")
    candidate_patches = list(getattr(args, "candidate_patch", []))
    excluded_patches = list(getattr(args, "exclude_patch", []))
    manifest_data.update(
        {
            "experiment_kind": _experiment_kind(candidate_patches, excluded_patches),
            "promotion_evidence": bool(getattr(args, "promotion_evidence", False)),
        }
    )
    if getattr(args, "promotion_evidence", False):
        if not getattr(args, "experiment_group_id", None):
            raise ValueError("--promotion-evidence 必须提供 --experiment-group-id")
        if not getattr(args, "experiment_role", None):
            raise ValueError("--promotion-evidence 必须提供 --experiment-role")
        if not getattr(args, "target_patch", None):
            raise ValueError("--promotion-evidence 必须提供 --target-patch")
        manifest_data.update(
            {
                "experiment_kind": "negative_control",
                "experiment_group_id": args.experiment_group_id,
                "experiment_role": args.experiment_role,
                "target_patch": args.target_patch,
            }
        )
        if args.experiment_role == "baseline" and args.target_patch not in excluded_patches:
            raise ValueError("baseline 必须在 excluded_patches 中排除 target_patch")
        if args.experiment_role == "patch_only" and args.target_patch in excluded_patches:
            raise ValueError("patch_only 不能排除 target_patch")
    write_json(manifest_path, manifest_data)

    material_review = _load_json_object(run_dir / "material_review.json", "material_review.json")
    material_review["material_level"] = None
    material_review["risk_labels"] = []
    write_json(run_dir / "material_review.json", material_review)
    material_status_text = "材料校验通过" if material_verification.ready else "材料校验失败，已阻塞"
    atomic_write_text(
        run_dir / "execution_plan.md",
        f"# 旧题闭环执行计划\n\n"
        f"- 题目：`{args.problem}`\n"
        f"- profile：`{args.profile}`（{profile_state['version']} / {profile_state['maturity']}）\n"
        f"- 闸门范围：Gate {args.gates}\n"
        f"- 材料：`{repo_relative(material_path)}`\n"
        f"- 材料清单：`{repo_relative(material_verification.manifest_path)}`\n"
        f"- review_ready 实验 patch：{candidate_patches or '无'}\n"
        f"- 排除 patch：{excluded_patches or '无'}\n"
        f"- 实验类型：{_experiment_kind(candidate_patches, excluded_patches)}\n"
        f"- 状态：{material_status_text}\n\n"
        "## Gate 0-5 定义\n\n"
        "- Gate 0：题目与材料诊断\n"
        "- Gate 1：模型路线\n"
        "- Gate 2：代码计划\n"
        "- Gate 3：结果确认\n"
        "- Gate 4：论文确认\n"
        "- Gate 5：最终验收\n\n"
        "## 执行顺序\n\n"
        "1. 先检查 `material_review.json`：只有 `status=ready` 才能进入 Gate 0。\n"
        "2. 人工确认材料等级 T0-T4 与风险 M1-M5。\n"
        "3. 读取 `runtime_pack.md`，只执行指定 Gate。\n"
        "4. 把发送给 AI 的提示词存入 `request.json`。\n"
        "5. 将诊断写入 `diagnosis.md`（人看）与 `diagnosis.json`（机器检查，符合 `schemas/diagnosis.schema.json`）。\n"
        "6. 把 AI 原始输出存入 `response.md` 和 `response.json`。\n"
        "7. 运行 `evaluate_prompt_response.py` 生成 `automatic_evaluation.json`。\n"
        "8. 人工填写 `human_review.md`、`score.json` 与 `failure_labels.json`。\n"
        "9. 只把升级建议写入 `patch_suggestions.md`，不得自动修改 patch 状态。\n",
    )
    write_json(run_dir / "score.json", {"total": None, "items": {}, "passed": None})
    write_json(run_dir / "failure_labels.json", {"labels": [], "evidence": {}, "reviewed": False})
    atomic_write_text(
        run_dir / "patch_suggestions.md",
        "# Patch 建议\n\n待复盘后填写；不得自动升级状态。\n",
    )
    write_json(
        run_dir / "run_evidence_manifest.json",
        build_run_evidence_manifest(run_dir, str(manifest_data["run_id"])),
    )
    return run_dir, material_verification.ready


def create_new_problem_run(args: argparse.Namespace) -> tuple[Path, bool]:
    """初始化比赛运行；不得携带旧题训练或 Patch 晋级语义。"""
    if getattr(args, "candidate_patch", []) or getattr(args, "exclude_patch", []):
        raise ValueError("new_problem 不支持 candidate/exclude Patch；正式比赛包只能使用已验证 Patch")
    if getattr(args, "promotion_evidence", False):
        raise ValueError("new_problem 不能声明为 Patch 晋级证据")
    run_dir, material_verification, profile_state, _pack_manifest, material_path = create_gate_run_core(
        args,
        workflow="new_problem",
        evidence_purpose="competition_execution",
    )
    material_status_text = "材料校验通过" if material_verification.ready else "材料校验失败，已阻塞"
    atomic_write_text(
        run_dir / "execution_plan.md",
        f"# 比赛执行计划\n\n"
        f"- 题目：`{args.problem}`\n"
        f"- profile：`{args.profile}`（{profile_state['version']}）\n"
        f"- 闸门范围：Gate {args.gates}\n"
        f"- 材料：`{repo_relative(material_path)}`\n"
        f"- 材料清单：`{repo_relative(material_verification.manifest_path)}`\n"
        f"- 状态：{material_status_text}\n\n"
        "## 比赛 Gate 0-5\n\n"
        "- Gate 0：题目与材料诊断；本轮只完成读题、题型判断、风险和人工确认项。\n"
        "- Gate 1：模型路线；经人工确认后明确变量、约束、基线和验证方式。\n"
        "- Gate 2：实现计划；确认模块、输入输出、验证和降级策略。\n"
        "- Gate 3：结果确认；验证结果、约束、基线比较和稳健性。\n"
        "- Gate 4：论文确认；仅映射已有证据，不把候选内容写成结论。\n"
        "- Gate 5：最终验收；复核可复现性、风险闭环和交付完整性。\n\n"
        "## 执行约束\n\n"
        "1. 仅在材料状态为 ready 时进入 Gate 0。\n"
        "2. 第一轮只执行 Gate 0；未经人工确认不得进入下一阶段。\n"
        "3. 每个 Gate 的 JSON 业务产物和 Gate Manifest 必须绑定当前 Run 身份。\n"
        "4. 记录真实 AI 运行元数据、请求、响应和人工审核。\n"
        "5. 本比赛 Run 的 evidence_purpose 为 competition_execution，不具备 Patch 首级晋级资格。\n",
    )
    atomic_write_text(
        run_dir / "competition_process_review.md",
        "# 比赛过程审核\n\n待填写每次人工确认、风险决策和阶段推进理由。\n",
    )
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    write_json(
        run_dir / "run_evidence_manifest.json",
        build_run_evidence_manifest(run_dir, str(manifest["run_id"])),
    )
    return run_dir, material_verification.ready


def create_old_problem_run(args: argparse.Namespace) -> tuple[Path, bool]:
    """兼容旧调用名称，并按调用方声明的 workflow 分派初始化语义。"""
    if getattr(args, "workflow", "full_replay") == "new_problem":
        return create_new_problem_run(args)
    return create_full_replay_run(args)


GATE_NAMES: dict[int, str] = {
    0: "题目与材料诊断",
    1: "模型路线",
    2: "代码计划",
    3: "结果确认",
    4: "论文确认",
    5: "最终验收",
}

GATE_5_CHECKLIST_KEYS: tuple[str, ...] = (
    "materials",
    "diagnosis",
    "model_route",
    "code_reproduction",
    "results",
    "claim_evidence",
    "risk_closure",
    "final_acceptance",
)

GATE_ARTIFACT_SPECS: dict[int, tuple[tuple[str, str, str, str], ...]] = {
    0: (("diagnosis.json", "diagnosis", "schemas/gate_business_artifact.schema.json", "1.0.0"),),
    1: (("model_route.json", "model_route", "schemas/gate_business_artifact.schema.json", "1.0.0"),),
    2: (("code_plan.json", "code_plan", "schemas/gate_business_artifact.schema.json", "1.0.0"),),
    3: (
        ("result_report.json", "result_report", "schemas/gate_business_artifact.schema.json", "1.0.0"),
        ("result_manifest.json", "result_manifest", "schemas/gate_business_artifact.schema.json", "1.0.0"),
    ),
    4: (("paper_claim_map.json", "paper_claim_map", "schemas/gate_business_artifact.schema.json", "1.0.0"),),
    5: (("gate_5_review.json", "gate_5_review", "schemas/gate_5_review.schema.json", "1.0.0"),),
}

TRANSITION_VERSION = "2.0.0"

VALID_TRANSITIONS: dict[int | None, set[int]] = {
    # from_gate -> {valid to_gate}；None 表示只允许从初始状态进入
    None: {0},       # 只能从 initialized 进入 Gate 0
    0: {1},          # Gate 0 → Gate 1
    1: {2},          # Gate 1 → Gate 2
    2: {3},          # Gate 2 → Gate 3
    3: {4},          # Gate 3 → Gate 4
    4: {5},          # Gate 4 → Gate 5
    5: set(),        # Gate 5 是终点
}


def _init_transitions(run_dir: Path, gate_range: str, material_ready: bool) -> None:
    """初始化 transitions.jsonl 并记录 initialized 状态。"""
    max_gate = int(gate_range.split("-")[1])
    initialized = chain_transition_event(
        {
            "transition_version": TRANSITION_VERSION,
            "from": None,
            "to": None,
            "completed_gate": None,
            "next_gate": 0,
            "state": "initialized",
            "material_ready": material_ready,
            "max_gate": max_gate,
            "note": "运行目录已创建；材料校验通过后才允许进入 Gate 0",
        },
        None,
    )
    atomic_write_text(
        run_dir / "transitions.jsonl",
        json.dumps(initialized, ensure_ascii=False) + "\n",
    )


def _read_transition_entries(transitions_path: Path) -> list[dict[str, Any]]:
    """读取转换日志，逐行要求为 JSON 对象，避免半截或伪造记录被忽略。"""
    entries: list[dict[str, Any]] = []
    for line_no, line in enumerate(transitions_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"transitions.jsonl 第 {line_no} 行不是合法 JSON：{exc}") from exc
        if not isinstance(entry, dict):
            raise ValueError(f"transitions.jsonl 第 {line_no} 行必须是 JSON 对象")
        entries.append(entry)
    return entries


def _replay_v2_transition_log(
    run_dir: Path,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """回放 v2 Gate 日志：事件表达已完成 Gate 和下一 Gate。"""
    _validate_transition_hash_chain(entries)
    init_data = entries[0]
    if init_data.get("completed_gate") is not None or init_data.get("next_gate") != 0:
        raise ValueError("v2 initialized 记录必须声明 completed_gate=null、next_gate=0")

    current: int | None = None
    completed_gates: list[int] = []
    completed = False
    completed_entry: dict[str, Any] | None = None
    for idx, entry in enumerate(entries[1:], start=2):
        if entry.get("transition_version") != TRANSITION_VERSION:
            raise ValueError(f"第 {idx} 条 Gate 记录 transition_version 不一致")
        if completed:
            raise ValueError("completed 终态之后不得再追加转换记录")
        decision = entry.get("decision")
        if decision not in ("approved", "rejected"):
            raise ValueError(f"第 {idx} 条 Gate 记录 decision 非法：{decision!r}")
        if not str(entry.get("reviewer", "")).strip():
            raise ValueError(f"第 {idx} 条 Gate 记录 reviewer 不能为空")

        state = entry.get("state")
        completed_gate = entry.get("completed_gate")
        next_gate = entry.get("next_gate")
        if state == "started_gate_0":
            if current is not None or completed_gate is not None or next_gate != 0:
                raise ValueError("started_gate_0 只能从初始化状态进入 Gate 0")
            if decision != "approved":
                raise ValueError("started_gate_0 必须为 approved")
            current = 0
            continue

        if state == "completed":
            if current != 5 or completed_gate != 5 or next_gate is not None:
                raise ValueError("completed 记录必须表达 completed_gate=5、next_gate=null")
            if decision != "approved":
                raise ValueError("completed 记录必须为 approved")
            review_record = entry.get("review_record")
            review_sha = entry.get("review_record_sha256")
            if review_record != "gate_5_review.json":
                raise ValueError("completed 记录必须绑定 gate_5_review.json")
            if not isinstance(review_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", review_sha):
                raise ValueError("completed 记录缺少合法 review_record_sha256")
            verify_gate_artifacts(run_dir, 5)
            _, actual_review_sha = _load_and_validate_gate_5_review(
                run_dir, str(entry["reviewer"])
            )
            if actual_review_sha != review_sha:
                raise ValueError("completed 记录绑定的 gate_5_review.json SHA-256 不匹配")
            completed_gates.append(5)
            completed = True
            completed_entry = entry
            current = None
            continue

        if current is None:
            raise ValueError(f"第 {idx} 条记录前尚未开始 Gate 0")
        expected_next = current + 1
        if completed_gate != current or next_gate != expected_next:
            raise ValueError(
                f"第 {idx} 条记录必须表达 completed_gate={current}、next_gate={expected_next}"
            )
        if next_gate > init_data["max_gate"]:
            raise ValueError(f"第 {idx} 条 Gate 记录超过 initialized.max_gate")
        if decision == "rejected":
            if state != f"rejected_gate_{current}":
                raise ValueError(f"第 {idx} 条拒绝记录 state 非法")
            continue
        if state != f"completed_gate_{current}":
            raise ValueError(f"第 {idx} 条完成记录 state 非法")
        verify_gate_artifacts(run_dir, current)
        completed_gates.append(current)
        current = next_gate

    return {
        "transition_version": TRANSITION_VERSION,
        "initialized": init_data,
        "current_gate": current,
        "completed_gates": completed_gates,
        "completed": completed,
        "completed_entry": completed_entry,
        "max_gate": init_data.get("max_gate"),
        "material_ready": init_data.get("material_ready"),
        "entries": entries,
    }


def replay_transition_log(run_dir: Path) -> dict[str, Any]:
    """严格回放 Gate 状态机，返回当前状态。

    该函数是 Gate 完成度和终态标记的唯一事实来源：必须恰好一次 initialized，
    初始化必须在首条有效记录，approved 只能按 VALID_TRANSITIONS 前进，completed
    只能从 Gate 5 产生且必须绑定 gate_5_review.json 的 SHA-256。
    """
    transitions_path = run_dir / "transitions.jsonl"
    if not transitions_path.is_file():
        raise FileNotFoundError(f"缺少 transitions.jsonl：{transitions_path}")

    entries = _read_transition_entries(transitions_path)
    if not entries:
        raise ValueError("transitions.jsonl 为空，缺少 initialized 记录")

    init_entries = [entry for entry in entries if entry.get("state") == "initialized"]
    if len(init_entries) != 1:
        raise ValueError(f"transitions.jsonl 必须且只能包含 1 条 initialized 记录，实际 {len(init_entries)} 条")
    if entries[0].get("state") != "initialized":
        raise ValueError("initialized 必须是 transitions.jsonl 的第一条有效记录")

    init_data = entries[0]
    if init_data.get("from") is not None or init_data.get("to") is not None:
        raise ValueError("initialized 记录的 from/to 必须为 null")
    max_gate = init_data.get("max_gate")
    if not isinstance(max_gate, int) or max_gate < 0 or max_gate > 5:
        raise ValueError("initialized.max_gate 必须是 0-5 的整数")
    if init_data.get("material_ready") is not True and len(entries) > 1:
        raise ValueError("initialized.material_ready 不为 true，日志中不得出现 Gate 转换")
    transition_version = init_data.get("transition_version")
    if transition_version is not None:
        if transition_version != TRANSITION_VERSION:
            raise ValueError(f"不支持的 transition_version：{transition_version!r}")
        return _replay_v2_transition_log(run_dir, entries)

    current: int | None = None
    completed = False
    completed_entry: dict[str, Any] | None = None
    for idx, entry in enumerate(entries[1:], start=2):
        state = entry.get("state")
        if state == "initialized":
            raise ValueError("initialized 记录不得重复出现")
        if completed:
            raise ValueError("completed 终态之后不得再追加转换记录")

        if state == "completed":
            if entry.get("from") != 5 or entry.get("to") is not None:
                raise ValueError("completed 记录必须从 Gate 5 转入终态，且 to 为 null")
            if current != 5:
                raise ValueError(f"completed 记录出现前当前 Gate 不是 5（当前：{current}）")
            if not str(entry.get("reviewer", "")).strip():
                raise ValueError("completed 记录 reviewer 不能为空")
            review_record = entry.get("review_record")
            review_sha = entry.get("review_record_sha256")
            if review_record != "gate_5_review.json":
                raise ValueError("completed 记录必须绑定 gate_5_review.json")
            if not isinstance(review_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", review_sha):
                raise ValueError("completed 记录缺少合法 review_record_sha256")
            try:
                _, actual_review_sha = _load_and_validate_gate_5_review(
                    run_dir,
                    str(entry["reviewer"]),
                )
            except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"completed 记录绑定的 gate_5_review.json 无效：{exc}") from exc
            if actual_review_sha != review_sha:
                raise ValueError("completed 记录绑定的 gate_5_review.json SHA-256 不匹配")
            completed = True
            completed_entry = entry
            continue

        decision = entry.get("decision")
        if decision not in ("approved", "rejected"):
            raise ValueError(f"第 {idx} 条 Gate 记录 decision 非法：{decision!r}")
        if not str(entry.get("reviewer", "")).strip():
            raise ValueError(f"第 {idx} 条 Gate 记录 reviewer 不能为空")
        from_gate = entry.get("from")
        to_gate = entry.get("to")
        if from_gate != current:
            raise ValueError(f"第 {idx} 条 Gate 记录 from={from_gate!r} 与当前 Gate {current!r} 不一致")
        if to_gate not in GATE_NAMES:
            raise ValueError(f"第 {idx} 条 Gate 记录 to 非法：{to_gate!r}")
        if not isinstance(to_gate, int) or to_gate > max_gate:
            raise ValueError(f"第 {idx} 条 Gate 记录超过 initialized.max_gate")
        valid_next = VALID_TRANSITIONS.get(current, set())
        if to_gate not in valid_next:
            expected = f"{{{', '.join(str(g) for g in sorted(valid_next))}}}" if valid_next else "（终点）"
            raise ValueError(f"Gate 转换非法：不能从 {current} 进入 Gate {to_gate}。允许的下一 Gate：{expected}。")
        expected_state = f"entering_gate_{to_gate}" if decision == "approved" else f"rejected_gate_{to_gate}"
        if state != expected_state:
            raise ValueError(f"第 {idx} 条 Gate 记录 state 应为 {expected_state!r}，实际 {state!r}")
        if decision == "approved":
            current = to_gate

    return {
        "transition_version": "1.0.0",
        "initialized": init_data,
        "current_gate": current,
        "completed": completed,
        "completed_entry": completed_entry,
        "max_gate": init_data.get("max_gate"),
        "material_ready": init_data.get("material_ready"),
        "completed_gates": list(range(6)) if completed else (
            list(range(current)) if current is not None else []
        ),
        "entries": entries,
    }


def record_transition(run_dir: Path, from_gate: int | None, to_gate: int, reviewer: str, decision: str) -> None:
    """记录一次闸门推进事件，所有前置状态均通过 replay_transition_log 严格回放。"""
    if to_gate not in GATE_NAMES:
        raise ValueError(f"未知 Gate：{to_gate}（允许 0-5）")
    if not str(reviewer).strip():
        raise ValueError("reviewer 不能为空")
    if decision not in ("approved", "rejected"):
        raise ValueError(f"decision 必须为 approved 或 rejected，实际为 {decision!r}")

    state = replay_transition_log(run_dir)
    if state["completed"]:
        raise ValueError("运行已 completed，不能再记录 Gate 转换。")
    if state["material_ready"] is not True:
        raise ValueError(
            f"材料校验未通过（material_ready={state['material_ready']}），"
            "禁止进入任何 Gate。请先修复材料问题。"
        )
    if to_gate > state["max_gate"]:
        raise ValueError(f"不能进入 Gate {to_gate}，初始化声明的最大 Gate 为 {state['max_gate']}。")

    real_current = state["current_gate"]
    if from_gate != real_current:
        raise ValueError(
            f"from_gate 不匹配：调用方声称当前为 {from_gate}，"
            f"但 transitions.jsonl 记录的实际当前 Gate 为 {real_current}。禁止伪造跳跃。"
        )

    valid_next = VALID_TRANSITIONS.get(real_current, set())
    if to_gate not in valid_next:
        expected = f"{{{', '.join(str(g) for g in sorted(valid_next))}}}" if valid_next else "（终点）"
        raise ValueError(f"Gate 转换非法：不能从 {real_current} 进入 Gate {to_gate}。允许的下一 Gate：{expected}。")

    if state.get("transition_version") == TRANSITION_VERSION:
        if real_current is None:
            if decision != "approved":
                raise ValueError("v2 工作流开始 Gate 0 时 decision 必须为 approved")
            entry = {
                "transition_version": TRANSITION_VERSION,
                "completed_gate": None,
                "next_gate": 0,
                "state": "started_gate_0",
                "gate_name": GATE_NAMES[0],
                "reviewer": str(reviewer).strip(),
                "decision": decision,
            }
        else:
            if decision == "approved":
                verify_gate_artifacts(run_dir, real_current)
            entry = {
                "transition_version": TRANSITION_VERSION,
                "completed_gate": real_current,
                "next_gate": to_gate,
                "state": (
                    f"completed_gate_{real_current}"
                    if decision == "approved"
                    else f"rejected_gate_{real_current}"
                ),
                "gate_name": GATE_NAMES[real_current],
                "reviewer": str(reviewer).strip(),
                "decision": decision,
            }
        _append_transition_event(run_dir / "transitions.jsonl", entry)
        return

    entry = {
        "from": real_current,
        "to": to_gate,
        "state": f"entering_gate_{to_gate}" if decision == "approved" else f"rejected_gate_{to_gate}",
        "gate_name": GATE_NAMES[to_gate],
        "reviewer": str(reviewer).strip(),
        "decision": decision,
    }
    with open(run_dir / "transitions.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def is_gate_complete(run_dir: Path, gate: int) -> bool:
    """检查指定 Gate 是否已完成并通过；伪造或损坏日志一律视为未完成。"""
    try:
        state = replay_transition_log(run_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return False
    if state["completed"]:
        return gate <= 5
    current = state["current_gate"]
    return current is not None and current > gate


def get_current_gate(run_dir: Path) -> int | None:
    """从 transitions.jsonl 严格回放当前所在 Gate；缺少日志时返回 None。"""
    try:
        state = replay_transition_log(run_dir)
    except FileNotFoundError:
        return None
    if state["completed"]:
        return None
    return state["current_gate"]


def _parse_datetime(value: Any, field: str) -> None:
    """校验 ISO 8601 时间字段；允许 Z 后缀。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"gate_5_review.{field} 不能为空")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"gate_5_review.{field} 不是合法 ISO 8601 时间") from exc


def _validate_gate_5_review_schema(review: dict[str, Any]) -> None:
    """以唯一 Schema 契约校验 Gate 5 审核记录，避免手工规则漂移。"""
    schema_path = ROOT / "schemas" / "gate_5_review.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(review),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError(f"gate_5_review.json 不符合 Schema：{details}")


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    """读取运行现场 JSON 对象；缺失、损坏或非对象均按闭锁失败处理。"""
    if not path.is_file():
        raise FileNotFoundError(f"缺少{label}：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是 JSON 对象")
    return value


def _load_current_run_binding(run_dir: Path) -> dict[str, str]:
    """从不可由审核文件替代的运行现场读取 Gate 5 身份绑定。"""
    run_manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    runtime_manifest = _load_json_object(
        run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json"
    )

    binding: dict[str, Any] = {
        "run_id": run_manifest.get("run_id"),
        "problem_id": run_manifest.get("problem_id"),
        "profile": run_manifest.get("profile"),
        "runtime_version": run_manifest.get("runtime_version"),
        "runtime_pack_sha256": runtime_manifest.get("runtime_pack_sha256"),
    }
    for field, value in binding.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"当前运行现场缺少合法 {field}")

    runtime_pack_sha = str(binding["runtime_pack_sha256"])
    if not re.fullmatch(r"[a-f0-9]{64}", runtime_pack_sha):
        raise ValueError("runtime_pack.manifest.json.runtime_pack_sha256 非法")
    runtime_pack_path = run_dir / "runtime_pack.md"
    if not runtime_pack_path.is_file():
        raise FileNotFoundError(f"缺少 runtime_pack.md：{runtime_pack_path}")
    actual_runtime_pack_sha = sha256_bytes(runtime_pack_path.read_bytes())
    if actual_runtime_pack_sha != runtime_pack_sha:
        raise ValueError("runtime_pack.md SHA-256 与 runtime_pack.manifest.json 不一致")

    for field in ("profile", "runtime_version"):
        declared = runtime_manifest.get(field)
        if declared is not None and declared != binding[field]:
            raise ValueError(
                f"run_manifest.json.{field} 与 runtime_pack.manifest.json.{field} 不一致"
            )
    return {field: str(value) for field, value in binding.items()}


def verify_run_seal(run_dir: Path) -> dict[str, Any]:
    """验证 v2 封存记录与三个被封存文件的现场哈希。"""
    seal = _load_json_object(run_dir / "seal_record.json", "seal_record.json")
    _validate_json_schema(seal, "schemas/run_seal.schema.json", "seal_record.json")
    run_manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if seal.get("run_id") != run_manifest.get("run_id"):
        raise ValueError("seal_record.run_id 与 run_manifest.run_id 不一致")

    sealed_files = {
        "run_manifest_sha256": run_dir / "run_manifest.json",
        "transitions_sha256": run_dir / "transitions.jsonl",
        "evidence_manifest_sha256": run_dir / "run_evidence_manifest.json",
    }
    for field, path in sealed_files.items():
        if not path.is_file():
            raise FileNotFoundError(f"seal_record 引用文件不存在：{path.name}")
        actual = sha256_bytes(path.read_bytes())
        if seal.get(field) != actual:
            raise ValueError(f"seal_record.{field} 与现场文件不一致")
    return seal


def _validate_json_schema(data: dict[str, Any], schema_relative: str, label: str) -> None:
    """按仓库内 Draft 2020-12 Schema 校验对象并汇总全部字段错误。"""
    schema_path = ROOT / schema_relative
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError(f"{label} 不符合 Schema：{details}")


def _validate_gate_business_artifact(
    run_dir: Path,
    filename: str,
    role: str,
    schema_relative: str,
    schema_version: str,
    binding: Mapping[str, str],
) -> bytes:
    """校验单个 Gate 业务产物的结构、身份、类型和内容，返回原始字节。"""
    path = run_dir / filename
    raw = path.read_bytes() if path.is_file() else b""
    if not raw:
        raise ValueError(f"Gate 产物缺失或为空：{filename}")
    try:
        artifact = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Gate 产物 {filename} 无法解析：{exc}") from exc
    if not isinstance(artifact, dict):
        raise ValueError(f"Gate 产物 {filename} 必须是 JSON 对象")
    _validate_json_schema(artifact, schema_relative, filename)

    for field, expected in binding.items():
        if artifact.get(field) != expected:
            raise ValueError(f"{filename}.{field} 与当前运行现场不一致")
    if role != "gate_5_review":
        if artifact.get("artifact_type") != role:
            raise ValueError(f"{filename}.artifact_type 必须为 {role}")
        if artifact.get("schema_version") != schema_version:
            raise ValueError(f"{filename}.schema_version 必须为 {schema_version}")
    return raw


def build_gate_artifact_manifest(
    run_dir: Path,
    gate: int,
    *,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """从已完成业务产物构建单 Gate 身份与哈希清单。"""
    if gate not in GATE_ARTIFACT_SPECS:
        raise ValueError(f"未知 Gate：{gate}（允许 0-5）")
    binding = _load_current_run_binding(run_dir)
    artifacts: list[dict[str, Any]] = []
    for filename, role, schema_relative, schema_version in GATE_ARTIFACT_SPECS[gate]:
        raw = _validate_gate_business_artifact(
            run_dir,
            filename,
            role,
            schema_relative,
            schema_version,
            binding,
        )
        artifacts.append(
            {
                "path": filename,
                "role": role,
                "schema": schema_relative,
                "schema_version": schema_version,
                "sha256": sha256_bytes(raw),
                "size_bytes": len(raw),
            }
        )
    return {
        "manifest_version": "1.0.0",
        "gate": gate,
        "completed_at": completed_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        **binding,
        "artifacts": artifacts,
    }


def write_gate_artifact_manifest(
    run_dir: Path,
    gate: int,
    *,
    completed_at: str | None = None,
) -> Path:
    """校验业务内容后写入 gate_artifacts/gate_N.manifest.json。"""
    manifest = build_gate_artifact_manifest(run_dir, gate, completed_at=completed_at)
    manifest_path = run_dir / "gate_artifacts" / f"gate_{gate}.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(manifest_path, manifest)
    return manifest_path


def verify_gate_artifacts(run_dir: Path, gate: int) -> dict[str, Any]:
    """验证 Gate 清单、精确文件集合、业务 Schema、运行身份及内容哈希。"""
    if gate not in GATE_ARTIFACT_SPECS:
        raise ValueError(f"未知 Gate：{gate}（允许 0-5）")
    manifest_path = run_dir / "gate_artifacts" / f"gate_{gate}.manifest.json"
    manifest = _load_json_object(manifest_path, f"gate_{gate}.manifest.json")
    _validate_json_schema(
        manifest,
        "schemas/gate_artifact_manifest.schema.json",
        f"gate_{gate}.manifest.json",
    )
    if manifest.get("gate") != gate:
        raise ValueError(f"gate_{gate}.manifest.json.gate 必须为 {gate}")

    binding = _load_current_run_binding(run_dir)
    for field, expected in binding.items():
        if manifest.get(field) != expected:
            raise ValueError(f"gate_{gate}.manifest.json.{field} 与当前运行现场不一致")

    expected_specs = GATE_ARTIFACT_SPECS[gate]
    expected_paths = {spec[0] for spec in expected_specs}
    entries = manifest.get("artifacts", [])
    actual_paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    if len(actual_paths) != len(set(actual_paths)):
        raise ValueError(f"gate_{gate}.manifest.json.artifacts 存在重复路径")
    if set(actual_paths) != expected_paths:
        raise ValueError(
            f"gate_{gate}.manifest.json 产物集合错误："
            f"期望 {sorted(expected_paths)}，实际 {sorted(str(path) for path in actual_paths)}"
        )
    entries_by_path = {entry["path"]: entry for entry in entries}
    for filename, role, schema_relative, schema_version in expected_specs:
        entry = entries_by_path[filename]
        expected_metadata = {
            "role": role,
            "schema": schema_relative,
            "schema_version": schema_version,
        }
        for field, expected in expected_metadata.items():
            if entry.get(field) != expected:
                raise ValueError(f"gate_{gate}.manifest.json {filename}.{field} 不符合固定契约")
        raw = _validate_gate_business_artifact(
            run_dir,
            filename,
            role,
            schema_relative,
            schema_version,
            binding,
        )
        if entry.get("sha256") != sha256_bytes(raw):
            raise ValueError(f"Gate {gate} 产物 {filename} SHA-256 不匹配")
        if entry.get("size_bytes") != len(raw):
            raise ValueError(f"Gate {gate} 产物 {filename} size_bytes 不匹配")
    if gate == 3:
        result_report = _load_json_object(run_dir / "result_report.json", "result_report.json")
        result_manifest = _load_json_object(
            run_dir / "result_manifest.json", "result_manifest.json"
        )
        model_errors = validate_model_and_execution(
            result_report, result_manifest, run_dir=run_dir
        )
        if model_errors:
            raise ValueError("Gate 3 数学或复现检查失败：" + "；".join(model_errors))
    if gate == 4:
        result_report = _load_json_object(run_dir / "result_report.json", "result_report.json")
        result_manifest = _load_json_object(
            run_dir / "result_manifest.json", "result_manifest.json"
        )
        claim_map = _load_json_object(run_dir / "paper_claim_map.json", "paper_claim_map.json")
        claim_errors = validate_model_and_execution(
            result_report,
            result_manifest,
            run_dir=run_dir,
            claim_map=claim_map,
        )
        if claim_errors:
            raise ValueError("Gate 4 Claim-Result 检查失败：" + "；".join(claim_errors))
    return manifest


def _load_and_validate_gate_5_review(run_dir: Path, reviewer: str) -> tuple[dict[str, Any], str]:
    """读取并验证 Gate 5 人工审核记录，返回记录和 SHA-256。"""
    if not str(reviewer).strip():
        raise ValueError("reviewer 不能为空")
    review_path = run_dir / "gate_5_review.json"
    if not review_path.is_file():
        raise FileNotFoundError(f"缺少 Gate 5 人工审核记录：{review_path}")
    raw = review_path.read_bytes()
    try:
        review = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"gate_5_review.json 无法解析：{exc}") from exc
    if not isinstance(review, dict):
        raise ValueError("gate_5_review.json 必须是 JSON 对象")

    _validate_gate_5_review_schema(review)
    current_binding = _load_current_run_binding(run_dir)
    for field, expected in current_binding.items():
        if review.get(field) != expected:
            raise ValueError(
                f"gate_5_review.{field} 与当前运行现场不一致："
                f"审核记录为 {review.get(field)!r}，当前运行为 {expected!r}"
            )
    if review.get("target_gate") != 5:
        raise ValueError("gate_5_review.target_gate 必须为 5")
    if review.get("reviewer") != str(reviewer).strip():
        raise ValueError("gate_5_review.reviewer 必须与 mark_run_completed 参数一致")
    _parse_datetime(review.get("reviewed_at"), "reviewed_at")
    if review.get("decision") != "approved":
        raise ValueError("gate_5_review.decision 必须为 approved")
    if review.get("final_acceptance") is not True:
        raise ValueError("gate_5_review.final_acceptance 必须为 true")
    if not isinstance(review.get("reason"), str) or len(review.get("reason", "").strip()) < 10:
        raise ValueError("gate_5_review.reason 至少需要 10 个字符")
    checklist = review["checklist"]
    if set(checklist) != set(GATE_5_CHECKLIST_KEYS):
        raise ValueError("gate_5_review.checklist 必须且只能包含固定八项")
    failed = [key for key in GATE_5_CHECKLIST_KEYS if checklist.get(key) is not True]
    if failed:
        raise ValueError(f"gate_5_review.checklist 存在未通过项：{', '.join(failed)}")
    return review, sha256_bytes(raw)


def mark_run_completed(run_dir: Path, reviewer: str) -> None:
    """将运行标记为 completed 终态（必须已严格到达 Gate 5 且审核记录获批）。"""
    state = replay_transition_log(run_dir)
    if state["completed"]:
        raise ValueError("运行已标记为 completed，不能重复标记。")
    if state["max_gate"] < 5:
        raise ValueError(f"最大 Gate 为 {state['max_gate']}，0-4 的运行不得被标记为 completed。")
    if state["current_gate"] != 5:
        raise ValueError(f"当前不在 Gate 5（当前 Gate：{state['current_gate']}），无法完成运行。")

    review, review_sha = _load_and_validate_gate_5_review(run_dir, reviewer)
    if state.get("transition_version") == TRANSITION_VERSION:
        verify_gate_artifacts(run_dir, 5)
        entry = {
            "transition_version": TRANSITION_VERSION,
            "completed_gate": 5,
            "next_gate": None,
            "state": "completed",
            "reviewer": str(reviewer).strip(),
            "decision": "approved",
            "review_record": "gate_5_review.json",
            "review_record_sha256": review_sha,
            "reviewed_at": review["reviewed_at"],
            "note": "Gate 5 业务产物与最终审核均通过，运行完成。",
        }
    else:
        entry = {
            "from": 5,
            "to": None,
            "state": "completed",
            "reviewer": str(reviewer).strip(),
            "decision": "approved",
            "review_record": "gate_5_review.json",
            "review_record_sha256": review_sha,
            "reviewed_at": review["reviewed_at"],
            "note": "Gate 5 通过，运行完成。",
        }
    if state.get("transition_version") == TRANSITION_VERSION:
        _append_transition_event(run_dir / "transitions.jsonl", entry)
    else:
        transitions_path = run_dir / "transitions.jsonl"
        atomic_write_text(
            transitions_path,
            transitions_path.read_text(encoding="utf-8")
            + json.dumps(entry, ensure_ascii=False)
            + "\n",
        )

    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.is_file():
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if run_manifest.get("manifest_version") != "2.0.0":
            run_manifest["run_status"] = "completed"
            run_manifest.setdefault("integrity_status", "unsealed")
            write_json(manifest_path, run_manifest)


def create_prompt_regression_run(args: argparse.Namespace) -> Path:
    """创建轻量 Prompt 回归目录；该流程不进入 Gate，也不能生成晋级证据。"""
    run_id = args.run_id or f"{date.today().isoformat()}_{normalize_problem_dir(args.problem)}_prompt"
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"运行目录已存在：{run_dir}")
    run_dir.mkdir(parents=True)

    profile = json.loads(
        (ROOT / "runtime_profiles" / f"{args.profile}.json").read_text(encoding="utf-8")
    )
    pack = build_pack(args.profile, args.candidate_patch, args.exclude_patch)
    pack_manifest = build_manifest(
        args.profile, pack, args.candidate_patch, args.exclude_patch
    )
    atomic_write_text(run_dir / "runtime_pack.md", pack)
    write_json(run_dir / "runtime_pack.manifest.json", pack_manifest)
    write_json(run_dir / "runtime_profile.snapshot.json", profile)
    write_json(
        run_dir / "run_manifest.json",
        {
            "manifest_version": "2.0.0",
            "run_id": run_id,
            "workflow": "prompt_regression",
            "problem_id": args.problem,
            "profile": args.profile,
            "runtime_version": profile["version"],
            "runtime_pack_sha256": pack_manifest["runtime_pack_sha256"],
            "initial_state": "initialized",
            "eligible_for_promotion": False,
            "evidence_validity": "prompt_behavior_only",
        },
    )
    write_json(
        run_dir / "request.json",
        {"prompt": "", "model": "", "source": "pending", "response_reference": None},
    )
    write_json(run_dir / "response.json", {"_note": "待执行轻量提示词行为测试"})
    return run_dir


def advance_run(run_dir: Path, reviewer: str, decision: str = "approved") -> dict[str, Any]:
    """推进一次 Gate；离开当前 Gate 时复用业务产物机器校验。"""
    state = replay_transition_log(run_dir)
    current = state["current_gate"]
    if current is None:
        record_transition(run_dir, None, 0, reviewer, decision)
    elif current == 5:
        raise ValueError("当前已在 Gate 5；请使用 complete 完成最终验收")
    else:
        record_transition(run_dir, current, current + 1, reviewer, decision)
    return replay_transition_log(run_dir)


def verify_run(run_dir: Path) -> dict[str, Any]:
    """复核运行现场；部分 Gate 运行可返回状态，但不会被标记为晋级证据。"""
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if manifest.get("workflow") == "prompt_regression":
        return {
            "run_id": manifest.get("run_id"),
            "workflow": "prompt_regression",
            "eligible_for_promotion": False,
            "verified_gates": [],
            "completed": False,
            "sealed": False,
        }
    state = replay_transition_log(run_dir)
    verified_gates: list[int] = []
    for gate in state.get("completed_gates", []):
        verify_gate_artifacts(run_dir, gate)
        verified_gates.append(gate)
    seal_errors: list[str] = []
    try:
        verify_run_seal(run_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        seal_errors.append(str(exc))

    promotion_errors = list(seal_errors)
    if manifest.get("promotion_evidence") is not True:
        promotion_errors.append("运行初始化时未声明为晋级证据")
    if state.get("transition_version") != TRANSITION_VERSION:
        promotion_errors.append("晋级证据必须使用 Gate 语义完成契约 v2")
    if not state["completed"] or state["max_gate"] != 5:
        promotion_errors.append("Gate 0-5 尚未完整完成")

    if not promotion_errors:
        try:
            metadata = _load_json_object(run_dir / "ai_run_metadata.json", "ai_run_metadata.json")
            _validate_json_schema(
                metadata, "schemas/ai_run_metadata.schema.json", "ai_run_metadata.json"
            )
            if metadata.get("status") != "completed":
                promotion_errors.append("ai_run_metadata.status 不是 completed")
            request = _load_json_object(run_dir / "request.json", "request.json")
            if request.get("source") != "real_ai_run":
                promotion_errors.append("request.source 不是 real_ai_run")
            automatic = _load_json_object(
                run_dir / "automatic_evaluation.json", "automatic_evaluation.json"
            )
            if automatic.get("result") != "pass" or automatic.get("errors"):
                promotion_errors.append("automatic_evaluation 未通过")

            from finalize_run_evidence import load_policy, validate_evidence_manifest

            policy = load_policy()
            required = policy["run_evidence_requirements"]["ai_run_metadata_checks"][
                "required_artifacts"
            ]
            evidence = _load_json_object(
                run_dir / "run_evidence_manifest.json", "run_evidence_manifest.json"
            )
            promotion_errors.extend(validate_evidence_manifest(run_dir, evidence, required))
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            promotion_errors.append(str(exc))

    return {
        "run_id": manifest.get("run_id"),
        "workflow": manifest.get("workflow"),
        "mode": manifest.get("mode"),
        "eligible_for_promotion": not promotion_errors,
        "verified_gates": verified_gates,
        "current_gate": state["current_gate"],
        "completed": state["completed"],
        "sealed": not seal_errors,
        "promotion_readiness_errors": promotion_errors,
    }


def complete_and_seal_run(run_dir: Path, reviewer: str) -> dict[str, Any]:
    """完成 Gate 5 并封存；中断后重复调用可从已完成转换处恢复。"""
    state = replay_transition_log(run_dir)
    if not state["completed"]:
        mark_run_completed(run_dir, reviewer)

    seal_path = run_dir / "seal_record.json"
    if seal_path.is_file():
        verify_run_seal(run_dir)
    else:
        from finalize_run_evidence import finalize_run_evidence

        finalize_run_evidence(run_dir)
    return verify_run(run_dir)


def _add_init_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workflow", required=True, choices=["prompt_regression", "full_replay", "new_problem"]
    )
    parser.add_argument("--problem", required=True, help="题号，例如 2024-C。")
    parser.add_argument("--profile", default="engineering_optimization")
    parser.add_argument("--mode", default="standard", choices=["strict", "standard", "emergency"])
    parser.add_argument("--materials", help="材料根目录；new_problem 必须显式提供。")
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--candidate-patch", action="append", default=[], dest="candidate_patch")
    parser.add_argument("--exclude-patch", action="append", default=[])
    parser.add_argument("--promotion-evidence", action="store_true")
    parser.add_argument("--experiment-group-id")
    parser.add_argument("--experiment-role", choices=["baseline", "patch_only"])
    parser.add_argument("--target-patch")
    parser.set_defaults(material_file=[])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="可追溯数学建模工作流 CLI。")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_init_arguments(commands.add_parser("init", help="冻结材料、Profile、Patch 和运行包"))
    advance = commands.add_parser("advance", help="验证并推进一个 Gate")
    advance.add_argument("--run-dir", required=True)
    advance.add_argument("--reviewer", required=True)
    advance.add_argument("--decision", default="approved", choices=["approved", "rejected"])
    complete = commands.add_parser("complete", help="验证 Gate 5 并完成运行")
    complete.add_argument("--run-dir", required=True)
    complete.add_argument("--reviewer", required=True)
    verify = commands.add_parser("verify", help="复核当前运行状态与已完成 Gate")
    verify.add_argument("--run-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "init":
            if args.workflow == "prompt_regression":
                run_dir = create_prompt_regression_run(args)
                print(f"[READY] 已创建轻量 Prompt 回归：{run_dir}")
                return
            if args.workflow == "new_problem" and not args.materials:
                raise ValueError("new_problem 必须显式提供 --materials")
            args.gates = "0-5"
            if args.workflow == "new_problem":
                run_dir, material_ready = create_new_problem_run(args)
            else:
                run_dir, material_ready = create_full_replay_run(args)
            print(f"已创建运行目录：{run_dir}")
            if not material_ready:
                raise ValueError("题面、附件、模板或 SHA-256 校验未通过")
            print("[READY] 材料与冻结快照已就绪；请从 Gate 0 开始。")
        elif args.command == "advance":
            state = advance_run(Path(args.run_dir), args.reviewer, args.decision)
            print(json.dumps(state, ensure_ascii=False, indent=2))
        elif args.command == "complete":
            report = complete_and_seal_run(Path(args.run_dir), args.reviewer)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print("[SEALED] Gate 0-5 已完成并封存。")
        elif args.command == "verify":
            print(json.dumps(verify_run(Path(args.run_dir)), ensure_ascii=False, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
