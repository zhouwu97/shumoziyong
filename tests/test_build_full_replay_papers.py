from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_full_replay_papers import (  # noqa: E402
    _build_claim_map,
    _display_number,
    _selected_route,
)


def test_display_number_normalizes_negative_zero() -> None:
    assert _display_number(-3.267144213156278e-16) == "0.000000"
    assert _display_number(0.08584078662173278) == "0.085841"


def test_selected_route_rejects_infeasible_result() -> None:
    model = {
        "subproblems": [
            {
                "subproblem_id": "Q1",
                "routes": [{"route_id": "R-PRIMARY", "name": "主路线"}],
            }
        ]
    }
    comparison = {
        "selected_route_id": "R-PRIMARY",
        "route_results": [
            {
                "route_id": "R-PRIMARY",
                "execution_status": "completed",
                "feasible": False,
                "data_leakage_detected": False,
                "stability_status": "passed",
                "metrics": [{"name": "objective", "value": 1.0}],
            }
        ],
    }

    with pytest.raises(ValueError, match="不满足论文准入条件"):
        _selected_route(model, comparison, "Q1")


def test_claim_map_binds_selected_route_objective_pointer() -> None:
    binding = {
        "run_id": "run-1",
        "problem_id": "2024-D",
        "profile": "evaluation",
        "runtime_version": "0.1.0",
        "runtime_pack_sha256": "a" * 64,
    }
    evidence = [
        {
            "subproblem_id": "Q2",
            "route": {"name": "低差异结构备选"},
            "result_index": 2,
            "objective": 0.08584078662173278,
            "display": "0.085841",
        }
    ]

    claim = _build_claim_map(binding, evidence)["claims"][0]

    assert claim["source_file"] == "route_comparison_result_Q2.json"
    assert claim["json_pointer"] == "/route_results/2/metrics/0/value"
    assert claim["rounding_rule"] == "6_decimal"
