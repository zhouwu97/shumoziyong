from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from modeling_contracts import (  # noqa: E402
    derive_technical_contribution_status,
    load_json,
    validate_bundle,
    validate_case,
    validate_common_formula_evidence,
    validate_contribution_ledger,
    validate_falsification_plan,
    validate_headline_registry,
    validate_mechanism_ledger,
    validate_paper_projection,
    validate_qualification_evidence,
    validate_requirement_map,
    validate_route_applicability,
    validate_run_bundle_binding,
    validate_uncovered_area_claim,
    write_bundle,
)


CASE = ROOT / "problems" / "2023_B"


def _artifact(name: str) -> dict:
    return load_json(CASE / "modeling" / name)


def _messages(errors: list[str]) -> str:
    return "\n".join(errors)


def test_valid_2023b_case_passes_gate_a_c(tmp_path: Path) -> None:
    case = tmp_path / "2023_B"
    shutil.copytree(CASE, case)
    write_bundle(case, frozen_at="2026-07-18T00:00:00Z")

    report = validate_case(case)

    assert report["gates"] == {"A": True, "B": True, "C": True}
    assert report["status"] == "gate_c_modeling_design_frozen"
    assert report["formal_result_eligible"] is False


def test_01_rejects_missing_core_source_fragment() -> None:
    value = _artifact("requirement_map.json")
    value["requirements"].pop()

    assert "覆盖不是 100%" in _messages(validate_requirement_map(value))


def test_02_rejects_duplicate_source_anchor() -> None:
    value = _artifact("requirement_map.json")
    value["requirements"][1]["source_anchor"] = copy.deepcopy(
        value["requirements"][0]["source_anchor"]
    )

    assert "Source Anchor 重复" in _messages(validate_requirement_map(value))


def test_03_rejects_core_requirement_without_appropriate_binding() -> None:
    value = _artifact("requirement_map.json")
    value["requirements"][0]["verification_bindings"] = []

    assert "缺少 required 验证绑定" in _messages(validate_requirement_map(value))


def test_04_rejects_explanation_forced_only_into_numeric_validator() -> None:
    value = _artifact("requirement_map.json")
    requirement = value["requirements"][0]
    requirement["requirement_type"] = "explanation"
    requirement["verification_bindings"] = [
        {"mode": "numerical_validator", "artifact": "validator.json", "required": True}
    ]

    assert "解释类 Requirement" in _messages(validate_requirement_map(value))


def test_05_rejects_silently_missing_core_mechanism() -> None:
    value = _artifact("mechanism_scope_ledger.json")
    value["mechanisms"].pop()

    assert "静默丢弃" in _messages(validate_mechanism_ledger(value))


def test_06_rejects_modeled_mechanism_without_coverage_scope() -> None:
    value = _artifact("mechanism_scope_ledger.json")
    value["mechanisms"][0].pop("coverage_scope")

    assert "coverage_scope" in _messages(validate_mechanism_ledger(value))


def test_07_rejects_local_approximation_claimed_as_full_model() -> None:
    mechanisms = _artifact("mechanism_scope_ledger.json")
    projection = [
        {"claim_id": "PAPER-1", "mechanism_id": "MECH-SLOPE", "asserted_scope": "full"}
    ]

    assert "不得写成完整建模" in _messages(validate_paper_projection(projection, mechanisms))


def test_08_rejects_fake_three_route_requirement_for_q1_q2() -> None:
    value = _artifact("route_applicability.json")
    value["subproblems"][0]["route_requirement"].update(
        {"applicability": "required", "minimum_structural_routes": 3}
    )

    assert "不得伪造" in _messages(validate_route_applicability(value))


def test_09_rejects_q3_q4_route_competition_marked_not_applicable() -> None:
    value = _artifact("route_applicability.json")
    value["subproblems"][2]["route_requirement"]["applicability"] = "not_applicable"

    assert "必须竞争结构路线" in _messages(validate_route_applicability(value))


def test_10_rejects_empty_falsification_plan() -> None:
    plan = _artifact("route_falsification_plan.json")
    applicability = _artifact("route_applicability.json")
    plan["routes"][0]["falsification_tests"] = []

    errors = _messages(validate_falsification_plan(plan, applicability))
    assert "缺少数学" in errors and "缺少数值" in errors


def test_11_rejects_untriggerable_failure_condition() -> None:
    plan = _artifact("route_falsification_plan.json")
    applicability = _artifact("route_applicability.json")
    plan["routes"][0]["falsification_tests"][0]["triggerability"] = "never"

    assert "triggerability" in _messages(validate_falsification_plan(plan, applicability))


def test_12_rejects_solver_validator_common_formula_without_oracle() -> None:
    evidence = {"solver_value": 10.0, "validator_value": 10.0, "tolerance": 1e-8}

    assert "缺少独立 Reference Oracle" in _messages(validate_common_formula_evidence(evidence))


def test_13_reference_oracle_detects_common_formula_error() -> None:
    evidence = {
        "solver_value": 10.0,
        "validator_value": 10.0,
        "oracle_value": 12.0,
        "tolerance": 1e-8,
    }

    assert "复制了同一错误" in _messages(validate_common_formula_evidence(evidence))


def test_14_technical_support_does_not_imply_novelty() -> None:
    entry = _artifact("contribution_ledger.json")["entries"][0]

    derived = derive_technical_contribution_status(entry, validator_supported=True)

    assert derived["technical_status"] == "validator_supported"
    assert derived["novelty_status"] == "unassessed"


def test_15_validator_cannot_derive_innovation_status() -> None:
    entry = _artifact("contribution_ledger.json")["entries"][0]
    entry["technical_status"] = "implemented"
    entry["novelty_status"] = "common_method"

    assert derive_technical_contribution_status(entry, True)["novelty_status"] == "common_method"


def test_16_rejects_standard_method_masquerading_as_innovation() -> None:
    value = _artifact("contribution_ledger.json")
    entry = value["entries"][0]
    entry["claim"] = "使用遗传算法求解"
    entry["novelty_status"] = "potentially_novel"

    assert "标准方法" in _messages(validate_contribution_ledger(value))


def test_17_rejects_ranking_claim_without_reversal_test() -> None:
    value = _artifact("headline_claim_registry.json")
    ranking = next(item for item in value["claims"] if item["claim_type"] == "ranking")
    ranking["required_stress_tests"].remove("ranking_reversal")

    assert "排序反转" in _messages(validate_headline_registry(value))


def test_18_rejects_feasibility_claim_checking_only_one_constraint() -> None:
    value = _artifact("headline_claim_registry.json")
    feasibility = next(item for item in value["claims"] if item["claim_type"] == "feasibility")
    feasibility["validation_dimensions"] = ["one_constraint_only"]

    assert "全部硬约束" in _messages(validate_headline_registry(value))


def test_19_detects_bundle_drift_after_freeze(tmp_path: Path) -> None:
    case = tmp_path / "2023_B"
    shutil.copytree(CASE, case)
    bundle_path = write_bundle(case, frozen_at="2026-07-18T00:00:00Z")
    bundle = load_json(bundle_path)
    with (case / "model_spec.md").open("a", encoding="utf-8") as handle:
        handle.write("\n漂移\n")

    assert "冻结后漂移" in _messages(validate_bundle(case, bundle))


def test_20_rejects_old_run_bound_to_new_bundle() -> None:
    bundle = {"bundle_sha256": "b" * 64}
    old_run = {"modeling_bundle_sha256": "a" * 64}

    assert "旧 Run" in _messages(validate_run_bundle_binding(old_run, bundle))


def test_21_rejects_ai_pre_review_in_qualification_aggregation() -> None:
    items = [
        {
            "evidence_id": "AI-1",
            "review_type": "ai_exploratory_pre_review",
            "qualification_usage": True,
        }
    ]

    assert "不得进入资格聚合" in _messages(validate_qualification_evidence(items))


def test_22_rejects_100_percent_coverage_below_numeric_resolution() -> None:
    claim = {
        "estimated_uncovered_area": 0.5,
        "area_uncertainty_upper_bound": 1.0,
        "text": "方案达到 100% 覆盖，无漏测。",
    }

    assert "不得宣称" in _messages(validate_uncovered_area_claim(claim))


def test_mathodology_source_lock_is_non_executable_and_pinned() -> None:
    lock = json.loads((ROOT / "upstream" / "mathodology.lock.json").read_text("utf-8"))

    assert lock["commit"] == "987644876160d105f0fa768248f5d23764f288b2"
    assert lock["runtime_import_allowed"] is False
    assert lock["execution_allowed"] is False
    assert lock["workflow_activation_allowed"] is False
    assert (ROOT / "upstream" / "LICENSE.mathodology").read_text("utf-8").startswith(
        "MIT License"
    )
