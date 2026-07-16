from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from competition_route_runtime import evaluate_competition_gate3  # noqa: E402
from score_v3 import (  # noqa: E402
    REQUIRED_DIMENSION_EVIDENCE,
    SOURCE_PATHS,
    ScoreV3Error,
    build_score_v3,
)
from test_competition_route_runtime import (  # noqa: E402
    _make_formal_results_eligible,
    _prepare_parent,
    _rewrite_report_for_failed_check,
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ratings(parent: Path, score: float = 100.0) -> Path:
    model = json.loads((parent / "model_route_v3.json").read_text(encoding="utf-8"))
    dimensions: dict[str, dict[str, Any]] = {}
    for dimension, keys in REQUIRED_DIMENSION_EVIDENCE.items():
        dimensions[dimension] = {
            "score": score,
            "rationale": f"{dimension} 已按当前运行证据逐项审核并给出评分。",
            "evidence_paths": sorted(
                SOURCE_PATHS[key].format(subproblem_id="Q1") for key in keys
            ),
        }
    value = {
        "schema_version": "1.0.0",
        "artifact_type": "score_v3_ratings_v1",
        "run_id": model["run_id"],
        "subproblem_id": "Q1",
        "scorer_id": "independent-scorer",
        "gate3_decision_sha256": hashlib.sha256(
            (parent / "competition_gate3_decision_Q1.json").read_bytes()
        ).hexdigest(),
        "dimensions": dimensions,
    }
    path = parent / "score_v3_ratings_Q1.json"
    _write_json(path, value)
    return path


def _eligible_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    parent = _prepare_parent(tmp_path, monkeypatch)
    _make_formal_results_eligible(monkeypatch)
    decision = evaluate_competition_gate3(parent, "Q1", "independent-validator")
    assert decision["decision"] == "allow_paper"
    return parent


def test_score_v3_fixed_nine_dimension_weights_and_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _eligible_parent(tmp_path, monkeypatch)
    score = build_score_v3(parent, "Q1", _ratings(parent))
    assert len(score["dimensions"]) == 9
    assert sum(item["weight"] for item in score["dimensions"].values()) == pytest.approx(1.0)
    assert score["raw_total"] == 100
    assert score["final_score"] == 100
    assert score["fatal_codes"] == []
    assert score["submission_status"] == "eligible"
    assert score["submission_allowed"] is True


def test_score_v3_low_nonfatal_score_is_technical_report_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _eligible_parent(tmp_path, monkeypatch)
    score = build_score_v3(parent, "Q1", _ratings(parent, score=60))
    assert score["final_score"] == 60
    assert score["fatal_cap_applied"] is False
    assert score["submission_status"] == "technical_report_only"
    assert score["technical_report_allowed"] is True


def test_formal_result_fatal_caps_score_at_70_and_forbids_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    decision = evaluate_competition_gate3(parent, "Q1", "independent-validator")
    assert decision["decision"] == "technical_report_only"
    score = build_score_v3(parent, "Q1", _ratings(parent))
    assert score["raw_total"] > 70
    assert score["final_score"] == 70
    assert score["fatal_cap_applied"] is True
    assert score["fatal_codes"] == ["V3F_FORMAL_RESULT_INELIGIBLE"]
    assert score["submission_allowed"] is False
    assert score["technical_report_allowed"] is True


def test_fatal_cap_does_not_raise_a_lower_raw_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    evaluate_competition_gate3(parent, "Q1", "independent-validator")
    score = build_score_v3(parent, "Q1", _ratings(parent, score=40))
    assert score["raw_total"] < 70
    assert score["final_score"] == score["raw_total"]
    assert score["fatal_cap_applied"] is True


def test_hard_operability_failure_maps_to_v3_fatal_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    _make_formal_results_eligible(monkeypatch)
    _rewrite_report_for_failed_check(parent, "minimum_order", "OP-MINIMUM-ORDER")
    decision = evaluate_competition_gate3(parent, "Q1", "independent-validator")
    assert decision["decision"] == "block"
    score = build_score_v3(parent, "Q1", _ratings(parent))
    assert score["final_score"] <= 70
    assert score["fatal_codes"] == ["V3F_OPERABILITY_HARD_FAILURE"]
    assert score["submission_status"] == "blocked"


def test_dimension_cannot_cite_outside_current_pr2_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _eligible_parent(tmp_path, monkeypatch)
    ratings_path = _ratings(parent)
    ratings = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings["dimensions"]["mechanism_hypothesis"]["evidence_paths"].append(
        "paper/manuscript.typ"
    )
    _write_json(ratings_path, ratings)
    with pytest.raises(ScoreV3Error, match="证据集合之外"):
        build_score_v3(parent, "Q1", ratings_path)


def test_dimension_must_include_required_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _eligible_parent(tmp_path, monkeypatch)
    ratings_path = _ratings(parent)
    ratings = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings["dimensions"]["business_constraints"]["evidence_paths"] = [
        "model_route_v3.json"
    ]
    _write_json(ratings_path, ratings)
    with pytest.raises(ScoreV3Error, match="缺少必需证据"):
        build_score_v3(parent, "Q1", ratings_path)


def test_score_rejects_stale_gate3_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _eligible_parent(tmp_path, monkeypatch)
    ratings_path = _ratings(parent)
    decision_path = parent / "competition_gate3_decision_Q1.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["validator"]["validator_id"] = "tampered-validator"
    _write_json(decision_path, decision)
    with pytest.raises(ScoreV3Error, match="Gate 3 SHA-256"):
        build_score_v3(parent, "Q1", ratings_path)


def test_v3_namespace_does_not_reinterpret_legacy_f1_to_f5() -> None:
    policy = json.loads(
        (ROOT / "runtime_contracts" / "score_v3_policy_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy["legacy_namespace"] == {
        "artifact_type": "score_v2",
        "fatal_codes": ["F1", "F2", "F3", "F4", "F5"],
        "reinterpretation_forbidden": True,
    }
    assert all(code.startswith("V3F_") for code in policy["fatal_mapping"].values())


def test_score_v3_policy_freezes_weights_cap_and_fatal_codes() -> None:
    policy = json.loads(
        (ROOT / "runtime_contracts" / "score_v3_policy_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy["weights"] == {
        "mechanism_hypothesis": 0.10,
        "business_constraints": 0.10,
        "route_competition": 0.12,
        "execution_completeness": 0.10,
        "comparison_quality": 0.12,
        "formal_evidence": 0.16,
        "operability": 0.12,
        "risk_robustness": 0.10,
        "submission_readiness": 0.08,
    }
    assert policy["fatal_cap"] == 70
    assert policy["fatal_mapping"] == {
        "G3V3_ROUTE_EXECUTION_INCOMPLETE": "V3F_ROUTE_EXECUTION_INCOMPLETE",
        "G3V3_SELECTED_ROUTE_INADMISSIBLE": "V3F_SELECTED_ROUTE_INADMISSIBLE",
        "G3V3_DATA_LEAKAGE": "V3F_DATA_LEAKAGE",
        "G3V3_OPERABILITY_FAILED": "V3F_OPERABILITY_HARD_FAILURE",
        "G3V3_RISK_BLOCK": "V3F_RISK_BLOCK",
        "G3V3_FORMAL_RESULT_INELIGIBLE": "V3F_FORMAL_RESULT_INELIGIBLE",
    }
