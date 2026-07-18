"""为已生成的 2024-C Q1 产物生成独立复算报告和 S1 证据 Manifest。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domains.problem_2024_c.data_loader import resolve_material_root
from validators.problem_2024c_q1.validate import validate_q1_result


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
    """以固定 LF 写 JSON，避免 Windows 换行转换破坏文件 SHA 绑定。"""

    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_s1_evidence(
    *,
    material_root: Path,
    formal_result_path: Path,
    run_log_path: Path,
    material_manifest_path: Path,
    report_path: Path,
    evidence_manifest_path: Path,
) -> tuple[Path, Path]:
    """只读取冻结产物，独立复算并写入两个可审计的 S1 证据文件。"""

    formal_result = _load_json(formal_result_path)
    run_log = _load_json(run_log_path)
    formal_sha = _sha256(formal_result_path)
    run_log_sha = _sha256(run_log_path)
    if run_log.get("formal_result_sha256") != formal_sha:
        raise ValueError("Solver run log 未绑定实际 Formal Result SHA-256")
    if run_log.get("q1_independent_recalculation_passed") is not True:
        raise ValueError("Solver run log 未登记 Q1 独立复算通过")
    if run_log.get("production_ready") is not False:
        raise ValueError("Q1 S1 不允许登记 production_ready=true")

    attachment_1 = material_root / "2024_C" / "attachments" / "附件1.xlsx"
    attachment_2 = material_root / "2024_C" / "attachments" / "附件2.xlsx"
    mathematical_report = validate_q1_result(
        formal_result,
        attachment_1,
        attachment_2,
        material_manifest_path,
    )
    if not mathematical_report["valid"]:
        raise ValueError("Q1 Formal Result 独立数学复算失败")

    formal_by_id = {item["scenario_id"]: item for item in formal_result["scenarios"]}
    log_by_id = {item["scenario_id"]: item for item in run_log["scenarios"]}
    expected_ids = {"q1_waste", "q1_discount"}
    if set(formal_by_id) != expected_ids or set(log_by_id) != expected_ids:
        raise ValueError("Q1 必须包含且仅包含两个独立销售情形")

    scenario_evidence: list[dict[str, Any]] = []
    for scenario_id in sorted(expected_ids):
        formal_item = formal_by_id[scenario_id]
        log_item = log_by_id[scenario_id]
        if log_item.get("workbook_sha256") != formal_item.get("output_workbook_sha256"):
            raise ValueError(f"{scenario_id} 工作簿 SHA 未与 Formal Result 绑定")
        workbook_validation = log_item.get("workbook_validation")
        if not isinstance(workbook_validation, dict) or workbook_validation.get("passed") is not True:
            raise ValueError(f"{scenario_id} 官方工作簿复核未通过")
        scenario_evidence.append(
            {
                "scenario_id": scenario_id,
                "solver_status": log_item.get("solver_status"),
                "mip_gap": log_item.get("mip_gap"),
                "optimality_proven": log_item.get("optimality_proven"),
                "solver_objective_yuan": log_item.get("solver_objective_yuan"),
                "exported_objective_yuan": log_item.get("exported_objective_yuan"),
                "workbook_sha256": formal_item.get("output_workbook_sha256"),
                "workbook_validation_passed": True,
            }
        )

    report = {
        "schema_version": "1.0.0",
        "artifact_type": "2024c_q1_validator_report",
        "problem_id": "2024-C",
        "validator": mathematical_report["validator"],
        "formal_result_path": _relative(formal_result_path),
        "formal_result_sha256": formal_sha,
        "material_manifest_path": _relative(material_manifest_path),
        "material_manifest_sha256": _sha256(material_manifest_path),
        "solver_run_log_path": _relative(run_log_path),
        "solver_run_log_sha256": run_log_sha,
        "solver": run_log.get("solver"),
        "settings": run_log.get("settings"),
        "scenarios": scenario_evidence,
        "mathematical_validation": mathematical_report,
        "valid": True,
        "production_ready": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_lf(report_path, report)

    evidence_manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "2024c_q1_s1_evidence_manifest",
        "problem_id": "2024-C",
        "q1_solver_status": "implemented",
        "q1_formal_result_status": "generated",
        "q1_mathematical_validation": "passed",
        "q1_workbook_status": "pending_s2_baseline_freeze",
        "q1_baseline_frozen": False,
        "production_ready": False,
        "files": [
            {"role": "formal_result", "path": _relative(formal_result_path), "sha256": formal_sha},
            {"role": "solver_run_log", "path": _relative(run_log_path), "sha256": run_log_sha},
            {"role": "validator_report", "path": _relative(report_path), "sha256": _sha256(report_path)},
        ],
        "scenario_evidence": scenario_evidence,
    }
    evidence_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_lf(evidence_manifest_path, evidence_manifest)
    return report_path, evidence_manifest_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--material-root", type=Path, default=resolve_material_root())
    parser.add_argument("--formal-result", type=Path, default=ROOT / "formal_result/cases/2024_C/q1/q1_formal_result.json")
    parser.add_argument("--run-log", type=Path, default=ROOT / "formal_result/cases/2024_C/q1/q1_solver_run_log.json")
    parser.add_argument("--material-manifest", type=Path, default=ROOT / "formal_result/cases/2024_C/material_manifest.json")
    parser.add_argument("--report", type=Path, default=ROOT / "formal_result/cases/2024_C/q1/q1_validator_report.json")
    parser.add_argument("--evidence-manifest", type=Path, default=ROOT / "formal_result/cases/2024_C/q1/q1_s1_evidence_manifest.json")
    args = parser.parse_args()
    report, manifest = build_s1_evidence(
        material_root=args.material_root.resolve(),
        formal_result_path=args.formal_result.resolve(),
        run_log_path=args.run_log.resolve(),
        material_manifest_path=args.material_manifest.resolve(),
        report_path=args.report.resolve(),
        evidence_manifest_path=args.evidence_manifest.resolve(),
    )
    print(json.dumps({"validator_report": str(report), "evidence_manifest": str(manifest), "status": "passed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
