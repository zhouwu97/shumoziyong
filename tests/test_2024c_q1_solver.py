"""2024-C Q1 完整 Solver 与独立 Validator 测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from official_integration import official_2024c_attachments


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.official_integration
def test_q1_solver_builds_formal_artifacts_with_independent_validation(tmp_path: Path) -> None:
    attachment_1, _ = official_2024c_attachments()
    material_root = attachment_1.parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_2024c_q1.py"),
            "--material-root",
            str(material_root),
            "--output-dir",
            str(tmp_path),
            "--time-limit-seconds",
            "20",
            "--mip-relative-gap",
            "0.0001",
            "--random-seed",
            "20240718",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    formal_result_path = tmp_path / "q1_formal_result.json"
    run_log_path = tmp_path / "q1_solver_run_log.json"
    formal_result = json.loads(formal_result_path.read_text(encoding="utf-8"))
    run_log = json.loads(run_log_path.read_text(encoding="utf-8"))
    assert [item["scenario_id"] for item in formal_result["scenarios"]] == [
        "q1_waste",
        "q1_discount",
    ]
    assert all(item["output_workbook_status"] == "generated" for item in formal_result["scenarios"])
    assert run_log["q1_independent_recalculation_passed"] is True
    assert run_log["qualification_claimed"] is False
    assert run_log["production_ready"] is False
    assert run_log["complete_official_old_problem_closure"] == 0
    assert run_log["settings"]["random_seed"] == 20240718
    assert all(item["mip_gap"] is not None for item in run_log["scenarios"])
    assert run_log["optimality_claimed"] is False
    assert all(item["workbook_validation"]["passed"] for item in run_log["scenarios"])
    assert (tmp_path / "result1_1.xlsx").is_file()
    assert (tmp_path / "result1_2.xlsx").is_file()
    assert formal_result_path.is_file()
    assert run_log_path.is_file()
