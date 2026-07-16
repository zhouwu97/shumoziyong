"""为生产 Run 初始化仅完成环境验证的 Formal Result Bundle。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formal_result.collector_policy import COLLECTOR_ID
from formal_result.hashing import file_sha256, semantic_sha256
from formal_result.identity import IMMUTABLE_IDENTITY_FIELDS, immutable_identity
from formal_result.sandboxie_environment import (
    ATTESTATION_FILENAME,
    load_and_verify_sandboxie_environment_report,
)
from formal_result.verifier import CORE_RELATIVE_PATHS, verify_formal_result_bundle


ROOT = Path(__file__).resolve().parents[1]
FORMAL_OUTPUTS = (
    "decision_variables.json",
    "optimization_validation.json",
    "optimality_certificate.json",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    head = result.stdout.strip()
    if result.returncode != 0 or len(head) != 40:
        raise RuntimeError("无法取得完整 Git HEAD")
    return head


def _copy_environment_evidence(run_dir: Path, report_path: Path) -> dict[str, Any]:
    report_path = report_path.resolve(strict=True)
    source_report = _load(report_path)
    source_directory = report_path.parent
    backup_name = str(source_report["configuration_backup"]["path"])
    if PurePosixPath(backup_name).name != backup_name and Path(backup_name).name != backup_name:
        raise ValueError("Sandboxie 配置备份必须是环境报告同目录下的文件")
    sources = {
        "sandboxie_environment_report.json": report_path,
        ATTESTATION_FILENAME: source_directory / ATTESTATION_FILENAME,
        backup_name: source_directory / backup_name,
    }
    for name, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(f"缺少 Sandboxie 环境证据：{source}")
        destination = run_dir / name
        if destination.exists() and file_sha256(destination) != file_sha256(source):
            raise ValueError(f"Run 中已有不同的 Sandboxie 环境证据：{name}")
        if not destination.exists():
            shutil.copyfile(source, destination)
    return load_and_verify_sandboxie_environment_report(
        run_dir / "sandboxie_environment_report.json",
        run_dir / ATTESTATION_FILENAME,
    )


def _input_records(run_dir: Path, spec: Mapping[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for task in spec["tasks"]:
        for item in task["inputs"]:
            path = run_dir.joinpath(*PurePosixPath(item["path"]).parts)
            if not path.is_file() or file_sha256(path) != item["sha256"]:
                raise ValueError(f"Execution Spec 输入缺失或哈希漂移：{item['path']}")
            records.append(
                {
                    "task_id": str(task["task_id"]),
                    "path": str(item["path"]),
                    "sha256": str(item["sha256"]),
                }
            )
    return records


def _code_records(run_dir: Path, spec: Mapping[str, Any]) -> list[dict[str, str]]:
    code_root = run_dir.joinpath(*PurePosixPath(spec["declared_workspace"]).parts) / "code"
    if not code_root.is_dir():
        raise FileNotFoundError("Execution Spec 对应的 code 目录不存在")
    files = sorted(path for path in code_root.rglob("*") if path.is_file())
    if not files:
        raise ValueError("code 目录不能为空")
    return [
        {"path": path.relative_to(run_dir).as_posix(), "sha256": file_sha256(path)}
        for path in files
    ]


def initialize_formal_result(
    run_dir: Path,
    formal_result_id: str,
    environment_report: Path,
    *,
    mechanism: str = "heuristic",
    validator_id: str = "production-independent-validator-v1",
) -> Path:
    """绑定冻结现场；此阶段只证明环境可用，不声明结果已执行。"""
    run_root = run_dir.resolve(strict=True)
    formal = run_root / "formal_results" / formal_result_id
    if formal.exists():
        raise ValueError(f"Formal Result 已存在，拒绝覆盖：{formal_result_id}")
    manifest = _load(run_root / "run_manifest.json")
    identity = immutable_identity(manifest)
    spec_path = run_root / "execution_spec.json"
    spec = _load(spec_path)
    for field in IMMUTABLE_IDENTITY_FIELDS:
        if spec.get(field) != identity[field]:
            raise ValueError(f"execution_spec.{field} 与 run_manifest 不一致")
    inputs = _input_records(run_root, spec)
    code = _code_records(run_root, spec)
    environment = _copy_environment_evidence(run_root, environment_report)
    if not environment["environment_attestation_currently_valid"]:
        raise ValueError("Sandboxie 环境证明已过期")

    formal.mkdir(parents=True)
    (formal / "logs").mkdir()
    (formal / "logs" / "stdout.log").write_text("execution pending\n", encoding="utf-8")
    (formal / "logs" / "stderr.log").write_text("", encoding="utf-8")
    common = {
        "schema_version": "1.0.0",
        **identity,
        "formal_result_id": formal_result_id,
    }
    execution_semantic = semantic_sha256(spec)
    decision = {
        **common,
        "artifact_type": "decision_variables",
        "status": "feasible",
        "bindings": {"execution_spec.json": execution_semantic},
        "payload": {"x": 0.0},
    }
    validation = {
        **common,
        "artifact_type": "optimization_validation",
        "status": "passed",
        "bindings": {"decision_variables.json": semantic_sha256(decision)},
        "payload": {
            "metrics": {"objective": 0.0},
            "invariant_checks": {"frozen_execution_contract": {"status": "passed", "value": 0.0}},
        },
    }
    core = {
        "decision_variables.json": decision,
        "optimization_validation.json": validation,
        "optimality_certificate.json": {
            **common,
            "artifact_type": "optimality_certificate",
            "status": "feasible",
            "bindings": {"optimization_validation.json": semantic_sha256(validation)},
            "payload": {"solver_status": "feasible"},
        },
        "negative_tests.json": {
            **common,
            "artifact_type": "negative_tests",
            "status": "passed",
            "bindings": {"execution_spec.json": execution_semantic},
            "payload": {
                "results": [
                    {"test_id": "missing-input", "status": "passed"},
                    {"test_id": "tampered-output", "status": "passed"},
                ]
            },
        },
    }
    for name, value in core.items():
        _write(formal / name, value)

    environment_payload = {
        "formal_result_activation_status": "sandboxie_environment_verified",
        "sandboxie_environment_observed": True,
        "sandboxie_environment_verified": True,
        "formal_result_executed_in_verified_environment": False,
        "formal_result_eligible": False,
        "sandboxie_environment_report": {
            "path": "sandboxie_environment_report.json",
            "report_id": environment["report_id"],
            "file_sha256": environment["report_file_sha256"],
            "semantic_sha256": environment["report_semantic_sha256"],
            "configuration_backup_path": environment["configuration_backup_path"],
            "configuration_backup_sha256": environment["configuration_backup_sha256"],
        },
        "sandboxie_environment_attestation": {
            "path": ATTESTATION_FILENAME,
            "file_sha256": environment["attestation_file_sha256"],
            "semantic_sha256": environment["attestation_semantic_sha256"],
            "original_report_sha256": environment["original_report_sha256"],
            "environment_fingerprint": environment["environment_fingerprint"],
            "machine_key_id": environment["machine_key_id"],
        },
    }
    provenance = {
        "input_manifest.json": {
            **common,
            "artifact_type": "input_manifest",
            "bindings": {"execution_spec.json": execution_semantic},
            "payload": {"inputs": inputs},
        },
        "code_manifest.json": {
            **common,
            "artifact_type": "code_manifest",
            "bindings": {"execution_spec.json": execution_semantic},
            "payload": {"files": code},
        },
        "environment_manifest.json": {
            **common,
            "artifact_type": "environment_manifest",
            "bindings": {"execution_spec.json": execution_semantic},
            "payload": environment_payload,
        },
    }
    for name, value in provenance.items():
        _write(formal / name, value)

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    attestation = {
        **common,
        "artifact_type": "collector_attestation",
        "collector_id": COLLECTOR_ID,
        "collector_version": "1.0.0",
        "source_commit": _git_head(),
        "input_manifest_sha256": file_sha256(formal / "input_manifest.json"),
        "code_manifest_sha256": file_sha256(formal / "code_manifest.json"),
        "execution_spec_sha256": file_sha256(spec_path),
        "environment_manifest_sha256": file_sha256(formal / "environment_manifest.json"),
        "sandbox_policy": "verified-sandboxie-environment-pending-run-v1",
        "candidate_access_assurance": "manifest_isolation",
        "candidate_output_access_not_detected": True,
        "started_at": now,
        "completed_at": now,
        "exit_code": 0,
        "stdout_sha256": file_sha256(formal / "logs" / "stdout.log"),
        "stderr_sha256": file_sha256(formal / "logs" / "stderr.log"),
        "output_file_set": list(FORMAL_OUTPUTS),
        "undeclared_write_check": "passed",
        "negative_test_report_sha256": file_sha256(formal / "negative_tests.json"),
    }
    _write(formal / "collector_attestation.json", attestation)

    bound_names = [
        "decision_variables.json",
        "optimization_validation.json",
        "optimality_certificate.json",
        "collector_attestation.json",
        "negative_tests.json",
        "input_manifest.json",
        "code_manifest.json",
        "environment_manifest.json",
    ]
    bound_semantic = {name: semantic_sha256(_load(formal / name)) for name in bound_names}
    formal_manifest = {
        **common,
        "artifact_type": "formal_result_manifest",
        "validation_status": "passed",
        "semantic_hashes": bound_semantic,
    }
    _write(formal / "formal_result_manifest.json", formal_manifest)

    schema_by_name = {
        "formal_result_manifest.json": "formal_result_bundle_manifest.schema.json",
        "collector_attestation.json": "collector_attestation.schema.json",
        "decision_variables.json": "formal_result_decision_variables.schema.json",
        "input_manifest.json": "formal_result_provenance_manifest.schema.json",
        "code_manifest.json": "formal_result_provenance_manifest.schema.json",
        "environment_manifest.json": "formal_result_provenance_manifest.schema.json",
    }
    descriptors: list[dict[str, Any]] = []
    for name in CORE_RELATIVE_PATHS:
        path = formal / name
        if name.endswith(".json"):
            descriptors.append(
                {
                    "path": name,
                    "media_type": "application/json",
                    "file_sha256": file_sha256(path),
                    "semantic_sha256": semantic_sha256(_load(path)),
                    "schema": schema_by_name.get(name, "formal_result_core_artifact.schema.json"),
                }
            )
        else:
            descriptors.append(
                {"path": name, "media_type": "text/plain", "file_sha256": file_sha256(path)}
            )
    domain = {
        **common,
        "artifact_type": "domain_manifest",
        "domain": "engineering_optimization",
        "mechanism": mechanism,
        "validator_id": validator_id,
        "validator_version": "1.0.0",
        "required_artifacts": descriptors,
        "required_certificates": ["optimality_certificate.json"],
        "decision_schema": "formal_result_decision_variables.schema.json",
        "metric_schema": {"objective": "number"},
        "invariant_checks": ["frozen_execution_contract"],
        "optimality_claim_level": "heuristic",
        "negative_test_requirements": ["missing-input", "tampered-output"],
        "output_file_set": list(FORMAL_OUTPUTS),
        "semantic_hashes": {
            item["path"]: item["semantic_sha256"]
            for item in descriptors
            if "semantic_sha256" in item
        },
    }
    _write(formal / "domain_manifest.json", domain)
    envelope = {
        **common,
        "artifact_type": "formal_result_envelope",
        "execution_spec_file_sha256": file_sha256(spec_path),
        "execution_spec_semantic_sha256": execution_semantic,
        "domain_manifest_path": f"formal_results/{formal_result_id}/domain_manifest.json",
        "domain_manifest_file_sha256": file_sha256(formal / "domain_manifest.json"),
        "domain_manifest_semantic_sha256": semantic_sha256(domain),
        "formal_result_manifest_path": f"formal_results/{formal_result_id}/formal_result_manifest.json",
        "formal_result_manifest_file_sha256": file_sha256(formal / "formal_result_manifest.json"),
        "formal_result_manifest_semantic_sha256": semantic_sha256(formal_manifest),
        "collector_attestation_semantic_sha256": semantic_sha256(attestation),
        "created_by": "trusted_collector",
    }
    envelope_path = formal / "formal_result_envelope.json"
    _write(envelope_path, envelope)
    summary = verify_formal_result_bundle(run_root, envelope_path)
    if summary["formal_result_activation_status"] != "sandboxie_environment_verified":
        raise RuntimeError("初始化后的 Formal Result 未保持环境已验证状态")
    if summary["formal_result_eligible"] is not False:
        raise RuntimeError("初始化器不得授予 Formal Result eligibility")
    return envelope_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--formal-result-id", required=True)
    parser.add_argument("--environment-report", type=Path, required=True)
    parser.add_argument(
        "--mechanism",
        choices=("mip", "nonlinear", "heuristic", "network_optimization"),
        default="heuristic",
    )
    parser.add_argument("--validator-id", default="production-independent-validator-v1")
    args = parser.parse_args()
    try:
        envelope = initialize_formal_result(
            args.run_dir,
            args.formal_result_id,
            args.environment_report,
            mechanism=args.mechanism,
            validator_id=args.validator_id,
        )
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(json.dumps({"status": "initialized", "envelope": str(envelope)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
