from __future__ import annotations

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from freeze_hash import canonical_file_sha256  # noqa: E402


def _load_json(path: str) -> object:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _load_runner_module():
    path = ROOT / "scripts" / "run_a092_claude_v3.py"
    spec = spec_from_file_location("run_a092_claude_v3", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_claude_version_parser_ignores_banner_suffix() -> None:
    runner = _load_runner_module()
    assert runner._cli_version("2.1.207 (Claude Code)\n") == "2.1.207"


def test_confirmatory_v3_protocol_is_frozen_for_claude_code() -> None:
    protocol = _load_json("protocols/a092_v3/a092_confirmatory_v3.json")
    schema = _load_json("schemas/a092_confirmatory_v3.schema.json")
    Draft202012Validator(schema).validate(protocol)
    assert protocol["supersedes"] == "A092-CONFIRMATORY-V2"  # type: ignore[index]
    assert protocol["execution_started"] is False  # type: ignore[index]
    assert protocol["execution_engine"]["cli"] == "Claude Code"  # type: ignore[index]
    assert protocol["execution_engine"]["model"] == "claude-opus-4-8"  # type: ignore[index]


def test_confirmatory_v3_freeze_hashes_every_bound_component() -> None:
    path = ROOT / "scripts" / "freeze_a092_v3_protocol.py"
    spec = spec_from_file_location("freeze_a092_v3_protocol", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    record = module.build_freeze_record()
    assert record == _load_json("protocols/a092_v3/protocol_freeze.json")
    for component, expected in record["components"].items():
        assert canonical_file_sha256(ROOT / component) == expected
