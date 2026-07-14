"""汇总 A092 Codex V1 的首个正控正式配对。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = ROOT / "experiments" / "a092_confirmatory_codex_v1"
RUN_ROOT = EXPERIMENT_ROOT / "runs"
OUTPUT = EXPERIMENT_ROOT / "pair_reports" / "positive_pair_1_R01_R02.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_entry(run_id: str) -> dict[str, Any]:
    root = RUN_ROOT / run_id
    metadata_path = root / "runner_metadata.json"
    validator_path = root / "gate3" / "validator_report.json"
    audit_path = root / "gate3" / "isolation_audit.json"
    disposition_path = root / "gate3" / "formal_disposition.json"
    attestation_path = root / "artifacts" / "a092" / "external_validator_attestation.json"
    metadata = _load(metadata_path)
    disposition = _load(disposition_path)
    attestation = _load(attestation_path)
    return {
        "run_id": run_id,
        "arm": metadata["arm"],
        **disposition,
        "candidate_disposition": attestation["candidate_disposition"],
        "objective_passed": attestation["objective_passed"],
        "constraints_passed": attestation["constraints_passed"],
        "claim_permissions": attestation["claim_permissions"],
        "evidence_sha256": {
            "runner_metadata": _sha256(metadata_path),
            "validator_report": _sha256(validator_path),
            "isolation_audit": _sha256(audit_path),
            "formal_disposition": _sha256(disposition_path),
            "external_validator_attestation": _sha256(attestation_path),
        },
    }


def build() -> dict[str, Any]:
    baseline = _run_entry("R01")
    treatment = _run_entry("R02")
    valid_pair = all(item["formal_protocol_disposition"] == "valid" for item in (baseline, treatment))
    return {
        "schema_version": "1.0.0",
        "protocol_id": "A092-CONFIRMATORY-CODEX-V1",
        "pair_id": "positive_1",
        "problem_id": "2024-C",
        "baseline": baseline,
        "treatment": treatment,
        "only_prompt_difference": "A092 patch present only in Treatment",
        "formal_pair_disposition": "valid_pair_completed" if valid_pair else "invalid_pair",
        "valid_positive_pair_count": 1 if valid_pair else 0,
        "positive_minimum_valid_pairs": 2,
        "promotion_threshold_met": False,
        "a092_promotion": False,
        "decision_reason": "首个正式正控配对不足以满足两对阈值；且任一候选数学门禁失败时不得推广。",
    }


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["formal_pair_disposition"] == "valid_pair_completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
