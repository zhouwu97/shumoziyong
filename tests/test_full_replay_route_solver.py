"""PR-7 五类数学路线与 Gate 1 编译回归。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from full_replay_route_solver import SOLVERS
from prepare_full_replay_runs import PROBLEMS, _model_route, _route_config
from route_contract_dispatch import validate_artifact


def test_prepare_full_replay_cli_can_start_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/prepare_full_replay_runs.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_all_route_families_produce_finite_distinct_results() -> None:
    samples = [
        ("2016-C", "Q1", "prediction"),
        ("2023-B", "Q3", "survey"),
        ("2024-B", "Q1", "sampling"),
        ("2024-B", "Q2", "decision"),
        ("2024-C", "Q2", "crop"),
        ("2024-D", "Q3", "depth_charge"),
    ]
    for problem_id, subproblem_id, category in samples:
        methods = set()
        objectives = []
        for role in ("baseline", "primary", "structural_alternative"):
            config = _route_config(problem_id, subproblem_id, category)
            config["role"] = role
            objective, details = SOLVERS[category](config)
            assert objective == objective
            methods.add(details["method"])
            objectives.append(round(objective, 10))
        assert len(methods) == 3
        assert len(set(objectives)) >= 2


def test_compiled_model_route_covers_all_17_subproblems() -> None:
    total = 0
    for problem_id, problem in PROBLEMS.items():
        manifest = {
            "run_id": problem["run"],
            "problem_id": problem_id,
            "profile": problem["profile"],
            "runtime_version": "0.1.0",
            "runtime_pack_sha256": "a" * 64,
            "material_manifest": f"official_materials/{problem['material']}/material_manifest.json",
        }
        model = _model_route(manifest, problem)
        validate_artifact(model, context="full_replay")
        total += len(model["subproblems"])
        for subproblem in model["subproblems"]:
            assert {route["role"] for route in subproblem["routes"]} == {
                "baseline",
                "primary",
                "structural_alternative",
            }
            assert len({route["structural_family"] for route in subproblem["routes"]}) == 3
    assert total == 17
