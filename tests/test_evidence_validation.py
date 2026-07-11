from __future__ import annotations

import hashlib
import json
import shutil
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
    validate_control_evidence,
    validate_formal_patch,
    validate_full_run,
    validate_profile_record,
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

    _write(tmp_path / "failure.json", {"patch_id": "A999", "failure_label": "logic"})
    _write(tmp_path / "fix.json", {"patch_id": "A999", "fix_description": "fixed"})
    _write(
        tmp_path / "review-fix.json",
        {"patch_id": "A999", "decision": "approved", "reviewer": "human"},
    )
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

    _write(tmp_path / "failure.json", {"patch_id": "A999"})
    patch["status"] = "competition_evidenced"
    semantic_outcome = validate_formal_patch(patch, matrix_entry, {}, root=tmp_path)
    assert not semantic_outcome.valid
    assert any("failure_record" in error for error in semantic_outcome.errors)


def test_full_run_recomputes_automatic_evaluation(
    tmp_path: Path, monkeypatch: Any
) -> None:
    fixture = ROOT / "tests" / "fixtures" / "valid_promotion_evidence" / "baseline"
    run_dir = tmp_path / "run"
    shutil.copytree(fixture, run_dir)
    response_path = run_dir / "response.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["patch_decisions"] = {
        "A999": {"enabled": True, "reason": "forged active patch"}
    }
    response_text = json.dumps(response)
    response_path.write_text(response_text, encoding="utf-8")
    automatic_path = run_dir / "automatic_evaluation.json"
    automatic = json.loads(automatic_path.read_text(encoding="utf-8"))
    automatic.update(
        {
            "result": "pass",
            "errors": [],
            "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
        }
    )
    automatic_path.write_text(json.dumps(automatic), encoding="utf-8")

    import finalize_run_evidence
    import run_workflow

    monkeypatch.setattr(evidence_module, "_schema_errors", lambda *_args: [])
    monkeypatch.setattr(run_workflow, "verify_run_seal", lambda *_args: {})
    monkeypatch.setattr(run_workflow, "verify_gate_artifacts", lambda *_args: {})
    monkeypatch.setattr(
        run_workflow,
        "replay_transition_log",
        lambda *_args: {"completed": True, "max_gate": 5, "transition_version": "2.0.0"},
    )
    monkeypatch.setattr(
        finalize_run_evidence, "validate_evidence_manifest", lambda *_args: []
    )

    outcome = validate_full_run(run_dir, {})

    assert not outcome.valid
    assert any("现场重算" in error for error in outcome.errors), outcome.errors


def test_control_requires_same_prompt_and_distinct_responses(
    tmp_path: Path, monkeypatch: Any
) -> None:
    baseline = tmp_path / "baseline"
    treatment = tmp_path / "treatment"
    baseline.mkdir()
    treatment.mkdir()
    baseline_evidence_sha = _write(
        baseline / "run_evidence_manifest.json", {"run_id": "baseline"}
    )
    treatment_evidence_sha = _write(
        treatment / "run_evidence_manifest.json", {"run_id": "treatment"}
    )
    _write(baseline / "ai_run_metadata.json", {"model": "same"})
    _write(treatment / "ai_run_metadata.json", {"model": "same"})
    _write(baseline / "problem_manifest.json", {"content_digest": "same"})
    _write(treatment / "problem_manifest.json", {"content_digest": "same"})
    _write(baseline / "runtime_pack.manifest.json", {"patches": []})
    _write(
        treatment / "runtime_pack.manifest.json",
        {"patches": [{"patch_id": "A999"}]},
    )
    review_path = tmp_path / "review.json"
    review = {
        "control_type": "positive",
        "target_patch": "A999",
        "baseline_run": "baseline",
        "treatment_run": "treatment",
        "baseline_evidence_manifest_sha256": baseline_evidence_sha,
        "treatment_evidence_manifest_sha256": treatment_evidence_sha,
        "experiment_group_id": "group",
        "final_conclusion": "pass",
        "consistency_checks": {"same_prompt": True},
        "risk_items": [{"observed": False}],
    }
    _write(review_path, review)

    def full_run(
        _run_dir: Path, _policy: dict[str, Any], **kwargs: Any
    ) -> EvidenceOutcome:
        role = kwargs["expected_role"]
        return EvidenceOutcome(
            True,
            identity={
                "run_id": role,
                "problem_id": "problem",
                "profile": "profile",
                "runtime_version": "1.0.0",
                "experiment_group_id": "group",
                "prompt_sha256": "baseline-prompt" if role == "baseline" else "other-prompt",
                "response_sha256": "same-response",
            },
        )

    monkeypatch.setattr(evidence_module, "validate_full_run", full_run)
    monkeypatch.setattr(evidence_module, "_schema_errors", lambda *_args: [])
    outcome = validate_control_evidence(
        "A999",
        "positive",
        {
            "case": "problem",
            "evidence": {
                "baseline_run": "baseline",
                "treatment_run": "treatment",
                "comparison_review": "review.json",
                "baseline_evidence_manifest_sha256": baseline_evidence_sha,
                "treatment_evidence_manifest_sha256": treatment_evidence_sha,
            },
        },
        {},
        root=tmp_path,
    )

    assert not outcome.valid
    assert any("prompt" in error.lower() for error in outcome.errors)
    assert any("response" in error.lower() for error in outcome.errors)


def test_profile_competition_rejects_experiment_and_patch_set_mismatch(
    tmp_path: Path, monkeypatch: Any
) -> None:
    patch_file = tmp_path / "patch.md"
    patch_file.write_text("patch", encoding="utf-8")
    runtime_path = tmp_path / "runtime.json"
    runtime_sha = _write(
        runtime_path,
        {
            "profile": "engineering_optimization",
            "runtime_version": "1.0.0",
            "runtime_pack_sha256": "a" * 64,
            "candidate_experiment": {"enabled": True, "patch_ids": ["A999"]},
            "exclusion_experiment": {"enabled": False, "patch_ids": []},
            "export_flags": {"candidate_patches": ["A999"], "excluded_patches": []},
            "patches": [],
        },
    )
    result_path = tmp_path / "result.json"
    result_sha = _write(result_path, {"run_id": "run", "result": "pass"})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    evidence_path = tmp_path / "competition.json"
    _write(
        evidence_path,
        {
            "profile": "engineering_optimization",
            "runtime_version": "1.0.0",
            "run_id": "run",
            "run_dir": "run",
            "runtime_pack_manifest": "runtime.json",
            "runtime_pack_manifest_sha256": runtime_sha,
            "result_record": "result.json",
            "result_record_sha256": result_sha,
        },
    )
    monkeypatch.setattr(evidence_module, "_schema_errors", lambda *_args: [])
    monkeypatch.setattr(
        evidence_module,
        "validate_full_run",
        lambda *_args, **_kwargs: EvidenceOutcome(
            True,
            identity={
                "run_id": "run",
                "runtime_pack_sha256": "a" * 64,
            },
        ),
    )
    record = {
        "record_id": "competition",
        "kind": "competition",
        "path": "competition.json",
        "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    patches = [
        {
            "patch_id": "A999",
            "status": "regression_verified",
            "file": "patch.md",
            "runtime_profiles": ["engineering_optimization"],
        }
    ]
    policy = {
        "runtime_profile_stable_requirements": {
            "forbid_candidate_experiment": True,
            "forbid_exclusion_experiment": True,
            "require_exact_patch_set": True,
            "require_non_empty_verified_patches": True,
        }
    }

    outcome = validate_profile_record(
        record,
        "engineering_optimization",
        patches,
        policy,
        root=tmp_path,
    )

    assert not outcome.valid
    assert any("candidate" in error for error in outcome.errors)
    assert any("Patch 集合" in error for error in outcome.errors)
