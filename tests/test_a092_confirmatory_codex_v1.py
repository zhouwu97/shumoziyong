from __future__ import annotations

import json
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from freeze_hash import canonical_file_sha256  # noqa: E402


def _load_json(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _load_module(name: str, relative: str):
    spec = spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_v1_schema_and_only_engine_level_protocol_drift() -> None:
    v4 = _load_json("protocols/a092_v4/a092_confirmatory_v4.json")
    codex = _load_json("protocols/a092_codex_v1/a092_confirmatory_codex_v1.json")
    schema = _load_json("schemas/a092_confirmatory_codex_v1.schema.json")
    Draft202012Validator(schema).validate(codex)
    for key in ("patch_id", "patch_status", "state", "execution_started", "pilot_evidence_allowed", "case_roles", "paired_runs", "attempt_isolation", "external_validation", "tolerances", "promotion_thresholds", "experiment_invalid"):
        assert codex[key] == v4[key]
    assert codex["execution_engine"] != v4["execution_engine"]
    assert codex["supersedes"] == "A092-CONFIRMATORY-V4"
    assert codex["controls"][3:] == v4["controls"][3:]


def test_codex_v1_freeze_matches_every_bound_component() -> None:
    module = _load_module("freeze_a092_codex_v1", "scripts/freeze_a092_codex_v1_protocol.py")
    record = module.build_freeze_record()
    assert record == _load_json("protocols/a092_codex_v1/protocol_freeze.json")
    for component, expected in record["components"].items():
        assert canonical_file_sha256(ROOT / component) == expected


def test_codex_runner_promotes_only_complete_formal_result(tmp_path: Path, monkeypatch) -> None:
    runner = _load_module("run_a092_codex_v1", "scripts/run_a092_codex_v1.py")
    work_root = tmp_path / "codex_v1"
    prepared = work_root / "prepared" / "R01"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = Path(kwargs["cwd"])
        (cwd / "results").mkdir()
        (cwd / "results" / "formal_result.json").write_text("{}", encoding="utf-8")
        kwargs["stdout"].write('{"type":"thread.started","thread_id":"t1"}\n')
        kwargs["stdout"].write('{"type":"turn.completed","usage":{}}\n')
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner, "WORK_ROOT", work_root)
    monkeypatch.setattr(runner, "verify_freeze", lambda: {})
    monkeypatch.setattr(runner, "_resolve_codex", lambda: Path("codex.exe"))
    monkeypatch.setattr(runner, "run_process_tree", fake_run)
    assert runner.execute("R01") == 0
    metadata = json.loads((work_root / "runs" / "R01" / "runner_metadata.json").read_text(encoding="utf-8"))
    assert metadata["engine_valid"] is True
    assert metadata["formal_result_valid_json"] is True


def test_codex_runner_rejects_normal_exit_without_formal_result(tmp_path: Path, monkeypatch) -> None:
    runner = _load_module("run_a092_codex_v1_missing", "scripts/run_a092_codex_v1.py")
    work_root = tmp_path / "codex_v1"
    prepared = work_root / "prepared" / "R01"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        kwargs["stdout"].write('{"type":"thread.started","thread_id":"t1"}\n')
        kwargs["stdout"].write('{"type":"turn.completed","usage":{}}\n')
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner, "WORK_ROOT", work_root)
    monkeypatch.setattr(runner, "verify_freeze", lambda: {})
    monkeypatch.setattr(runner, "_resolve_codex", lambda: Path("codex.exe"))
    monkeypatch.setattr(runner, "run_process_tree", fake_run)
    assert runner.execute("R01") == 1
    assert not (work_root / "runs" / "R01").exists()
