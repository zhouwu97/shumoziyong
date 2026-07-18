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
    assert random["numpy_version"] == "2.4.4"
    optimization_seeds = random["optimization_seed_groups"]
    evaluation_seeds = random["evaluation_seed_groups"]
    assert set(optimization_seeds).isdisjoint(evaluation_seeds)
    assert random["scenario_pool_per_seed"] == 512
    assert random["default_optimization_prefix_per_seed"] == 256
    assert random["default_evaluation_prefix_per_seed"] == 256
    assert "scenarios_per_seed" not in random
    assert random["optimization_scenario_count"] == len(optimization_seeds) * random["default_optimization_prefix_per_seed"]
    assert random["evaluation_scenario_count"] == len(evaluation_seeds) * random["default_evaluation_prefix_per_seed"]
    assert random["q3_correlation_excluded"] is True
    assert random["scenario_manifest"]["sha256_required"] is True


def test_q2_scenario_identity_and_prefix_invariants() -> None:
    random = _contract()["random"]
    identity = random["scenario_identity"]
    prefixes = random["convergence_prefixes_per_seed"]
    assert identity["primary_key"] == ["phase", "seed", "scenario_index"]
    assert identity["id_template"] == "{phase}_seed_{seed}_scenario_{scenario_index:04d}"
    assert identity["scenario_index_range"] == [0, 511]
    assert len(prefixes) == 4
    assert prefixes == sorted(prefixes)
    assert max(prefixes) <= random["scenario_pool_per_seed"]
    assert all(set(range(prefixes[i])).issubset(range(prefixes[i + 1])) for i in range(len(prefixes) - 1))

    ids = {
        f"{phase}_seed_{seed}_scenario_{index:04d}"
        for phase, seeds, prefix in (
            ("opt", random["optimization_seed_groups"], random["default_optimization_prefix_per_seed"]),
            ("eval", random["evaluation_seed_groups"], random["default_evaluation_prefix_per_seed"]),
        )
        for seed in seeds
        for index in range(prefix)
    }
    expected_count = len(random["optimization_seed_groups"]) * 256 + len(random["evaluation_seed_groups"]) * 256
    assert len(ids) == expected_count


def test_q2_seed_sequence_and_manifest_serialization_are_exact() -> None:
    random = _contract()["random"]
    assert random["seed_sequence"] == {
        "constructor": "SeedSequence(entropy=seed, spawn_key=(2024, 3, 2))",
        "child_stream_order": ["sales", "yield", "cost", "price"],
        "draw_order": ["year_ascending", "official_crop_id_ascending", "declared_sampling_key"],
    }
    assert random["uniform_interval"] == "[low, high)"
    assert random["scenario_manifest"]["canonical_json"] == {
        "encoding": "utf-8",
        "ensure_ascii": False,
        "sort_keys": True,
        "separators": [",", ":"],
        "allow_nan": False,
        "trailing_newline": False,
    }


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
    assert risk["primary_lambda"] == 0.25
    sensitivity = risk["sensitivity"]
    assert sensitivity["lambdas"] == [0.0, 0.25, 0.5]
    assert sensitivity["action"] == "reoptimize_each_lambda"
    assert sensitivity["optimization_scenarios"] == "same_frozen_optimization_manifest"
    assert sensitivity["evaluation_scenarios"] == "same_frozen_evaluation_manifest"
    assert sensitivity["compare_plan_structure"] is True
    assert set(["mean", "p05", "p50", "p95", "worst_profit", "cvar_loss"]).issubset(risk["reported_statistics"])


def test_q2_requires_real_q1_baseline_and_convergence_audit() -> None:
    contract = _contract()
    assert contract["q1_baseline"]["status"] == "pending_real_q1_result"
    assert contract["q1_baseline"]["must_be_frozen_before_q2_solver"] is True
    convergence = contract["convergence"]
    assert convergence["scenario_budgets"] == [64, 128, 256, 512]
    assert convergence["claim_256_scenarios_sufficient"] is False


def test_q2_contract_document_mentions_machine_identity_and_sampling_rules() -> None:
    document = (ROOT / "docs" / "cases" / "2024_C" / "Q2_MODEL_CONTRACT.md").read_text(encoding="utf-8")
    for fragment in (
        "(phase, seed, scenario_index)",
        "scenario_pool_per_seed",
        "[a,b)",
        "分别重新求解",
        "allow_nan=false",
    ):
        assert fragment in document
