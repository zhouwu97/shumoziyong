from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from validators.common.claim_level import claim_is_allowed, derive_optimality_claim  # noqa: E402
from validators.common.improvement import compare_with_baseline  # noqa: E402
from validators.common.residuals import check_constraints  # noqa: E402
from validators.common.sensitivity import run_sensitivity_checks  # noqa: E402
from validators.common.types import ConstraintValue  # noqa: E402
from validators.pilot_case.run_pilot import run_fault_injections  # noqa: E402
from freeze_a092_protocol import build_freeze_record  # noqa: E402


def _load_json(relative: str) -> object:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_constraint_passes_when_absolute_or_scaled_tolerance_passes() -> None:
    results, violated, max_raw, max_scaled = check_constraints(
        [ConstraintValue("scaled", "inequality", 0.01, scale=10_000.0)],
        absolute_tolerance=1e-6,
        relative_tolerance=1e-5,
    )

    assert violated == []
    assert max_raw == 0.01
    assert max_scaled == 1e-6
    assert results[0]["satisfied"] is True


def test_improvement_uses_absolute_baseline_and_handles_near_zero() -> None:
    negative = compare_with_baseline(
        objective_direction="maximize",
        baseline_objective=-10,
        candidate_objective=-8,
        epsilon=1e-9,
    )
    near_zero = compare_with_baseline(
        objective_direction="minimize",
        baseline_objective=1e-12,
        candidate_objective=0,
        epsilon=1e-9,
        reported_ratio=1.0,
    )

    assert negative["absolute_improvement"] == 2
    assert negative["improvement_ratio"] == 0.2
    assert near_zero["improvement_ratio"] is None
    assert near_zero["baseline_near_zero"] is True
    assert near_zero["improvement_ratio_consistent"] is False


def test_sensitivity_can_be_closed_only_with_reason_and_impact() -> None:
    valid = run_sensitivity_checks(
        {
            "status": "not_applicable",
            "reason": "本题没有可解释扰动参数",
            "impact_on_core_conclusion": "不影响固定公式的直接计算结论",
        }
    )
    invalid = run_sensitivity_checks({"status": "not_applicable", "reason": "不适用"})

    assert valid["checks_passed"] is True
    assert invalid["checks_passed"] is False


def test_heuristic_search_cannot_claim_global_optimum() -> None:
    allowed = derive_optimality_claim(
        {"method": "heuristic_search", "independent_checks_passed": True},
        feasible=True,
        objective_consistent=True,
    )

    assert allowed == "best_found_in_search"
    assert claim_is_allowed("global_optimum_verified", allowed) is False
    assert claim_is_allowed("locally_optimal_candidate", allowed) is False


def test_pilot_detects_all_seven_fault_injections() -> None:
    valid, faults = run_fault_injections()

    assert valid["valid"] is True
    assert len(faults) == 7
    assert all(fault["detected"] for fault in faults)


def test_a092_schemas_validate_protocol_knowledge_and_pilot_result() -> None:
    protocol_schema = _load_json("schemas/a092_experiment_protocol.schema.json")
    knowledge_schema = _load_json("schemas/knowledge_card.schema.json")
    validator_schema = _load_json("schemas/a092_validator_result.schema.json")
    claim_map_schema = _load_json("schemas/a092_claim_map.schema.json")
    protocol = _load_json("protocols/a092_experiment_protocol.json")
    knowledge = _load_json("papers/2023_A092_知识卡片.json")
    valid, _ = run_fault_injections()

    Draft202012Validator(protocol_schema).validate(protocol)
    Draft202012Validator(knowledge_schema).validate(knowledge)
    Draft202012Validator(validator_schema).validate(valid)
    Draft202012Validator(claim_map_schema).validate(
        _load_json("examples/a092_phase2_pilot/artifacts/a092/claim_map.json")
    )
    assert knowledge["source"]["verification_status"] == "verified"  # type: ignore[index]
    assert len(knowledge["source"]["claims"]) == 7  # type: ignore[index]


def test_patch_index_keeps_a092_review_ready_with_verified_claims() -> None:
    patch_index = _load_json("prompt_patches/patch_index.json")
    a092 = next(item for item in patch_index if item["patch_id"] == "A092")  # type: ignore[union-attr]

    assert a092["status"] == "review_ready"
    assert len(a092["source"]["claim_ids"]) == 7


def test_freeze_record_binds_all_protocol_inputs() -> None:
    record = build_freeze_record("a" * 40)
    schema = _load_json("schemas/a092_protocol_freeze.schema.json")

    Draft202012Validator(schema).validate(record)
    assert record["pilot_evidence_allowed"] is False
    assert len(record["validator_files"]) >= 6
    assert record["protocol_deviation"] is True
    assert len(record["deviation_records"]) == 1
