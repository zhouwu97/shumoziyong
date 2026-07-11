from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evidence_validation as evidence_module  # noqa: E402
import promotion_engine  # noqa: E402
from evidence_validation import (  # noqa: E402
    ControlOutcome,
    EvidenceOutcome,
    validate_formal_patch,
)
from promotion_engine import EligibilityReport  # noqa: E402


def _write(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_formal_patch_status_must_equal_highest_derived_state(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """真实证据已支持更高状态时，较低手填状态也不得进入正式包。"""
    patch_file = tmp_path / "patch.md"
    patch_file.write_text("verified patch", encoding="utf-8")
    patch_sha = hashlib.sha256(patch_file.read_bytes()).hexdigest()
    _write(
        tmp_path / "card.json",
        {"source": {"verification_status": "verified", "claims": [{"claim_id": "C001"}]}},
    )

    negative_runs = []
    for index in range(2):
        baseline = tmp_path / f"baseline-{index}"
        treatment = tmp_path / f"treatment-{index}"
        _write(baseline / "run_evidence_manifest.json", {"run_id": f"b-{index}"})
        _write(treatment / "run_evidence_manifest.json", {"run_id": f"t-{index}"})
        review = tmp_path / f"review-{index}.json"
        _write(review, {"final_conclusion": "pass"})
        negative_runs.append(
            {
                "experiment_group_id": f"group-{index}",
                "case": f"negative-{index}",
                "baseline_run": baseline.relative_to(tmp_path).as_posix(),
                "treatment_run": treatment.relative_to(tmp_path).as_posix(),
                "comparison_review": review.relative_to(tmp_path).as_posix(),
            }
        )

    for name in ("failure.json", "fix.json", "review-fix.json"):
        _write(tmp_path / name, {"patch_id": "A999"})
    retest = tmp_path / "retest"
    _write(retest / "run_evidence_manifest.json", {"run_id": "retest"})

    competition_manifest = tmp_path / "competition.manifest.json"
    competition_sha = _write(
        competition_manifest,
        {
            "patches": [
                {
                    "patch_id": "A999",
                    "path": "patch.md",
                    "sha256": patch_sha,
                    "status": "competition_evidenced",
                }
            ]
        },
    )
    _write(
        tmp_path / "competition.result.json",
        {
            "result": "pass",
            "runtime_pack_manifest": "competition.manifest.json",
            "runtime_pack_manifest_sha256": competition_sha,
        },
    )

    patch = {
        "patch_id": "A999",
        "status": "regression_verified",
        "file": "patch.md",
        "source": {"knowledge_card": "card.json", "claim_ids": ["C001"]},
        "validation_records": ["validation.json"],
        "stable_evidence": {
            "negative_control_runs": negative_runs,
            "failure_fix_retests": [
                {
                    "failure_record": "failure.json",
                    "fix_record": "fix.json",
                    "review_record": "review-fix.json",
                    "retest_run": "retest",
                }
            ],
            "competition_validation_records": [
                {
                    "runtime_pack_manifest": "competition.manifest.json",
                    "runtime_pack_manifest_sha256": competition_sha,
                    "result_record": "competition.result.json",
                }
            ],
            "human_approval_record": {},
        },
    }
    matrix_entry = {
        name: {"case": name, "evidence": {"fixture": True}}
        for name in ("positive", "boundary", "negative")
    }

    monkeypatch.setattr(
        evidence_module,
        "validate_control_evidence",
        lambda *_args, **_kwargs: ControlOutcome(True, result="pass"),
    )
    monkeypatch.setattr(
        evidence_module,
        "validate_full_run",
        lambda *_args, **_kwargs: EvidenceOutcome(True),
    )
    monkeypatch.setattr(evidence_module, "_schema_errors", lambda *_args: [])

    def eligible(
        candidate: dict[str, Any],
        _entry: dict[str, Any],
        _policy: dict[str, Any],
        target: str,
    ) -> EligibilityReport:
        return EligibilityReport(
            patch_id=str(candidate["patch_id"]),
            current_status=str(candidate["status"]),
            target_status=target,
            eligible=True,
        )

    monkeypatch.setattr(promotion_engine, "evaluate_status_eligibility", eligible)
    outcome = validate_formal_patch(patch, matrix_entry, {}, root=tmp_path)

    assert not outcome.valid
    assert outcome.identity["derived_status"] == "competition_evidenced"
    assert any("记录状态 regression_verified" in error for error in outcome.errors)
