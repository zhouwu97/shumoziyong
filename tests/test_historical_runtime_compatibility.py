from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_workflow import verify_run  # noqa: E402


FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "historical_sealed_run_v1_1"
RUN_DIR = FIXTURE_ROOT / "historical_v1_1_sealed"


def test_base_v1_1_sealed_run_remains_verifiable_without_migration() -> None:
    """Base 生成的 sealed Run 必须保持字节不变并由 Head 的 legacy verifier 接受。"""
    provenance = json.loads((FIXTURE_ROOT / "provenance.json").read_text(encoding="utf-8"))
    run_manifest = json.loads((RUN_DIR / "run_manifest.json").read_text(encoding="utf-8"))
    runtime_manifest = json.loads(
        (RUN_DIR / "runtime_pack.manifest.json").read_text(encoding="utf-8")
    )
    assert provenance["source_commit"] == "4baec51abd1fac8be56c6badb1a97ebfdc163f46"
    assert runtime_manifest["manifest_version"] == "1.1.0"
    assert "workflow_context" not in runtime_manifest
    assert "runtime_contract" not in runtime_manifest
    assert "evidence_purpose" not in run_manifest

    report = verify_run(RUN_DIR)
    assert report["completed"] is True
    assert report["sealed"] is True
    assert report["advance_allowed"] is False


def test_unknown_runtime_manifest_version_fails_closed(tmp_path: Path) -> None:
    """未知 manifest 版本不得借用 legacy 兼容路径。"""
    copied_run = tmp_path / "run"
    shutil.copytree(RUN_DIR, copied_run)
    runtime_manifest_path = copied_run / "runtime_pack.manifest.json"
    runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
    runtime_manifest["manifest_version"] = "9.9.9"
    runtime_manifest_path.write_text(json.dumps(runtime_manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest_version 不支持"):
        verify_run(copied_run)
