"""生成或校验 2023-B Gate A-C 建模冻结证据。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atomic_io import atomic_write_bytes
from modeling_contracts import ROOT, validate_case, write_bundle


DEFAULT_CASE = ROOT / "problems" / "2023_B"


def main() -> int:
    parser = argparse.ArgumentParser(description="校验建模 Gate A-C")
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--freeze", action="store_true", help="先重新生成 Modeling Bundle")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    case_dir = args.case_dir.resolve()
    if args.freeze:
        write_bundle(case_dir)
    report = validate_case(case_dir)
    output = args.output or case_dir / "modeling" / "gate_a_c_report.json"
    atomic_write_bytes(
        output,
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps({"status": report["status"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "gate_c_modeling_design_frozen" else 1


if __name__ == "__main__":
    raise SystemExit(main())
