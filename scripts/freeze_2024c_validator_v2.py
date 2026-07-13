"""冻结 2024-C Validator v2 数据与目标合同。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from atomic_io import atomic_write_bytes


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIAGNOSIS = (
    ROOT / "experiments" / "2024c_objective_diagnosis_v1" / "diagnostic_result.json"
)
DEFAULT_REPORT = ROOT / "docs" / "reports" / "2024C_OBJECTIVE_RECOMPUTATION_DIAGNOSIS.md"
DEFAULT_OUTPUT = ROOT / "protocols" / "a092_v2" / "2024c_validator_contract_freeze.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_freeze_record(diagnosis_path: Path, report_path: Path) -> dict[str, object]:
    diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    if diagnosis.get("diagnosis_passed") is not True:
        raise ValueError("2024-C 诊断未通过，拒绝冻结 Validator v2")
    inputs = [
        ROOT / "official_materials" / "2024_C" / "attachments" / "附件1.xlsx",
        ROOT / "official_materials" / "2024_C" / "attachments" / "附件2.xlsx",
    ]
    validator_files = [
        ROOT / "validators" / "problem_positive_v2" / "__init__.py",
        ROOT / "validators" / "problem_positive_v2" / "validate.py",
    ]
    return {
        "freeze_record_version": "1.0.0",
        "validator_contract_version": "2024c_positive_v2",
        "status": "validator_frozen_for_a092_v2_design",
        "full_confirmatory_protocol_frozen": False,
        "data_contract": {
            "merged_plot_ids_forward_filled": True,
            "smart_greenhouse_first_season_source": "普通大棚第一季",
            "sales_cap_key": ["crop_id", "season"],
            "smart_greenhouse_rotation_order": "actual_season_sequence_with_2023_boundary",
            "objective_tolerance": 1e-6,
            "constraint_tolerance": 1e-5,
        },
        "official_inputs": {
            path.relative_to(ROOT).as_posix(): _sha256(path) for path in inputs
        },
        "validator_files": {
            path.relative_to(ROOT).as_posix(): _sha256(path) for path in validator_files
        },
        "diagnostic_result": {
            "path": diagnosis_path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(diagnosis_path),
        },
        "diagnostic_report": {
            "path": report_path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(report_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="冻结 2024-C Validator v2 合同")
    parser.add_argument("--diagnosis", type=Path, default=DEFAULT_DIAGNOSIS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = build_freeze_record(args.diagnosis, args.report)
    atomic_write_bytes(
        args.output,
        (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps({"output": str(args.output), "status": record["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
