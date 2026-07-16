from __future__ import annotations

import subprocess
import sys
import time
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from attempt_workspace import ActiveAttemptError, attempt_workspace  # noqa: E402
from process_tree_v2 import ProcessTreeTimeoutExpired, run_process_tree  # noqa: E402
import process_tree_v2  # noqa: E402
import run_a092_stage3  # noqa: E402
import run_a092_claude_v3  # noqa: E402


def test_timeout_terminates_descendant_process_before_it_can_write(tmp_path: Path) -> None:
    marker = tmp_path / "orphan_wrote.txt"
    child = (
        "import time; from pathlib import Path; "
        f"time.sleep(0.8); Path({str(marker)!r}).write_text('orphan', encoding='utf-8')"
    )
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
    )

    with pytest.raises(ProcessTreeTimeoutExpired) as caught:
        run_process_tree([sys.executable, "-c", parent], timeout=0.2)

    time.sleep(1.0)
    assert caught.value.process_tree_terminated is True
    assert not marker.exists()


def test_posix_process_group_confirmation_waits_for_delayed_reaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """进程组短暂残留时应等待系统完成回收，而不是立即报告清理失败。"""
    probes = iter((None, None, ProcessLookupError()))

    def fake_killpg(_process_group: int, signal_number: int) -> None:
        assert signal_number == 0
        outcome = next(probes)
        if isinstance(outcome, BaseException):
            raise outcome

    monkeypatch.setattr(process_tree_v2.os, "killpg", fake_killpg, raising=False)

    assert process_tree_v2._wait_for_posix_process_group_exit(
        1234,
        timeout=0.1,
        poll_interval=0,
    )


def test_only_one_active_attempt_is_allowed_per_run(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared" / "R09"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    with attempt_workspace(tmp_path, "R09", prepared) as first:
        assert first.path != prepared
        assert (first.path / "prompt_exact.md").read_text(encoding="utf-8") == "prompt"
        with pytest.raises(ActiveAttemptError, match="active attempt"):
            with attempt_workspace(tmp_path, "R09", prepared):
                pass

    with attempt_workspace(tmp_path, "R09", prepared) as second:
        assert second.attempt_id != first.attempt_id


def test_attempt_is_atomically_promoted_only_after_success(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared" / "R01"
    prepared.mkdir(parents=True)
    (prepared / "input.txt").write_text("frozen", encoding="utf-8")
    official = tmp_path / "runs" / "R01"

    with attempt_workspace(tmp_path, "R01", prepared) as attempt:
        (attempt.path / "result.txt").write_text("complete", encoding="utf-8")
        assert not official.exists()
        attempt.promote(official)

    assert not attempt.path.exists()
    assert (official / "input.txt").read_text(encoding="utf-8") == "frozen"
    assert (official / "result.txt").read_text(encoding="utf-8") == "complete"


def test_failed_attempt_is_never_promoted(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared" / "R02"
    prepared.mkdir(parents=True)
    official = tmp_path / "runs" / "R02"

    with attempt_workspace(tmp_path, "R02", prepared) as attempt:
        (attempt.path / "partial.txt").write_text("partial", encoding="utf-8")

    assert attempt.path.is_dir()
    assert not official.exists()


def test_a092_runner_executes_in_attempt_then_promotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_root = tmp_path / "a092"
    prepared = work_root / "prepared" / "R01"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")
    observed: dict[str, Path | list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        attempt_dir = Path(args[args.index("-C") + 1])
        observed["attempt_dir"] = attempt_dir
        observed["command"] = args
        assert attempt_dir == kwargs["cwd"]
        (attempt_dir / "results").mkdir()
        (attempt_dir / "results" / "formal_result.json").write_text("{}", encoding="utf-8")
        Path(args[args.index("--output-last-message") + 1]).write_text("done", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(run_a092_stage3, "WORK_ROOT", work_root)
    monkeypatch.setattr(run_a092_stage3, "run_process_tree", fake_run)

    assert run_a092_stage3.execute("R01") == 0

    official = work_root / "runs" / "R01"
    metadata = json.loads((official / "runner_metadata.json").read_text(encoding="utf-8"))
    assert official.is_dir()
    assert observed["attempt_dir"] != official
    assert isinstance(observed["attempt_dir"], Path)
    assert not observed["attempt_dir"].exists()
    assert metadata["attempt_id"].startswith("attempt-")
    assert metadata["execution_status"] == "completed"
    assert not (work_root / "active_attempts" / "R01.json").exists()
    assert "--ignore-user-config" not in observed["command"]


def test_a092_runner_keeps_timed_out_attempt_unpromoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_root = tmp_path / "a092"
    prepared = work_root / "prepared" / "R02"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    def fake_timeout(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise ProcessTreeTimeoutExpired(
            args,
            1,
            output=None,
            stderr=None,
            process_tree_terminated=True,
            termination_details={"method": "test", "process_tree_terminated": True},
        )

    monkeypatch.setattr(run_a092_stage3, "WORK_ROOT", work_root)
    monkeypatch.setattr(run_a092_stage3, "run_process_tree", fake_timeout)

    assert run_a092_stage3.execute("R02") == 124

    attempts = list((work_root / "attempts" / "R02").iterdir())
    metadata = json.loads((attempts[0] / "runner_metadata.json").read_text(encoding="utf-8"))
    assert len(attempts) == 1
    assert metadata["execution_status"] == "timeout"
    assert metadata["process_tree_terminated"] is True
    assert not (work_root / "runs" / "R02").exists()


def test_a092_runner_retains_run_lock_when_tree_cleanup_is_unproven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_root = tmp_path / "a092"
    prepared = work_root / "prepared" / "R03"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    def fake_unclean_timeout(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise ProcessTreeTimeoutExpired(
            args,
            1,
            output=None,
            stderr=None,
            process_tree_terminated=False,
            termination_details={"method": "test", "process_tree_terminated": False},
        )

    monkeypatch.setattr(run_a092_stage3, "WORK_ROOT", work_root)
    monkeypatch.setattr(run_a092_stage3, "run_process_tree", fake_unclean_timeout)

    assert run_a092_stage3.execute("R03") == 125

    lock_path = work_root / "active_attempts" / "R03.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["lock_retained"] is True
    with pytest.raises(ActiveAttemptError):
        run_a092_stage3.execute("R03")


def test_v2_runner_uses_separate_root_and_protocol_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_root = tmp_path / "a092_v2"
    prepared = work_root / "prepared" / "R01"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(run_a092_stage3, "V2_WORK_ROOT", work_root)
    monkeypatch.setattr(run_a092_stage3, "V2_ARCHIVE_ROOT", tmp_path / "archive_v2")
    monkeypatch.setattr(run_a092_stage3, "verify_v2_freeze", lambda: {})
    monkeypatch.setattr(run_a092_stage3, "run_process_tree", fake_run)

    assert run_a092_stage3.execute("R01", "v2") == 0
    metadata = json.loads(
        (work_root / "runs" / "R01" / "runner_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["protocol_id"] == "A092-CONFIRMATORY-V2"


def test_claude_v3_runner_rejects_model_drift_and_keeps_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_root = tmp_path / "a092_v3"
    prepared = work_root / "prepared" / "R01"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        stdout = kwargs["stdout"]
        stdout.write(
            json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": "session-1",
                    "model": "unexpected-model",
                    "claude_code_version": "2.1.207",
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(run_a092_claude_v3, "WORK_ROOT", work_root)
    monkeypatch.setattr(run_a092_claude_v3, "verify_v3_freeze", lambda: {})
    monkeypatch.setattr(run_a092_claude_v3, "run_process_tree", fake_run)

    assert run_a092_claude_v3.execute("R01") == 1
    attempts = list((work_root / "attempts" / "R01").iterdir())
    metadata = json.loads((attempts[0] / "runner_metadata.json").read_text(encoding="utf-8"))
    assert metadata["engine_valid"] is False
    assert not (work_root / "runs" / "R01").exists()
