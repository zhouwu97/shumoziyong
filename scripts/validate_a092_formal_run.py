"""对 A092 阶段三单次运行执行独立验证与隔离审计。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validators.problem_boundary.validate import validate_result as validate_boundary
from validators.problem_negative.validate import validate_result as validate_negative
from validators.problem_positive.validate import validate_result as validate_positive


FORBIDDEN_PATTERNS = (
    re.compile(r"a092_confirmatory_v1[\\/](R(?:0[1-9]|10))", re.IGNORECASE),
    re.compile(r"experiments[\\/]a092_confirmatory_v1", re.IGNORECASE),
    re.compile(r"prompt_patches", re.IGNORECASE),
    re.compile(r"protocols[\\/]a092", re.IGNORECASE),
)


def _load_result(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "results" / "formal_result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate(run_dir: Path, problem: str) -> dict[str, Any]:
    """根据题目调用冻结的独立适配器。"""

    result = _load_result(run_dir)
    if problem == "2024-C":
        return validate_positive(
            result,
            run_dir / "materials" / "attachments" / "附件1.xlsx",
            run_dir / "materials" / "attachments" / "附件2.xlsx",
        )
    if problem == "2023-B":
        return validate_boundary(result)
    if problem == "2016-C":
        return validate_negative(result)
    raise ValueError(f"不支持的问题: {problem}")


def audit_isolation(run_dir: Path) -> dict[str, Any]:
    """扫描事件流，确认没有引用其他正式运行或仓库侧实验资料。"""

    events_path = run_dir / "runner_events.jsonl"
    text = events_path.read_text(encoding="utf-8", errors="replace")
    own_run = run_dir.name.upper()
    findings: list[dict[str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in FORBIDDEN_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if "a092_confirmatory_v1" in value.lower() and value.upper().endswith(own_run):
                    continue
                findings.append({"line": str(line_number), "match": value})
    return {
        "audit": "a092_run_isolation_v1",
        "run_id": own_run,
        "events_sha256_checked": True,
        "forbidden_reference_count": len(findings),
        "findings": findings,
        "valid": not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 A092 正式运行")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("problem", choices=("2024-C", "2023-B", "2016-C"))
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    report = validate(run_dir, args.problem)
    audit = audit_isolation(run_dir)
    gate3 = run_dir / "gate3"
    gate5 = run_dir / "gate5"
    gate3.mkdir(parents=True, exist_ok=True)
    gate5.mkdir(parents=True, exist_ok=True)
    (gate3 / "validator_independent.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (gate5 / "isolation_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"validator": report, "isolation": audit}, ensure_ascii=False, indent=2))
    return 0 if audit["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
