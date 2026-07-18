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
    assert contract["status"] == "model_contract_frozen_solver_pending"
    assert contract["validation"]["qualification_authority"] is False

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    q2 = next(item for item in registry["validators"] if item["subproblem_id"] == "Q2")
    assert q2["status"] == contract["status"]
    assert q2["validator_id"] is None
    assert q2["contract_path"] == "runtime_contracts/2024c_q2_model_contract.json"


def test_q2_randomness_is_reproducible_and_excludes_q3_correlation() -> None:
    random = _contract()["random"]
    assert random["bit_generator"] == "PCG64"
    assert random["scenario_count"] == 256
    assert random["primary_seed"] == random["replicate_seeds"][0]
    assert len(random["replicate_seeds"]) == 5
    assert random["q3_correlation_excluded"] is True


def test_q2_parameter_ranges_match_official_question() -> None:
    params = _contract()["uncertain_parameters"]
    assert params["sales_wheat_corn_growth"] == {
        "distribution": "uniform",
        "low": 0.05,
        "high": 0.10,
        "recurrence": "compound_previous_year",
    }
    assert params["yield_factor"]["low"] == 0.90
    assert params["yield_factor"]["high"] == 1.10
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
