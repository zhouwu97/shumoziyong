"""复核题目到论文结论的语义链，禁止通用一公式冒充正式候选。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


class PaperSemanticError(ValueError):
    """语义映射输入不可信或结构不合法。"""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PaperSemanticError(f"JSON 顶层必须是对象：{path}")
    return value


def _validate_schema(value: Mapping[str, Any], schema_name: str) -> None:
    schema = _load(ROOT / "schemas" / schema_name)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise PaperSemanticError(f"{schema_name} 校验失败：{location}: {error.message}")


def _resolve_text(root: Path, ref: Mapping[str, Any], label: str) -> str:
    relative = str(ref["path"])
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative or ":" in relative:
        raise PaperSemanticError(f"{label} 必须是安全 POSIX 相对路径")
    path = root.joinpath(*pure.parts)
    try:
        path.resolve(strict=True).relative_to(root.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise PaperSemanticError(f"{label} 不存在或越出根目录") from exc
    if path.suffix.lower() not in {".txt", ".md", ".typ"}:
        raise PaperSemanticError(f"{label} 必须是可审计文本，不接受二进制或 PDF 代理")
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        raise PaperSemanticError(f"{label} SHA-256 漂移")
    return path.read_text(encoding="utf-8")


def _normalized(value: str) -> str:
    return "".join(value.split()).casefold()


def validate_paper_semantics(
    semantic_map: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    """验证核心实体、逐问绑定、正式章节和题目专用公式。"""
    _validate_schema(semantic_map, "paper_semantic_map.schema.json")
    _validate_schema(registry, "problem_semantics_registry.schema.json")
    matches = [
        item for item in registry["problems"]
        if item["problem_id"] == semantic_map["problem_id"]
    ]
    if len(matches) != 1:
        raise PaperSemanticError("题目未在语义注册表中唯一登记")
    problem = matches[0]
    paper = _resolve_text(root, semantic_map["paper_text"], "论文文本")
    statement = _resolve_text(root, semantic_map["problem_statement"], "官方题面文本")
    failures: set[str] = set()

    required_entities = list(problem["required_entities"])
    forbidden_entities = list(problem["forbidden_entities"])
    if any(entity not in statement for entity in required_entities):
        failures.add("PSM_STATEMENT_ENTITY_MISMATCH")
    if any(entity not in paper for entity in required_entities):
        failures.add("PSM_REQUIRED_ENTITY_MISSING")
    if any(entity in paper for entity in forbidden_entities):
        failures.add("PSM_FORBIDDEN_ENTITY_PRESENT")

    for aliases in registry["required_section_aliases"].values():
        if not any(alias in paper for alias in aliases):
            failures.add("PSM_REQUIRED_SECTION_MISSING")

    bindings = list(semantic_map["bindings"])
    binding_ids = [str(item["subproblem_id"]) for item in bindings]
    expected_ids = list(problem["subproblem_ids"])
    if len(binding_ids) != len(set(binding_ids)) or set(binding_ids) != set(expected_ids):
        failures.add("PSM_SUBPROBLEM_COVERAGE")

    formula_catalog = list(semantic_map["formula_catalog"])
    formula_ids = [str(item["formula_id"]) for item in formula_catalog]
    if len(formula_ids) != len(set(formula_ids)):
        failures.add("PSM_FORMULA_ID_DUPLICATE")
    formula_by_id = {str(item["formula_id"]): item for item in formula_catalog}
    forbidden_formulas = {
        _normalized(str(expression)) for expression in registry["forbidden_generic_formulas"]
    }
    if any(
        _normalized(str(item["expression"])) in forbidden_formulas
        for item in formula_catalog
    ):
        failures.add("PSM_GENERIC_FORMULA_FORBIDDEN")

    formula_use: dict[str, int] = {}
    for binding in bindings:
        if (
            str(binding["mathematical_task"]) not in paper
            or str(binding["model_formula_text"]) not in paper
            or str(binding["solver_result_text"]) not in paper
        ):
            failures.add("PSM_BINDING_TEXT_MISSING")
        ids = [str(item) for item in binding["formula_ids"]]
        if any(formula_id not in formula_by_id for formula_id in ids):
            failures.add("PSM_FORMULA_BINDING_INVALID")
        for formula_id in ids:
            formula_use[formula_id] = formula_use.get(formula_id, 0) + 1
    for binding in bindings:
        ids = [str(item) for item in binding["formula_ids"]]
        if not any(formula_use.get(formula_id) == 1 for formula_id in ids):
            failures.add("PSM_SUBPROBLEM_FORMULA_NOT_UNIQUE")

    report = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_semantic_report_v1",
        "run_id": semantic_map["run_id"],
        "problem_id": semantic_map["problem_id"],
        "status": "failed" if failures else "passed",
        "failure_codes": sorted(failures),
        "checked_subproblems": sorted(set(binding_ids)),
        "required_entities": required_entities,
        "forbidden_entities": forbidden_entities,
    }
    _validate_schema(report, "paper_semantic_report.schema.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-map", type=Path, required=True)
    parser.add_argument(
        "--registry",
        type=Path,
        default=ROOT / "runtime_contracts" / "problem_semantics_registry_v1.json",
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        semantic_map = _load(args.semantic_map)
        registry = _load(args.registry)
        report = validate_paper_semantics(semantic_map, registry, root=args.root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, PaperSemanticError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
