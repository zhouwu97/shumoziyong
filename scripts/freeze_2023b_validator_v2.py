"""冻结 2023-B Validator v2 公式合同与 Pilot 证据哈希。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from atomic_io import atomic_write_bytes


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PILOT = ROOT / "experiments" / "2023b_validator_pilot_v2" / "pilot_result.json"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "2023B_VALIDATOR_FORMULA_PILOT.md"
DEFAULT_OUTPUT = ROOT / "protocols" / "a092_v2" / "2023b_validator_formula_freeze.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_freeze_record(pilot_path: Path, report_path: Path) -> dict[str, object]:
    source = ROOT / "official_materials" / "2023_B" / "problem" / "B题.pdf"
    validator_files = [
        ROOT / "validators" / "problem_boundary_v2" / "__init__.py",
        ROOT / "validators" / "problem_boundary_v2" / "validate.py",
    ]
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    if pilot.get("pilot_passed") is not True:
        raise ValueError("Pilot 未通过，拒绝冻结公式合同")
    return {
        "freeze_record_version": "1.0.0",
        "formula_contract_version": "2023b_q1_q2_v2",
        "status": "formula_frozen_for_a092_v2_design",
        "full_confirmatory_protocol_frozen": False,
        "source_pdf": {
            "path": source.relative_to(ROOT).as_posix(),
            "sha256": _sha256(source),
            "pages_checked": [2, 3],
        },
        "coordinate_contract": pilot["coordinate_contract"],
        "equations": pilot["equations"],
        "validator_files": {
            path.relative_to(ROOT).as_posix(): _sha256(path) for path in validator_files
        },
        "pilot_result": {
            "path": pilot_path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(pilot_path),
        },
        "pilot_report": {
            "path": report_path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(report_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="冻结 2023-B Validator v2 公式合同")
    parser.add_argument("--pilot", type=Path, default=DEFAULT_PILOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = build_freeze_record(args.pilot, args.report)
    atomic_write_bytes(
        args.output,
        (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps({"output": str(args.output), "status": record["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
