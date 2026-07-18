from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "runtime_contracts" / "2024c_q2_model_contract.json"
REGISTRY_PATH = ROOT / "runtime_contracts" / "2024c_q1_validator_registry.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_q2_contract_is_frozen_but_not_implemented() -> None:
    contract = _contract()
    assert contract["problem_id"] == "2024-C"
    assert contract["subproblem_id"] == "Q2"
    assert contract["status"] == "model_contract_draft_review_pending"
    assert contract["validation"]["qualification_authority"] is False

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    q2 = next(item for item in registry["validators"] if item["subproblem_id"] == "Q2")
    assert q2["status"] == contract["status"]
    assert q2["validator_id"] is None
    assert q2["contract_path"] == "runtime_contracts/2024c_q2_model_contract.json"


def test_q2_randomness_is_reproducible_and_excludes_q3_correlation() -> None:
    random = _contract()["random"]
    assert random["bit_generator"] == "PCG64"
    assert random["numpy_version"] == "2.4.4"
    assert random["scenarios_per_seed"] == 256
    assert set(random["optimization_seed_groups"]).isdisjoint(random["evaluation_seed_groups"])
    assert random["optimization_scenario_count"] == 768
    assert random["evaluation_scenario_count"] == 512
    assert random["q3_correlation_excluded"] is True
    assert random["scenario_manifest"]["sha256_required"] is True


def test_q2_parameter_ranges_match_official_question() -> None:
    params = _contract()["uncertain_parameters"]
    sales_growth = params["sales_wheat_corn_growth"]
    assert sales_growth["distribution"] == "uniform"
    assert sales_growth["low"] == 0.05
    assert sales_growth["high"] == 0.10
    assert sales_growth["recurrence"] == "compound_previous_year"
    assert sales_growth["sampling_key"] == "crop_id_season_year"
    assert params["yield_factor"]["low"] == 0.90
    assert params["yield_factor"]["high"] == 1.10
    assert params["yield_factor"]["sampling_key"] == "crop_id_year_shared_across_land_and_season"
    assert params["morel_price_decline"]["value"] == 0.05
    for item in params.values():
        if item["distribution"] == "uniform":
            assert math.isfinite(item["low"])
            assert math.isfinite(item["high"])
            assert item["low"] <= item["high"]


def test_q2_risk_statistics_and_sensitivity_are_explicit() -> None:
    risk = _contract()["risk"]
    assert risk["alpha"] == 0.90
    assert risk["cvar_tail_count_rule"] == "ceil"
    assert risk["risk_aversion_lambda"] == 0.25
    assert risk["sensitivity_lambdas"] == [0.0, 0.25, 0.5]
    assert set(["mean", "p05", "p50", "p95", "worst_profit", "cvar_loss"]).issubset(risk["reported_statistics"])


def test_q2_requires_real_q1_baseline_and_convergence_audit() -> None:
    contract = _contract()
    assert contract["q1_baseline"]["status"] == "pending_real_q1_result"
    assert contract["q1_baseline"]["must_be_frozen_before_q2_solver"] is True
    convergence = contract["convergence"]
    assert convergence["scenario_budgets"] == [64, 128, 256, 512]
    assert convergence["claim_256_scenarios_sufficient"] is False
