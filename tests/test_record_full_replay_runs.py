from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import record_full_replay_runs as recorder  # noqa: E402


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False), encoding="utf-8")


def _run(tmp_path: Path) -> Path:
    run = tmp_path / "run-2024d"
    commit = "a" * 40
    _write(
        run / "full_replay_session.json",
        {"started_at": "2026-07-17T01:00:00+08:00", "source_control_commit": commit},
    )
    _write(run / "run_manifest.json", {"run_id": "run-2024d", "problem_id": "2024-D"})
    _write(
        run / "route_runs/Q1/R-BASE/sandboxie_run_execution_attestation.json",
        {
            "git_head": commit,
            "started_at": "2026-07-17T01:01:00+08:00",
            "completed_at": "2026-07-17T01:02:00+08:00",
        },
    )
    (run / "route_runs.stale-env").mkdir()
    _write(run / "paper_visual_review.json", {"status": "passed"})
    _write(
        run / "paper_candidate_manifest.json",
        {"candidate_status": "paper_candidate_ready_for_independent_review"},
    )
    return run


def test_build_record_binds_trusted_commit_and_discloses_reviews(tmp_path: Path) -> None:
    record = recorder.build_record(
        _run(tmp_path), datetime.fromisoformat("2026-07-17T01:03:00+08:00")
    )

    assert record["source_control_commit"] == "a" * 40
    assert record["runtime_seconds"] == 180
    assert [item["category"] for item in record["manual_interventions"]] == [
        "execution_recovery",
        "paper_review",
    ]
    assert "不是人工评审或双盲评审" in record["manual_interventions"][1]["description"]


def test_build_record_rejects_attestation_from_other_commit(tmp_path: Path) -> None:
    run = _run(tmp_path)
    path = run / "route_runs/Q1/R-BASE/sandboxie_run_execution_attestation.json"
    attestation = json.loads(path.read_text(encoding="utf-8"))
    attestation["git_head"] = "b" * 40
    _write(path, attestation)

    with pytest.raises(ValueError, match="未绑定 full_replay_session 提交"):
        recorder.build_record(run, datetime.fromisoformat("2026-07-17T01:03:00+08:00"))
