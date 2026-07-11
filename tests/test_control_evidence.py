from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from control_evidence import derive_control_result  # noqa: E402
from validate_repository import RepositoryValidator  # noqa: E402


def _review(conclusion: str = "pass") -> dict[str, object]:
    return {
        "review_version": "2.0.0",
        "reviewer": "test",
        "reviewed_at": "2026-07-11T00:00:00Z",
        "experiment_group_id": "group-1",
        "control_type": "positive",
        "target_patch": "A092",
        "baseline_run": "runs/baseline",
        "treatment_run": "runs/treatment",
        "baseline_evidence_manifest_sha256": "a" * 64,
        "treatment_evidence_manifest_sha256": "b" * 64,
        "expected_behavior": {
            "baseline": "The baseline follows the frozen generic workflow.",
            "treatment": "The treatment applies only the target patch behavior.",
            "acceptable_difference": "Only an in-scope improvement attributable to the patch is acceptable.",
        },
        "difference_metrics": [
            {
                "name": "quality_delta",
                "baseline": 0.7,
                "treatment": 0.8,
                "interpretation": "The treatment improves the declared review metric.",
            }
        ],
        "risk_items": [
            {
                "risk_id": "R1",
                "observed": False,
                "severity": "high",
                "evidence": "No out-of-scope mechanism appears in the treatment evidence.",
            }
        ],
        "consistency_checks": {
            "same_problem_id": True,
            "same_material_digest": True,
            "same_model_parameters": True,
            "same_runtime_environment": True,
            "same_experiment_group": True,
            "same_runtime_version": True,
            "only_target_patch_differs": True,
            "responses_independently_generated": True,
        },
        "final_conclusion": conclusion,
        "reason": "All configured evidence and consistency checks support this conclusion.",
    }


def _control() -> dict[str, object]:
    return {
        "case": "2024-C",
        "case_metadata": {
            "problem_id": "2024-C",
            "year": 2024,
            "mechanism_class": "resource_allocation",
            "relation_to_patch": "positive_in_scope",
            "material_level": "T3",
        },
        "expected_behavior": "The treatment improves an in-scope mechanism without changing the task.",
        "evidence": {
            "baseline_run": "runs/baseline",
            "treatment_run": "runs/treatment",
            "comparison_review": "runs/comparison_review.json",
            "baseline_evidence_manifest_sha256": "a" * 64,
            "treatment_evidence_manifest_sha256": "b" * 64,
        },
    }


def test_v2_control_and_review_schemas_accept_complete_records() -> None:
    validator = RepositoryValidator()
    matrix = {
        "matrix_version": "2.0.0",
        "patches": [
            {
                "patch_id": "A092",
                "positive": _control(),
                "boundary": {"case": None, "case_metadata": None, "expected_behavior": None, "evidence": None},
                "negative": {"case": None, "case_metadata": None, "expected_behavior": None, "evidence": None},
            }
        ],
    }

    assert validator.validate_schema(matrix, "control_matrix.schema.json", "v2 matrix")
    assert validator.validate_schema(_review(), "comparison_review_v2.schema.json", "v2 review")


def test_matrix_schema_rejects_manual_result() -> None:
    validator = RepositoryValidator()
    control = _control()
    control["result"] = "pass"
    matrix = {
        "matrix_version": "2.0.0",
        "patches": [
            {"patch_id": "A092", "positive": control, "boundary": control, "negative": control}
        ],
    }

    assert not validator.validate_schema(matrix, "control_matrix.schema.json", "manual result")


def test_result_is_derived_from_review_and_evidence() -> None:
    assert derive_control_result(_control(), _review(), evidence_valid=True) == "pass"
    assert derive_control_result(_control(), _review("needs_retest"), evidence_valid=True) == "needs_retest"
    assert derive_control_result(_control(), _review(), evidence_valid=False) == "invalid"


def test_observed_risk_forces_fail_even_if_review_says_pass() -> None:
    review = _review()
    review["risk_items"][0]["observed"] = True
    assert derive_control_result(_control(), review, evidence_valid=True) == "fail"


def test_failed_consistency_forces_invalid() -> None:
    review = _review()
    review["consistency_checks"]["same_model_parameters"] = False
    assert derive_control_result(_control(), review, evidence_valid=True) == "invalid"


def test_manual_result_is_rejected_even_when_value_is_pass() -> None:
    control = _control()
    control["result"] = "pass"
    with pytest.raises(ValueError, match="不得保存手填 result"):
        derive_control_result(control, _review(), evidence_valid=True)
