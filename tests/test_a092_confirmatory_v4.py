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


def _load_json(path: str) -> object:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _load_module(name: str, relative: str):
    spec = spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3_freeze_remains_unchanged_after_invalid_attempt() -> None:
    module = _load_module("freeze_a092_v3_protocol", "scripts/freeze_a092_v3_protocol.py")
    assert module.build_freeze_record() == _load_json("protocols/a092_v3/protocol_freeze.json")


def test_v4_protocol_supersedes_v3_with_permission_probe() -> None:
    protocol = _load_json("protocols/a092_v4/a092_confirmatory_v4.json")
    schema = _load_json("schemas/a092_confirmatory_v4.schema.json")
    Draft202012Validator(schema).validate(protocol)
    assert protocol["supersedes"] == "A092-CONFIRMATORY-V3"  # type: ignore[index]
    assert protocol["execution_engine"]["permission_mode"] == "bypassPermissions"  # type: ignore[index]
    invalid = _load_json("protocols/a092_v3/invalid_attempt_R01.json")
    assert invalid["counts_toward_confirmatory_pairs"] is False  # type: ignore[index]
    assert invalid["official_result_directory_created"] is False  # type: ignore[index]


def test_v4_freeze_matches_every_bound_component() -> None:
    module = _load_module("freeze_a092_v4_protocol", "scripts/freeze_a092_v4_protocol.py")
    record = module.build_freeze_record()
    assert record == _load_json("protocols/a092_v4/protocol_freeze.json")
    for component, expected in record["components"].items():
        assert canonical_file_sha256(ROOT / component) == expected


def test_v4_runner_promotes_matching_permission_mode(tmp_path: Path, monkeypatch) -> None:
    runner = _load_module("run_a092_claude_v4", "scripts/run_a092_claude_v4.py")
    work_root = tmp_path / "v4"
    prepared = work_root / "prepared" / "R01"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        kwargs["stdout"].write(json.dumps({
            "type": "system", "subtype": "init", "session_id": "s1",
            "model": "claude-opus-4-8", "claude_code_version": "2.1.207",
            "permissionMode": "bypassPermissions",
        }) + "\n")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner, "WORK_ROOT", work_root)
    monkeypatch.setattr(runner, "verify_v4_freeze", lambda: {})
    monkeypatch.setattr(runner, "run_process_tree", fake_run)
    assert runner.execute("R01") == 0
    metadata = _load_json_from(work_root / "runs" / "R01" / "runner_metadata.json")
    assert metadata["engine_valid"] is True


def test_v4_runner_rejects_permission_mode_drift(tmp_path: Path, monkeypatch) -> None:
    runner = _load_module("run_a092_claude_v4_drift", "scripts/run_a092_claude_v4.py")
    work_root = tmp_path / "v4"
    prepared = work_root / "prepared" / "R01"
    prepared.mkdir(parents=True)
    (prepared / "prompt_exact.md").write_text("prompt", encoding="utf-8")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        kwargs["stdout"].write(json.dumps({
            "type": "system", "subtype": "init", "session_id": "s1",
            "model": "claude-opus-4-8", "claude_code_version": "2.1.207",
            "permissionMode": "dontAsk",
        }) + "\n")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner, "WORK_ROOT", work_root)
    monkeypatch.setattr(runner, "verify_v4_freeze", lambda: {})
    monkeypatch.setattr(runner, "run_process_tree", fake_run)
    assert runner.execute("R01") == 1
    assert not (work_root / "runs" / "R01").exists()


def test_v4_audit_allows_own_path_and_rejects_other_run(tmp_path: Path) -> None:
    validator = _load_module(
        "validate_a092_formal_run_v4", "scripts/validate_a092_formal_run_v4.py"
    )
    run_dir = tmp_path / "a092_confirmatory_v4" / "runs" / "R01"
    run_dir.mkdir(parents=True)
    (run_dir / "runner_events.jsonl").write_text(
        "a092_confirmatory_v4/runs/R01/output\n"
        "a092_confirmatory_v4/runs/R02/output\n",
        encoding="utf-8",
    )
    (run_dir / "runner_metadata.json").write_text(
        json.dumps(
            {
                "protocol_id": "A092-CONFIRMATORY-V4",
                "execution_engine": "Claude Code",
                "cli_version_observed": "2.1.207",
                "model_observed": "claude-opus-4-8",
                "permission_mode_observed": "bypassPermissions",
                "engine_valid": True,
            }
        ),
        encoding="utf-8",
    )
    report = validator.audit_v4(run_dir)
    assert report["valid"] is False
    assert report["forbidden_reference_count"] == 1
    assert report["findings"][0]["match"].endswith("R02")


def _load_json_from(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
