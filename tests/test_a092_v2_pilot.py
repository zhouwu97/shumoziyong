from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from jsonschema import Draft202012Validator

from validators.common.external_validation import audit_data_contract


ROOT = Path(__file__).resolve().parents[1]


def _load_pilot() -> ModuleType:
    path = ROOT / "scripts" / "run_a092_v2_pilot.py"
    spec = spec_from_file_location("run_a092_v2_pilot", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PILOT = _load_pilot()


def test_data_contract_requires_all_preprocessing_checks_and_fixtures() -> None:
    audit = PILOT._valid_data_audit()
    assert audit_data_contract(audit)["passed"] is True

    del audit["preprocessing"]["aggregation_keys"]
    result = audit_data_contract(audit)
    assert result["passed"] is False
    assert result["missing_checks"] == ["aggregation_keys"]


def test_v2_pilot_distinguishes_experiment_and_candidate_failures() -> None:
    _, cases = PILOT.run_cases()
    by_id = {case["case_id"]: case for case in cases}

    assert by_id["external_adapter_fixture_fail"]["attestation"]["experiment_disposition"] == "invalid"
    assert by_id["candidate_self_check_pass_external_objective_fail"]["attestation"]["experiment_disposition"] == "valid"
    assert by_id["candidate_self_check_pass_external_objective_fail"]["attestation"]["candidate_disposition"] == "rejected"
    assert by_id["objective_pass_constraints_fail"]["attestation"]["objective_passed"] is True
    assert not any(by_id["objective_pass_constraints_fail"]["attestation"]["claim_permissions"].values())
    assert by_id["same_implementation_claimed_independent"]["attestation"]["implementation_independent"] is False
    assert by_id["all_external_gates_pass"]["attestation"]["optimality_evidence_passed"] is True
    no_certificate = by_id["objective_constraints_pass_without_optimality_evidence"]["attestation"]
    assert no_certificate["candidate_disposition"] == "accepted"
    assert no_certificate["claim_permissions"] == {
        "objective_value": True,
        "improvement_rate": True,
        "strong_optimality": False,
    }


def test_v2_pilot_outputs_match_machine_contracts() -> None:
    audit, cases = PILOT.run_cases()
    audit_schema = json.loads((ROOT / "schemas" / "a092_data_contract_audit.schema.json").read_text(encoding="utf-8"))
    attestation_schema = json.loads((ROOT / "schemas" / "a092_external_validator_attestation.schema.json").read_text(encoding="utf-8"))

    Draft202012Validator(audit_schema).validate(audit)
    for case in cases:
        Draft202012Validator(attestation_schema).validate(case["attestation"])
        assert case["detected"] is True
        assert case["claims_blocked_when_required"] is True
