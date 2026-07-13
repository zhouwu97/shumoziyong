"""A092 v4 数学复算与 Claude 执行条件联合门禁。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from validate_a092_formal_run import audit_isolation, build_v2_external_artifacts, validate


V4_RUN_PATTERN = re.compile(
    r"a092_confirmatory_v4(?:[\\/](?:runs|attempts|prepared))?[\\/](R(?:0[1-9]|10))",
    re.IGNORECASE,
)
V4_EXPERIMENT_PATTERN = re.compile(r"experiments[\\/]a092_confirmatory_v4", re.IGNORECASE)


def audit_v4(run_dir: Path) -> dict[str, object]:
    report = audit_isolation(run_dir, "v3")
    events = (run_dir / "runner_events.jsonl").read_text(encoding="utf-8", errors="replace")
    own_run = run_dir.name.upper()
    v4_findings: list[dict[str, str]] = []
    for line_number, line in enumerate(events.splitlines(), start=1):
        for match in V4_RUN_PATTERN.finditer(line):
            if match.group(1).upper() != own_run:
                v4_findings.append({"line": str(line_number), "match": match.group(0)})
        for match in V4_EXPERIMENT_PATTERN.finditer(line):
            v4_findings.append({"line": str(line_number), "match": match.group(0)})
    report["findings"] = [*report["findings"], *v4_findings]
    report["forbidden_reference_count"] = len(report["findings"])
    metadata_path = run_dir / "runner_metadata.json"
    findings = list(report.get("engine_findings", []))
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("protocol_id") != "A092-CONFIRMATORY-V4":
            findings.append("protocol_id_mismatch")
        if metadata.get("permission_mode_observed") != "bypassPermissions":
            findings.append("claude_permission_mode_mismatch")
    else:
        findings.append("runner_metadata_missing")
    report["audit"] = "a092_run_isolation_v4"
    report["engine_findings"] = sorted(set(findings))
    report["valid"] = not report["findings"] and not report["engine_findings"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 A092 v4 正式运行")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("problem", choices=("2024-C", "2023-B", "2016-C"))
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    validation = validate(run_dir, args.problem, "v3")
    audit = audit_v4(run_dir)
    attestation = build_v2_external_artifacts(run_dir, args.problem, validation)
    gate3 = run_dir / "gate3"
    gate3.mkdir(parents=True, exist_ok=True)
    (gate3 / "validator_report.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (gate3 / "isolation_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"validation": validation, "isolation": audit, "attestation": attestation}, ensure_ascii=False))
    return 0 if validation.get("status") == "passed" and audit["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
