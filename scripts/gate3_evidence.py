"""Gate 3 数学检查证据的独立收集与现场复核。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "gate_3_check_evidence.schema.json"
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


def _validate_input_manifest_references(path: Path, run_root: Path, check_id: str) -> list[str]:
    """拒绝输入清单将当前检查伪装成跨 Run 结果复用。"""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{check_id} 的输入 Manifest 无法解析：{exc}"]
    artifacts = manifest.get("artifacts") if isinstance(manifest, Mapping) else None
    if not isinstance(artifacts, list):
        return [f"{check_id} 的输入 Manifest 必须声明 artifacts 列表"]
    errors: list[str] = []
    for artifact in artifacts:
        relative = artifact.get("path") if isinstance(artifact, Mapping) else None
        referenced = _resolve_within(run_root, relative)
        if referenced is None:
            errors.append(f"{check_id} 的输入 Manifest 引用了其他 Run 路径")
        elif not referenced.is_file():
            errors.append(f"{check_id} 的输入 Manifest 引用文件不存在：{relative}")
    return errors


def _schema_errors(evidence: Any) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(evidence), key=lambda item: list(item.absolute_path))
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
        for error in errors
    ]


def validate_gate_3_check_evidence(evidence: object, run_dir: Path) -> list[str]:
    """重算证据结论，不信任声明的哈希、布尔值或路径。"""
    errors = _schema_errors(evidence)
    if errors or not isinstance(evidence, Mapping):
        return errors
    run_root = run_dir.resolve()
    validator_root = (ROOT / "validators").resolve()
    seen_ids: set[str] = set()
    for check in evidence["checks"]:
        assert isinstance(check, Mapping)
        check_id = str(check["check_id"])
        if check_id in seen_ids:
            errors.append(f"检查 ID 重复：{check_id}")
        seen_ids.add(check_id)

        validator_path = _resolve_within(ROOT, check["validator_path"])
        if validator_path is None or not validator_path.is_relative_to(validator_root):
            errors.append(f"{check_id} 的 validator_path 不在允许 Validator 根目录内")
        elif not validator_path.is_file():
            errors.append(f"{check_id} 的 Validator 文件不存在")
        elif _sha256(validator_path) != check["validator_sha256"]:
            errors.append(f"{check_id} 的 Validator SHA-256 不匹配")

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
                errors.extend(_validate_input_manifest_references(path, run_root, check_id))

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
    """返回结构、数学和正式结果资格；旧记录不会因缺少新证据而无法读取。"""
    if result_report.get("profile") != ENGINEERING_PROFILE:
        return {
            "structural_validation": "passed",
            "mathematical_validation": "not_required",
            "formal_result_eligible": False,
            "errors": [],
        }
    evidence_path = run_dir / EVIDENCE_FILENAME
    if not evidence_path.is_file():
        return {
            "structural_validation": "passed",
            "mathematical_validation": "unverified",
            "formal_result_eligible": False,
            "errors": ["缺少 Gate 3 可执行数学检查证据"],
        }
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "structural_validation": "passed",
            "mathematical_validation": "failed",
            "formal_result_eligible": False,
            "errors": [f"Gate 3 证据无法解析：{exc}"],
        }
    errors = validate_gate_3_check_evidence(evidence, run_dir)
    check_ids = {item.get("check_id") for item in evidence.get("checks", []) if isinstance(item, Mapping)}
    required = set(REQUIRED_OPTIMIZATION_CHECKS)
    if result_manifest.get("deterministic_expected") is False:
        required.update(REQUIRED_RANDOM_CHECKS)
    missing = required - check_ids
    if missing:
        errors.append(f"Gate 3 缺少必需机器检查：{sorted(missing)}")
    if errors:
        return {
            "structural_validation": "passed",
            "mathematical_validation": "failed",
            "formal_result_eligible": False,
            "errors": errors,
        }
    return {
        "structural_validation": "passed",
        "mathematical_validation": "passed",
        "formal_result_eligible": True,
        "errors": [],
    }
