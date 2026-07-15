from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_matlab_recomputation import run_recomputation, sha256_file


MATLAB = Path(r"E:\Matlab\bin\matlab.exe")


def _ref(run_dir: Path, path: str) -> dict[str, str]:
    file_path = run_dir / path
    return {"path": path, "sha256": sha256_file(file_path)}


@pytest.mark.skipif(not MATLAB.is_file(), reason="MATLAB executable unavailable")
def test_level_a_and_b_execute_with_real_matlab(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "matlab_test"}), encoding="utf-8"
    )
    (run_dir / "official_input.txt").write_text("official", encoding="utf-8")
    (run_dir / "python_result.json").write_text("{}", encoding="utf-8")
    common = {
        "schema_version": "1.0.0",
        "run_id": "matlab_test",
        "official_input_refs": [_ref(run_dir, "official_input.txt")],
        "python_result_ref": _ref(run_dir, "python_result.json"),
        "tolerances": {"objective": 1e-9, "constraint": 1e-9, "statistic": 1e-9, "decision": 1e-9},
    }
    level_a = {
        **common,
        "level": "A",
        "model": {
            "decision_vector": [1, 2],
            "objective_coefficients": [3, 4],
            "objective_constant": 1,
            "constraints": [{"name": "budget", "coefficients": [1, 1], "sense": "<=", "rhs": 4}],
            "python_metrics": {"objective_value": 12, "max_constraint_violation": 0, "decision_sum": 3},
        },
    }
    level_a_path = run_dir / "matlab_level_a_input.json"
    level_a_path.write_text(json.dumps(level_a), encoding="utf-8")
    report_a = run_recomputation(run_dir, level_a_path, run_dir / "matlab_level_a_report.json", "A")
    assert report_a["status"] == "passed"
    assert all(item["passed"] for item in report_a["checks"])

    level_b = {
        **common,
        "level": "B",
        "small_examples": [
            {
                "case_id": "toy_001",
                "objective_direction": "min",
                "objective_coefficients": [1, 2],
                "variables": [
                    {"lower": 0, "upper": 2, "step": 1},
                    {"lower": 0, "upper": 2, "step": 1},
                ],
                "constraints": [{"name": "sum", "coefficients": [1, 1], "sense": ">=", "rhs": 2}],
                "python_expected": {
                    "objective_value": 2,
                    "decision_vector": [2, 0],
                    "boundary_checks": [{"name": "sum", "coefficients": [1, 1], "sense": ">=", "rhs": 2, "expected": True}],
                },
            }
        ],
    }
    level_b_path = run_dir / "matlab_level_b_input.json"
    level_b_path.write_text(json.dumps(level_b), encoding="utf-8")
    report_b = run_recomputation(run_dir, level_b_path, run_dir / "matlab_level_b_report.json", "B")
    assert report_b["status"] == "passed"
    assert all(item["passed"] for item in report_b["checks"])


def test_missing_matlab_input_is_a_blocker(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(json.dumps({"run_id": "blocked"}), encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        run_recomputation(run_dir, run_dir / "missing.json", run_dir / "report.json", "A")
