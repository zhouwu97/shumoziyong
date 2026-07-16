"""PR-7 可信路线独立可执行性与选择规则测试。"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from finalize_full_replay_runs import ROLE_PRIORITY, _operability_checks
from full_replay_route_solver import SOLVERS
from prepare_full_replay_runs import _route_config


def _result(problem_id: str, subproblem_id: str, category: str, role: str) -> tuple[dict, dict]:
    config = _route_config(problem_id, subproblem_id, category)
    config.update({"route_id": f"R-{role.upper()}", "role": role})
    objective, details = SOLVERS[category](config)
    return config, {"objective": objective, "details": details}


def test_sampling_validator_rejects_risky_baseline_and_accepts_primary() -> None:
    baseline_config, baseline = _result("2024-B", "Q1", "sampling", "baseline")
    primary_config, primary = _result("2024-B", "Q1", "sampling", "primary")

    assert not all(
        check.passed for check in _operability_checks("sampling", baseline_config, baseline)
    )
    assert all(
        check.passed for check in _operability_checks("sampling", primary_config, primary)
    )


def test_crop_validator_enforces_rotation_instead_of_trusting_objective() -> None:
    baseline_config, baseline = _result("2024-C", "Q1", "crop", "baseline")
    primary_config, primary = _result("2024-C", "Q1", "crop", "primary")

    assert baseline["objective"] > primary["objective"]
    assert not all(check.passed for check in _operability_checks("crop", baseline_config, baseline))
    assert all(check.passed for check in _operability_checks("crop", primary_config, primary))


def test_equal_objective_prefers_primary_after_feasibility_filter() -> None:
    routes = [
        {"role": "baseline", "objective": 10.0},
        {"role": "structural_alternative", "objective": 9.0},
        {"role": "primary", "objective": 10.0},
    ]

    selected = max(
        routes,
        key=lambda item: (item["objective"], ROLE_PRIORITY[item["role"]]),
    )

    assert selected["role"] == "primary"
