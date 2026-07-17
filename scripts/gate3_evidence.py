"""Gate 3 执行后证据的一致性、哈希与 Validator 语义绑定复核。"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "gate_3_check_evidence.schema.json"
CONTRACT_SCHEMA_PATH = ROOT / "schemas" / "gate_3_validator_contract.schema.json"
INPUT_MANIFEST_SCHEMA_PATH = ROOT / "schemas" / "gate_3_input_manifest.schema.json"
EXECUTION_ATTESTATION_SCHEMA_PATH = (
    ROOT / "schemas" / "gate_3_execution_attestation.schema.json"
)
EVIDENCE_FILENAME = "gate_3_check_evidence.json"
ENGINEERING_PROFILE = "engineering_optimization"
REQUIRED_OPTIMIZATION_CHECKS = {
    "objective_recomputation",
    "constraint_residual",
    "decision_output_consistency",
    "variable_domain",
    "solver_status",
}
REQUIRED_RANDOM_CHECKS = {"random_seed_replay", "sample_manifest_consistency"}


def derive_implementation_status(validation: Mapping[str, object]) -> str:
    """由 Gate 3 结构与数学检查状态派生实现正确性。"""
    structural_status = validation.get("structural_validation")
    mathematical_status = validation.get("mathematical_validation")
    if structural_status == "passed" and mathematical_status in {
        "passed",
        "not_required",
    }:
        return "pass"
    return "fail"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_within(root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative.strip():
        return None
    path = (root / relative).resolve()
    return path if path.is_relative_to(root.resolve()) else None


def _comparison_holds(value: float, comparison: str, threshold: float) -> bool:
    if comparison == "le":
        return value <= threshold
    if comparison == "lt":
        return value < threshold
    if comparison == "ge":
        return value >= threshold
    if comparison == "gt":
        return value > threshold
    if comparison == "eq":
        return value == threshold
    if comparison == "ne":
        return value != threshold
    raise ValueError(f"未知 comparison：{comparison!r}")


def _schema_errors(value: Any, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.absolute_path))
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
        for error in errors
    ]


def _validate_input_manifest_references(
    path: Path,
    run_root: Path,
    check_id: str,
    contract: Mapping[str, Any],
) -> list[str]:
    """复核当前 Run 输入文件集合、角色和内容哈希。"""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{check_id} 的输入 Manifest 无法解析：{exc}"]
    schema_errors = _schema_errors(manifest, INPUT_MANIFEST_SCHEMA_PATH)
    errors = [f"{check_id} 的输入 Manifest Schema：{error}" for error in schema_errors]
    artifacts = manifest.get("artifacts") if isinstance(manifest, Mapping) else None
    if not isinstance(artifacts, list):
        errors.append(f"{check_id} 的输入 Manifest 必须声明 artifacts 列表")
        return errors
    role_counts: dict[str, int] = {}
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            errors.append(f"{check_id} 的输入 Manifest artifact 必须为对象")
            continue
        relative = artifact.get("path")
        declared_sha = artifact.get("sha256")
        role = artifact.get("role")
        if not isinstance(relative, str) or not relative.strip():
            errors.append(f"{check_id} 的输入 Manifest artifact 缺少 path")
            continue
        if not isinstance(declared_sha, str) or len(declared_sha) != 64:
            errors.append(f"{check_id} 的输入 Manifest artifact 缺少 SHA-256：{relative}")
            continue
        if not isinstance(role, str) or not role.strip():
            errors.append(f"{check_id} 的输入 Manifest artifact 缺少 role：{relative}")
            continue
        role_counts[role] = role_counts.get(role, 0) + 1
        if relative in seen_paths:
            errors.append(f"{check_id} 的输入 Manifest 重复引用文件：{relative}")
        seen_paths.add(relative)
        referenced = _resolve_within(run_root, relative)
        if referenced is None:
            errors.append(f"{check_id} 的输入 Manifest 引用了其他 Run 路径")
        elif not referenced.is_file():
            errors.append(f"{check_id} 的输入 Manifest 引用文件不存在：{relative}")
        elif _sha256(referenced) != declared_sha:
            errors.append(f"{check_id} 的输入 Manifest artifact SHA-256 不匹配：{relative}")
    required_roles = contract["required_input_roles"]
    if contract["exact_input_set"]:
        extra_roles = set(role_counts) - set(required_roles)
        if extra_roles:
            errors.append(f"{check_id} 的输入 Manifest 包含额外输入角色：{sorted(extra_roles)}")
    for role, limits in required_roles.items():
        count = role_counts.get(role, 0)
        minimum = int(limits["min_items"])
        maximum = limits.get("max_items")
        if count < minimum:
            errors.append(f"{check_id} 的输入 Manifest 角色 {role} 少于 {minimum} 项")
        if maximum is not None and count > int(maximum):
            errors.append(f"{check_id} 的输入 Manifest 角色 {role} 多于 {maximum} 项")
    return errors


def _load_validator_contract(check: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """加载可信 Validator Contract，并绑定其声明的 Validator 与报告 Schema。"""
    check_id = str(check["check_id"])
    validator_root = (ROOT / "validators").resolve()
    contract_path = _resolve_within(ROOT, check["validator_contract_path"])
    if contract_path is None or not contract_path.is_relative_to(validator_root):
        return None, [f"{check_id} 的 Validator Contract 不在允许 Validator 根目录内"]
    if not contract_path.is_file():
        return None, [f"{check_id} 的 Validator Contract 文件不存在"]
    if _sha256(contract_path) != check["validator_contract_sha256"]:
        return None, [f"{check_id} 的 Validator Contract SHA-256 不匹配"]
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{check_id} 的 Validator Contract 无法解析：{exc}"]
    errors = _schema_errors(contract, CONTRACT_SCHEMA_PATH)
    if errors or not isinstance(contract, dict):
        return None, [f"{check_id} 的 Validator Contract：{error}" for error in errors]
    if contract["validator_path"] != check["validator_path"]:
        errors.append(f"{check_id} 的 Validator Contract 与 Evidence validator_path 不一致")
    if contract["validator_sha256"] != check["validator_sha256"]:
        errors.append(f"{check_id} 的 Validator Contract 与 Evidence validator_sha256 不一致")
    if check_id not in contract["supported_check_ids"]:
        errors.append(f"{check_id} 不受 Validator Contract 支持")
    if check_id not in contract["required_observations"]:
        errors.append(f"{check_id} 缺少 Validator Contract required_observations")
    validator_path = _resolve_within(ROOT, contract["validator_path"])
    if validator_path is None or not validator_path.is_relative_to(validator_root):
        errors.append(f"{check_id} 的 Contract validator_path 不在允许 Validator 根目录内")
    elif not validator_path.is_file() or _sha256(validator_path) != contract["validator_sha256"]:
        errors.append(f"{check_id} 的 Contract Validator SHA-256 不匹配")
    report_schema_path = _resolve_within(ROOT, contract["report_schema_path"])
    if report_schema_path is None or not report_schema_path.is_relative_to(validator_root):
        errors.append(f"{check_id} 的报告 Schema 不在允许 Validator 根目录内")
    elif not report_schema_path.is_file():
        errors.append(f"{check_id} 的报告 Schema 文件不存在")
    elif _sha256(report_schema_path) != contract["report_schema_sha256"]:
        errors.append(f"{check_id} 的报告 Schema SHA-256 不匹配")
    else:
        try:
            Draft202012Validator.check_schema(json.loads(report_schema_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{check_id} 的报告 Schema 无效：{exc}")
    return contract, errors


def _validate_execution_attestation(
    evidence: Mapping[str, Any], run_root: Path
) -> tuple[Mapping[str, Any] | None, list[str]]:
    """复核父进程执行证明及其绑定的日志、输入和报告。"""
    relative = evidence["execution_attestation_path"]
    expected_sha = evidence["execution_attestation_sha256"]
    attestation_path = _resolve_within(run_root, relative)
    if attestation_path is None:
        return None, ["Gate 3 执行证明路径越出当前 Run"]
    if not attestation_path.is_file():
        return None, ["Gate 3 执行证明文件不存在"]
    if _sha256(attestation_path) != expected_sha:
        return None, ["Gate 3 执行证明 SHA-256 不匹配"]
    try:
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"Gate 3 执行证明无法解析：{exc}"]
    errors = [
        f"Gate 3 执行证明 Schema：{error}"
        for error in _schema_errors(attestation, EXECUTION_ATTESTATION_SCHEMA_PATH)
    ]
    if errors or not isinstance(attestation, Mapping):
        return None, errors
    if attestation["status"] != "completed" or attestation["exit_code"] != 0:
        errors.append("Gate 3 执行证明不是成功完成状态")

    for path_field, hash_field, label in (
        ("stdout_path", "stdout_sha256", "stdout.log"),
        ("stderr_path", "stderr_sha256", "stderr.log"),
        ("input_manifest_path", "input_manifest_sha256", "input_manifest.json"),
        ("report_path", "report_sha256", "report.json"),
    ):
        bound_path = _resolve_within(run_root, attestation[path_field])
        if bound_path is None:
            errors.append(f"Gate 3 执行证明 {label} 路径越出当前 Run")
        elif not bound_path.is_file():
            errors.append(f"Gate 3 执行证明 {label} 文件不存在")
        elif _sha256(bound_path) != attestation[hash_field]:
            errors.append(f"Gate 3 执行证明 {label} SHA-256 不匹配")

    validator_root = (ROOT / "validators").resolve()
    validator_path = _resolve_within(ROOT, attestation["validator_path"])
    if validator_path is None or not validator_path.is_relative_to(validator_root):
        errors.append("Gate 3 执行证明 Validator 路径不可信")
    elif not validator_path.is_file() or _sha256(validator_path) != attestation["validator_sha256"]:
        errors.append("Gate 3 执行证明 Validator SHA-256 不匹配")
    contract_path = _resolve_within(ROOT, attestation["validator_contract_path"])
    if contract_path is None or not contract_path.is_relative_to(validator_root):
        errors.append("Gate 3 执行证明 Validator Contract 路径不可信")
    elif not contract_path.is_file() or _sha256(contract_path) != attestation["validator_contract_sha256"]:
        errors.append("Gate 3 执行证明 Validator Contract SHA-256 不匹配")

    cwd = _resolve_within(run_root, attestation["cwd"])
    input_path = _resolve_within(run_root, attestation["input_manifest_path"])
    report_path = _resolve_within(run_root, attestation["report_path"])
    if cwd is None or cwd != (run_root / "validation").resolve():
        errors.append("Gate 3 执行证明 cwd 不是固定 validation 工作目录")
    if input_path is not None and input_path.parent != cwd:
        errors.append("Gate 3 执行证明 Input Manifest 不在固定 cwd")
    if report_path is not None and report_path.parent != cwd:
        errors.append("Gate 3 执行证明 Report 不在固定 cwd")
    if validator_path is not None and input_path is not None and report_path is not None:
        expected_argv = [
            attestation["python_executable"],
            str(validator_path),
            "--input-manifest",
            input_path.name,
            "--report",
            report_path.name,
        ]
        if attestation["argv"] != expected_argv:
            errors.append("Gate 3 执行证明 argv 不是固定 Validator 调用")
    if attestation["python_executable"] != sys.executable:
        errors.append("Gate 3 执行证明 Python executable 与当前可信父进程不一致")
    try:
        started_at = datetime.fromisoformat(str(attestation["started_at"]))
        ended_at = datetime.fromisoformat(str(attestation["ended_at"]))
        elapsed = (ended_at - started_at).total_seconds()
        if elapsed < 0 or abs(elapsed - float(attestation["duration_seconds"])) > 1.0:
            errors.append("Gate 3 执行证明时间区间与 duration_seconds 不一致")
    except (TypeError, ValueError):
        errors.append("Gate 3 执行证明时间字段无法复算")
    return attestation, errors


def _validate_report_semantics(
    check: Mapping[str, Any], contract: Mapping[str, Any], report_path: Path
) -> list[str]:
    """确认综合报告中存在与 Evidence 同一 check_id 的独立结果区段。"""
    check_id = str(check["check_id"])
    required_observations = contract["required_observations"].get(check_id)
    if not isinstance(required_observations, list):
        return [f"{check_id} 缺少 Validator Contract required_observations"]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{check_id} 的报告无法解析：{exc}"]
    schema_path = _resolve_within(ROOT, contract["report_schema_path"])
    assert schema_path is not None
    errors = _schema_errors(report, schema_path)
    if errors or not isinstance(report, Mapping):
        return [f"{check_id} 的报告 Schema：{error}" for error in errors]
    if report["validator_path"] != check["validator_path"]:
        errors.append(f"{check_id} 的报告 validator_path 与 Evidence 不一致")
    if report["validator_sha256"] != check["validator_sha256"]:
        errors.append(f"{check_id} 的报告 validator_sha256 与 Evidence 不一致")
    if report["input_manifest_sha256"] != check["input_manifest_sha256"]:
        errors.append(f"{check_id} 的报告 input_manifest_sha256 与 Evidence 不一致")
    if check["check_type"] != contract["check_types"][check_id]:
        errors.append(f"{check_id} 的 check_type 与 Validator Contract 不一致")
    sections = [item for item in report["checks"] if item["check_id"] == check_id]
    if len(sections) != 1:
        errors.append(f"{check_id} 的报告必须包含且只能包含一个同名检查区段")
        return errors
    report_observations = {item["name"]: item["value"] for item in sections[0]["observations"]}
    required = set(required_observations)
    missing = required - set(report_observations)
    if missing:
        errors.append(f"{check_id} 的报告缺少必需 observation：{sorted(missing)}")
    evidence_observations = {item["name"]: item["value"] for item in check["observations"]}
    if set(evidence_observations) != set(report_observations):
        errors.append(f"{check_id} 的 Evidence observations 与报告区段不一致")
    for name, value in evidence_observations.items():
        if report_observations.get(name) != value:
            errors.append(f"{check_id} 的 observation {name} 与报告数值不一致")
    evidence_rules = {
        item["name"]: (item["comparison"], float(item["threshold"]))
        for item in check["observations"]
    }
    contract_rules = {
        name: (rule["comparison"], float(rule["threshold"]))
        for name, rule in contract["observation_rules"][check_id].items()
    }
    if evidence_rules != contract_rules:
        errors.append(f"{check_id} 的 observation 比较规则与 Validator Contract 不一致")
    return errors


def validate_gate_3_check_evidence(evidence: object, run_dir: Path) -> list[str]:
    """重算证据结论，不信任声明的哈希、布尔值、路径或 check_id 标签。"""
    errors = _schema_errors(evidence, SCHEMA_PATH)
    if errors or not isinstance(evidence, Mapping):
        return errors
    run_root = run_dir.resolve()
    validator_root = (ROOT / "validators").resolve()
    attestation, attestation_errors = _validate_execution_attestation(evidence, run_root)
    errors.extend(attestation_errors)
    seen_ids: set[str] = set()
    for check in evidence["checks"]:
        assert isinstance(check, Mapping)
        check_id = str(check["check_id"])
        if check_id in seen_ids:
            errors.append(f"检查 ID 重复：{check_id}")
        seen_ids.add(check_id)
        contract, contract_errors = _load_validator_contract(check)
        errors.extend(contract_errors)
        if attestation is not None:
            attestation_bindings = {
                "validator_path": "validator_path",
                "validator_sha256": "validator_sha256",
                "validator_contract_path": "validator_contract_path",
                "validator_contract_sha256": "validator_contract_sha256",
                "input_manifest_path": "input_manifest_path",
                "input_manifest_sha256": "input_manifest_sha256",
                "report_path": "report_path",
                "report_sha256": "report_sha256",
                "exit_code": "exit_code",
            }
            for evidence_field, attestation_field in attestation_bindings.items():
                if check[evidence_field] != attestation[attestation_field]:
                    errors.append(
                        f"{check_id} 的 {evidence_field} 与父进程执行证明不一致"
                    )

        validator_path = _resolve_within(ROOT, check["validator_path"])
        if validator_path is None or not validator_path.is_relative_to(validator_root):
            errors.append(f"{check_id} 的 validator_path 不在允许 Validator 根目录内")
        elif not validator_path.is_file():
            errors.append(f"{check_id} 的 Validator 文件不存在")
        elif _sha256(validator_path) != check["validator_sha256"]:
            errors.append(f"{check_id} 的 Validator SHA-256 不匹配")

        report_path: Path | None = None
        for path_field, hash_field, label in (
            ("input_manifest_path", "input_manifest_sha256", "输入 Manifest"),
            ("report_path", "report_sha256", "报告"),
        ):
            path = _resolve_within(run_root, check[path_field])
            if path is None:
                errors.append(f"{check_id} 的 {label} 路径越出当前 Run")
            elif not path.is_file():
                errors.append(f"{check_id} 的 {label} 文件不存在")
            elif _sha256(path) != check[hash_field]:
                errors.append(f"{check_id} 的 {label} SHA-256 不匹配")
            elif path_field == "input_manifest_path":
                if contract is not None:
                    errors.extend(
                        _validate_input_manifest_references(path, run_root, check_id, contract)
                    )
            else:
                report_path = path
        if contract is not None and report_path is not None:
            errors.extend(_validate_report_semantics(check, contract, report_path))

        if check["exit_code"] != 0:
            errors.append(f"{check_id} 的 exit_code 不是 0")
        observations_passed = True
        for observation in check["observations"]:
            assert isinstance(observation, Mapping)
            computed = _comparison_holds(
                float(observation["value"]),
                str(observation["comparison"]),
                float(observation["threshold"]),
            )
            observations_passed = observations_passed and computed
            if observation["passed"] is not computed:
                errors.append(f"{check_id} 的 observation {observation['name']} 声明结果与数值比较不一致")
        computed_check_passed = observations_passed and check["exit_code"] == 0
        if check["passed"] is not computed_check_passed:
            errors.append(f"{check_id} 的 passed 声明与现场复算不一致")
    return errors


def collect_gate_3_math_validation(
    run_dir: Path,
    result_report: Mapping[str, Any],
    result_manifest: Mapping[str, Any],
) -> dict[str, object]:
    """返回结构、数学和正式结果资格；旧记录缺少新合同仍可只读。"""
    if result_report.get("profile") != ENGINEERING_PROFILE:
        return {"structural_validation": "passed", "mathematical_validation": "not_required", "formal_result_eligible": False, "errors": []}
    evidence_path = run_dir / EVIDENCE_FILENAME
    if not evidence_path.is_file():
        return {"structural_validation": "passed", "mathematical_validation": "unverified", "formal_result_eligible": False, "errors": ["缺少 Gate 3 可执行数学检查证据"]}
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"structural_validation": "passed", "mathematical_validation": "failed", "formal_result_eligible": False, "errors": [f"Gate 3 证据无法解析：{exc}"]}
    errors = validate_gate_3_check_evidence(evidence, run_dir)
    check_ids = {item.get("check_id") for item in evidence.get("checks", []) if isinstance(item, Mapping)}
    required = set(REQUIRED_OPTIMIZATION_CHECKS)
    if result_manifest.get("deterministic_expected") is False:
        required.update(REQUIRED_RANDOM_CHECKS)
    missing = required - check_ids
    if missing:
        errors.append(f"Gate 3 缺少必需机器检查：{sorted(missing)}")
    failed = {
        str(item.get("check_id"))
        for item in evidence.get("checks", [])
        if isinstance(item, Mapping)
        and item.get("check_id") in required
        and item.get("passed") is not True
    }
    if failed:
        errors.append(f"Gate 3 必需机器检查未通过：{sorted(failed)}")
    if errors:
        return {"structural_validation": "passed", "mathematical_validation": "failed", "formal_result_eligible": False, "errors": errors}
    return {"structural_validation": "passed", "mathematical_validation": "passed", "formal_result_eligible": True, "errors": []}
