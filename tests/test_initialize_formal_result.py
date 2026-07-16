"""生产级 Formal Result 初始化器回归测试。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from formal_result.verifier import verify_formal_result_bundle
from formal_result_fixtures import write_formal_result_bundle
from initialize_formal_result import initialize_formal_result
from test_repository_tooling import _v2_gate_0_run


LIVE_REPORT = (
    ROOT
    / "output"
    / "environment"
    / "sandboxie-m2"
    / "2026-07-12"
    / "sandboxie_environment_report.json"
)


def test_initializer_binds_existing_code_inputs_and_signed_environment(tmp_path: Path) -> None:
    run_dir = _v2_gate_0_run(tmp_path)
    write_formal_result_bundle(run_dir, sandboxie_report=LIVE_REPORT)
    shutil.rmtree(run_dir / "formal_results")

    envelope = initialize_formal_result(
        run_dir,
        "formal-production-001",
        LIVE_REPORT,
        mechanism="heuristic",
        validator_id="production-independent-validator-v1",
    )
    summary = verify_formal_result_bundle(run_dir, envelope)

    assert summary["formal_result_activation_status"] == "sandboxie_environment_verified"
    assert summary["sandboxie_environment_verified"] is True
    assert summary["formal_result_executed_in_verified_environment"] is False
    assert summary["formal_result_eligible"] is False
