"""独立反向验证 Q1 官方工作簿并冻结 Q1 基线 Manifest。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domains.problem_2024_c.data_loader import load_problem_data, resolve_material_root
from domains.problem_2024_c.official_output_schema import inspect_template
from validators.competition_full_replay.problem_2024_c import (
    WorkbookAssignment,
    read_official_workbook,
    validate_q1_workbook,
)


TOLERANCE = 1e-5


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return value


def _write_json_lf(path: Path, value: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _assignment_key(item: Any) -> tuple[str, int, str, int]:
    if isinstance(item, WorkbookAssignment):
        return item.plot_id, item.year, item.season, item.crop_id
    return str(item["plot_id"]), int(item["year"]), str(item["season"]), int(item["crop_id"])


def _assignment_area(item: Any) -> float:
    return float(item.area_mu if isinstance(item, WorkbookAssignment) else item["area_mu"])


def _assignment_map(items: Iterable[Any]) -> dict[tuple[str, int, str, int], float]:
    values: dict[tuple[str, int, str, int], float] = defaultdict(float)
    for item in items:
        values[_assignment_key(item)] += _assignment_area(item)
    return dict(values)


def _assignment_sha(items: Iterable[Any]) -> str:
    values = [
        {
            "plot_id": key[0],
            "year": key[1],
            "season": key[2],
            "crop_id": key[3],
            "area_mu": round(area, 6),
        }
        for key, area in sorted(_assignment_map(items).items())
    ]
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def freeze_q1_baseline(
    *,
    material_root: Path,
    formal_result_path: Path,
    validator_report_path: Path,
    material_manifest_path: Path,
    template_root: Path,
    baseline_manifest_path: Path,
) -> Path:
    """从已生成产物反向读取工作簿，验证并写入不可伪造的基线清单。"""

    data = load_problem_data(material_root)
    formal = _load_json(formal_result_path)
    validator_report = _load_json(validator_report_path)
    formal_sha = _sha256(formal_result_path)
    validator_sha = _sha256(validator_report_path)
    if validator_report.get("formal_result_sha256") != formal_sha:
        raise ValueError("Validator report 未绑定实际 Formal Result SHA-256")
    if validator_report.get("valid") is not True:
        raise ValueError("Validator report 未通过")
    if validator_report.get("production_ready") is not False:
        raise ValueError("Q1 基线不允许登记 production_ready=true")

    template_contracts = {
        scenario_id: inspect_template(template_root / "2024_C" / "templates" / template_name)
        for scenario_id, template_name in {
            "q1_waste": "result1_1.xlsx",
            "q1_discount": "result1_2.xlsx",
        }.items()
    }
    formal_by_id = {item["scenario_id"]: item for item in formal["scenarios"]}
    expected_ids = {"q1_waste", "q1_discount"}
    if set(formal_by_id) != expected_ids:
        raise ValueError("Formal Result 必须包含 q1_waste 和 q1_discount 两个场景")

    scenarios: list[dict[str, Any]] = []
    for scenario_id, template_name in (("q1_waste", "result1_1.xlsx"), ("q1_discount", "result1_2.xlsx")):
        formal_item = formal_by_id[scenario_id]
        workbook = ROOT / str(formal_item["output_workbook_path"])
        if not workbook.is_file():
            raise ValueError(f"Formal Result 工作簿不存在: {workbook}")
        if _sha256(workbook) != formal_item.get("output_workbook_sha256"):
            raise ValueError(f"{scenario_id} 工作簿 SHA 与 Formal Result 不匹配")
        template = template_root / "2024_C" / "templates" / template_name
        if inspect_template(workbook) != template_contracts[scenario_id]:
            raise ValueError(f"{scenario_id} 工作簿模板结构不匹配")

        assignments = read_official_workbook(workbook, data)
        formal_assignments = formal_item["assignments"]
        actual_map = _assignment_map(assignments)
        formal_map = _assignment_map(formal_assignments)
        if set(actual_map) != set(formal_map):
            raise ValueError(f"{scenario_id} 工作簿与 Formal Result 决策变量集合不一致")
        differences = [
            (key, actual_map[key], formal_map[key])
            for key in actual_map
            if abs(actual_map[key] - formal_map[key]) > TOLERANCE
        ]
        if differences:
            raise ValueError(f"{scenario_id} 工作簿与 Formal Result 面积不一致: {differences[0]}")

        workbook_report = validate_q1_workbook(
            workbook,
            data,
            scenario_id,
            float(formal_item["objective_reported"]),
        )
        if workbook_report.get("passed") is not True:
            raise ValueError(f"{scenario_id} 官方工作簿独立复核失败")
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "objective_yuan": float(workbook_report["objective_recomputed_yuan"]),
                "assignment_count": len(assignments),
                "candidate_assignments_sha256": _assignment_sha(formal_assignments),
                "template_path": f"official_materials/2024_C/templates/{template_name}",
                "template_sha256": _sha256(template),
                "workbook_path": _relative(workbook),
                "workbook_sha256": _sha256(workbook),
                "workbook_validation_passed": True,
            }
        )

    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "2024c_q1_baseline_manifest",
        "problem_id": "2024-C",
        "q1_baseline_frozen": True,
        "production_ready": False,
        "files": [
            {"role": "material_manifest", "path": _relative(material_manifest_path), "sha256": _sha256(material_manifest_path)},
            {"role": "formal_result", "path": _relative(formal_result_path), "sha256": formal_sha},
            {"role": "validator_report", "path": _relative(validator_report_path), "sha256": validator_sha},
        ],
        "scenarios": scenarios,
        "q1_waste_objective": next(item["objective_yuan"] for item in scenarios if item["scenario_id"] == "q1_waste"),
        "q1_discount_objective": next(item["objective_yuan"] for item in scenarios if item["scenario_id"] == "q1_discount"),
        "official_workbook_reverse_validation_passed": True,
    }
    baseline_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_lf(baseline_manifest_path, manifest)
    return baseline_manifest_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--material-root", type=Path, default=resolve_material_root())
    parser.add_argument("--formal-result", type=Path, default=ROOT / "formal_result/cases/2024_C/q1/q1_formal_result.json")
    parser.add_argument("--validator-report", type=Path, default=ROOT / "formal_result/cases/2024_C/q1/q1_validator_report.json")
    parser.add_argument("--material-manifest", type=Path, default=ROOT / "formal_result/cases/2024_C/material_manifest.json")
    parser.add_argument("--template-root", type=Path, default=resolve_material_root())
    parser.add_argument("--baseline-manifest", type=Path, default=ROOT / "formal_result/cases/2024_C/q1/q1_baseline_manifest.json")
    args = parser.parse_args()
    manifest = freeze_q1_baseline(
        material_root=args.material_root.resolve(),
        formal_result_path=args.formal_result.resolve(),
        validator_report_path=args.validator_report.resolve(),
        material_manifest_path=args.material_manifest.resolve(),
        template_root=args.template_root.resolve(),
        baseline_manifest_path=args.baseline_manifest.resolve(),
    )
    print(json.dumps({"baseline_manifest": str(manifest), "status": "frozen"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
