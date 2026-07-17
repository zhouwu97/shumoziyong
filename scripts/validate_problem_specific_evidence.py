"""调用登记的题目专用 Validator，拒绝候选程序自报通过。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "runtime_contracts" / "problem_validator_registry_v1.json"


class ProblemValidatorError(ValueError):
    """题目专用 Validator 证据不满足闭环。"""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProblemValidatorError(f"JSON 顶层必须是对象：{path}")
    return value


def _schema(value: Mapping[str, Any], name: str) -> None:
    schema = _load(ROOT / "schemas" / name)
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise ProblemValidatorError(f"{name} 校验失败：{errors[0].message}")


def _ref_path(root: Path, ref: Mapping[str, Any], label: str) -> Path:
    relative = str(ref["path"])
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative or ":" in relative:
        raise ProblemValidatorError(f"{label} 路径不安全")
    path = root.joinpath(*pure.parts)
    try:
        path.resolve(strict=True).relative_to(root.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise ProblemValidatorError(f"{label} 不存在或越出根目录") from exc
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        raise ProblemValidatorError(f"{label} SHA-256 漂移")
    return path


def _registry_entry(registry: Mapping[str, Any], problem_id: str) -> dict[str, Any]:
    entries = [item for item in registry["validators"] if item["problem_id"] == problem_id]
    if len(entries) != 1:
        raise ProblemValidatorError(f"{problem_id} 未唯一登记题目专用 Validator")
    return entries[0]


def run_problem_validator(
    report: Mapping[str, Any], *, case_root: Path, registry: Mapping[str, Any]
) -> dict[str, Any]:
    _schema(registry, "problem_validator_registry.schema.json")
    _schema(report, "problem_validator_report.schema.json")
    entry = _registry_entry(registry, str(report["problem_id"]))
    if entry["status"] != "active":
        raise ProblemValidatorError(
            f"{report['problem_id']} Validator 状态为 {entry['status']}，必须完成独立复算后才可 active"
        )
    if report["validator_id"] != entry["validator_id"]:
        raise ProblemValidatorError("报告 Validator 身份与注册表不一致")
    if set(report["subproblem_ids"]) != set(entry["subproblem_ids"]):
        raise ProblemValidatorError("报告未覆盖全部原始子问题")
    if len(report["objective_recomputation"]["checks"]) < len(entry["subproblem_ids"]):
        raise ProblemValidatorError("目标函数未逐问复算")
    if len(report["hard_constraint_recomputation"]["checks"]) < len(entry["subproblem_ids"]):
        raise ProblemValidatorError("硬约束未逐问复算")
    _ref_path(case_root, report["official_materials"], "官方材料清单")
    _ref_path(case_root, report["decision_variables"], "决策变量")
    for index, output_ref in enumerate(report["required_outputs"], 1):
        _ref_path(case_root, output_ref, f"题目要求输出 {index}")
    module_path = _ref_path(ROOT, {"path": entry["module_path"], "sha256": entry["module_sha256"]}, "Validator 模块")
    spec = importlib.util.spec_from_file_location(f"trusted_{entry['validator_id']}", module_path)
    if spec is None or spec.loader is None:
        raise ProblemValidatorError("无法加载题目专用 Validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validate_case = getattr(module, "validate_case", None)
    if not callable(validate_case):
        raise ProblemValidatorError("题目专用 Validator 缺少 validate_case")
    independent_report = validate_case(case_root, report)
    if not isinstance(independent_report, dict):
        raise ProblemValidatorError("Validator 必须返回结构化报告")
    _schema(independent_report, "problem_validator_report.schema.json")
    if independent_report != dict(report):
        raise ProblemValidatorError("报告不是由独立 Validator 当前复算产生")
    return independent_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--case-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = _load(args.report)
        registry = _load(REGISTRY_PATH)
        result = run_problem_validator(report, case_root=args.case_root, registry=registry)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ProblemValidatorError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
