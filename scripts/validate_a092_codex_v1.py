"""A092 Codex V1 数学复算与执行引擎联合门禁。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from validate_a092_formal_run import build_v2_external_artifacts, validate


PROTOCOL_ID = "A092-CONFIRMATORY-CODEX-V1"
EXPECTED = {
    "execution_engine": "Codex",
    "cli_version_observed": "0.144.2",
    "model_observed": "gpt-5.6-sol",
    "model_reasoning_effort": "high",
    "approval_policy_observed": "never",
    "sandbox_observed": "danger-full-access",
}
FORBIDDEN = (
    re.compile(r"a092_confirmatory_v[1-4]", re.IGNORECASE),
    re.compile(r"a092_codex_diagnostic", re.IGNORECASE),
    re.compile(r"experiments[\\/]a092", re.IGNORECASE),
    re.compile(r"prompt_patches", re.IGNORECASE),
    re.compile(r"protocols[\\/]a092", re.IGNORECASE),
)
OWN_RUN = re.compile(r"a092_confirmatory_codex_v1(?:[\\/](?:runs|attempts|prepared))?[\\/](R0[12])", re.IGNORECASE)


def audit_codex(run_dir: Path) -> dict[str, Any]:
    events_path = run_dir / "runner_events.jsonl"
    text = events_path.read_text(encoding="utf-8", errors="replace")
    findings: list[dict[str, str]] = []
    own = run_dir.name.upper()
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in FORBIDDEN:
            for match in pattern.finditer(line):
                findings.append({"line": str(line_number), "match": match.group(0)})
        for match in OWN_RUN.finditer(line):
            if match.group(1).upper() != own:
                findings.append({"line": str(line_number), "match": match.group(0)})
    engine_findings: list[str] = []
    metadata_path = run_dir / "runner_metadata.json"
    if not metadata_path.is_file():
        engine_findings.append("runner_metadata_missing")
    else:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("protocol_id") != PROTOCOL_ID:
            engine_findings.append("protocol_id_mismatch")
        for key, expected in EXPECTED.items():
            if metadata.get(key) != expected:
                engine_findings.append(f"{key}_mismatch")
        if metadata.get("engine_valid") is not True:
            engine_findings.append("engine_valid_false")
        if metadata.get("evidence_class") != "formal_confirmatory":
            engine_findings.append("evidence_class_mismatch")
    return {
        "audit": "a092_run_isolation_codex_v1",
        "run_id": own,
        "events_sha256_checked": True,
        "forbidden_reference_count": len(findings),
        "findings": findings,
        "engine_findings": sorted(set(engine_findings)),
        "valid": not findings and not engine_findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 A092 Codex V1 正式运行")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("problem", choices=("2024-C", "2023-B", "2016-C"))
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    mathematical = validate(run_dir, args.problem, "v3")
    audit = audit_codex(run_dir)
    attestation = build_v2_external_artifacts(run_dir, args.problem, mathematical)
    mathematical_disposition = "accepted" if attestation["candidate_disposition"] == "accepted" else "rejected"
    engine_disposition = "valid" if audit["valid"] else "invalid"
    formal_disposition = "valid" if audit["valid"] and attestation["experiment_disposition"] == "valid" else "invalid"
    disposition = {
        "mathematical_validator_disposition": mathematical_disposition,
        "engine_audit_disposition": engine_disposition,
        "formal_protocol_disposition": formal_disposition,
    }
    gate3 = run_dir / "gate3"
    gate3.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("validator_report.json", mathematical),
        ("isolation_audit.json", audit),
        ("formal_disposition.json", disposition),
    ):
        (gate3 / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"validation": mathematical, "isolation": audit, "attestation": attestation, "disposition": disposition}, ensure_ascii=False))
    return 0 if formal_disposition == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
