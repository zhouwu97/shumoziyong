from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v21_contracts import (  # noqa: E402
    classify_benchmark,
    compute_score_v2,
    evaluate_paper_admission,
    validate_matlab_recomputation,
    validate_model_validity_contract,
    validate_validator_independence,
    validate_reviewer_pair,
    validate_competition_value_assessment,
)
from v21_assertions import evaluate_registered, validate_assertion_refs
from run_workflow import V21_EVIDENCE_ARTIFACT_SPECS


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _contract() -> dict:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "model_validity_contract",
        "run_id": "run-1",
        "problem_id": "2024-C",
        "contract_status": "planned",
        "data_generation": {"mechanism": "official table observations", "sources": ["official"], "scope": "single benchmark replay"},
        "variables": [{"name": "x", "definition": "decision", "unit": "kg", "source": "official"}],
        "parameters": [{"name": "a", "definition": "coefficient", "unit": "1", "source": "estimated"}],
        "formulas": [{"formula_id": "f1", "expression": "a*x", "symbols": ["a", "x"], "expected_units": "kg"}],
        "parameter_estimation_plan": {"method": "least squares", "identifiability": "rank matrix check", "stability_test": "bootstrap stability check"},
        "small_examples": [{"case_id": "s1", "description": "small hand-checkable case", "expected_behavior": "returns a feasible optimum", "execution_ref": "matlab:level_b"}],
        "limit_cases": [{"case_id": "l1", "description": "zero demand boundary", "expected_behavior": "zero output", "execution_ref": "python:boundary"}],
        "expected_monotonicity": [{"quantity": "objective", "direction": "increasing", "condition": "holding x fixed"}],
        "falsification_conditions": ["negative residual", "unit mismatch"],
        "alternative_models": [{"name": "baseline", "comparison_plan": "compare objective and residual"}],
        "claim_scope": {"allowed": ["benchmark conclusion"], "forbidden": ["global optimality beyond scope"]},
        "assertion_refs": [{"assertion_set_id": "public-v1", "layer": "public", "path": "assertions/public.json", "sha256": _sha("public"), "sealed": False, "blind_evidence": False}],
    }


def test_new_schemas_are_valid_and_history_schema_is_unchanged() -> None:
    Draft202012Validator.check_schema(_schema("model_route_v2.schema.json"))
    for name in (
        "model_route_v2_1.schema.json",
        "model_validity_contract.schema.json",
        "model_validity_report.schema.json",
        "validator_independence_manifest.schema.json",
        "paper_admission_report.schema.json",
        "reviewer_report.schema.json",
        "formal_result_run_binding.schema.json",
        "competition_value_assessment.schema.json",
        "paper_claim_map_v2.schema.json",
    ):
        Draft202012Validator.check_schema(_schema(name))


def test_v21_evidence_specs_bind_diagnosis_and_execution_once() -> None:
    paths = [path for path, _role, _media_type in V21_EVIDENCE_ARTIFACT_SPECS]
    roles = [role for _path, role, _media_type in V21_EVIDENCE_ARTIFACT_SPECS]
    bindings = {
        path: role for path, role, _media_type in V21_EVIDENCE_ARTIFACT_SPECS
    }
    assert len(paths) == len(set(paths))
    assert len(roles) == len(set(roles))
    assert bindings["diagnosis.json"] == "gate_0_diagnosis"
    assert bindings["execution_spec.json"] == "formal_execution_spec"


def test_gate1_contract_cannot_claim_execution_validation() -> None:
    assert validate_model_validity_contract(_contract()) == []
    invalid = dict(_contract())
    invalid["contract_status"] = "passed"
    assert validate_model_validity_contract(invalid)


def test_sealed_assertion_requires_blind_evidence() -> None:
    invalid = _contract()
    invalid["assertion_refs"] = [{"assertion_set_id": "sealed", "layer": "sealed", "path": "private.json", "sha256": _sha("x"), "sealed": True, "blind_evidence": False}]
    assert "sealed 断言必须同时" in "；".join(validate_model_validity_contract(invalid))


def test_validator_independence_triggers_f5_when_primary_metrics_are_read() -> None:
    manifest = {
        "schema_version": "1.0.0", "artifact_type": "validator_independence_manifest", "run_id": "run-1", "validator_id": "v1",
        "raw_input_origin": "official", "reads_primary_intermediates": False, "reads_primary_metrics": True,
        "reads_primary_decision_vector": True, "reconstructs_coefficients_independently": True,
        "shared_source_modules": [], "independent_formula_implementation": True,
        "validation_scope": ["objective_recalculation"], "f5_status": "fail",
    }
    assert validate_validator_independence(manifest) == []


def test_paper_admission_blocks_finding_and_allows_technical_report() -> None:
    result = evaluate_paper_admission(
        implementation_status="pass", model_validity_status="pass", competition_score=85,
        competition_status="pass", findings=[{"code": "F3", "severity": "fatal", "resolved": False}],
    )
    assert result["admission_status"] == "blocked"
    assert result["technical_report_allowed"] is True
    assert result["submission_paper_allowed"] is False


def test_score_v2_keeps_presentation_separate() -> None:
    score = compute_score_v2(80, 60, 90, 100)
    assert score["technical_merit"] == 60
    assert score["competition_submission_score"] == pytest.approx(68)
    assert score["competition_submission_status"] == "eligible"


def test_2024c_is_development_only() -> None:
    result = classify_benchmark("2024-C")
    assert result == {
        "classification": "development_integration_benchmark",
        "blind_generalization": False,
        "profile_promotion_eligible": False,
    }


def test_matlab_levels_are_explicit() -> None:
    assert validate_matlab_recomputation({"level": "A", "backend": "matlab", "independent_from_python": True}) == []
    assert validate_matlab_recomputation({"level": "A", "backend": "matlab", "independent_from_python": True, "full_model_solved": True})
    assert validate_matlab_recomputation({"level": "B", "backend": "matlab", "independent_from_python": True, "small_example_ids": ["s1"]}) == []


def test_sealed_assertions_are_not_runtime_pack_evidence() -> None:
    refs = [{"assertion_set_id": "s", "layer": "sealed", "path": "private.json", "sha256": "a" * 64, "sealed": True, "blind_evidence": True}]
    assert validate_assertion_refs(refs, runtime_pack_text="public only") == []
    assert validate_assertion_refs(refs, runtime_pack_text="private.json")


def test_registered_assertion_rejects_unknown_dynamic_expression() -> None:
    assert evaluate_registered("public.unit_declared", {"variables": [{"unit": "kg"}]}) is True
    with pytest.raises(ValueError):
        evaluate_registered("unknown.eval", {})


def test_competition_value_requires_score_threshold_for_pass() -> None:
    value = {
        "schema_version": "1.0.0", "artifact_type": "competition_value_assessment", "run_id": "r",
        "reviewer_id": "b", "score": 69, "status": "pass",
        "baseline_improvement_supported": True, "operational_value_supported": True, "findings": [],
    }
    assert validate_competition_value_assessment(value)


def test_reviewer_pair_requires_role_separated_label_for_same_model() -> None:
    base = {
        "schema_version": "1.0.0", "artifact_type": "reviewer_report", "run_id": "r",
        "reviewed_bundle_sha256": "a" * 64, "forbidden_inputs_confirmed": True, "write_access": False,
        "independence_mode": "independent", "reviewer_model": "same", "prompt_profile": "same",
        "findings": [], "decision": "pass",
    }
    a = {**base, "reviewer_id": "a", "review_role": "model", "review_round": 1,
         "input_artifacts": [{"path": "problem_manifest.json", "sha256": "a" * 64, "category": "problem"}]}
    b = {**base, "reviewer_id": "b", "review_role": "paper", "review_round": 1,
         "input_artifacts": [{"path": "paper_claim_map.json", "sha256": "b" * 64, "category": "claim_map"}]}
    assert any("role_separated_review" in item for item in validate_reviewer_pair(a, b))
