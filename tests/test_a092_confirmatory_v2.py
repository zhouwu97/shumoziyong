from __future__ import annotations

import hashlib
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: str) -> object:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_confirmatory_v2_protocol_matches_schema_and_stays_pre_execution() -> None:
    protocol = _load_json("protocols/a092_v2/a092_confirmatory_v2.json")
    schema = _load_json("schemas/a092_confirmatory_v2.schema.json")
    Draft202012Validator(schema).validate(protocol)
    assert protocol["patch_status"] == "review_ready"  # type: ignore[index]
    assert protocol["execution_started"] is False  # type: ignore[index]
    assert protocol["external_validation"]["quantitative_claim_gate"] == "objective_passed_and_constraints_passed"  # type: ignore[index]
    assert protocol["external_validation"]["strong_optimality_gate"].endswith("optimality_evidence_passed")  # type: ignore[index]


def test_confirmatory_v2_freeze_hashes_every_bound_component() -> None:
    path = ROOT / "scripts" / "freeze_a092_v2_protocol.py"
    spec = spec_from_file_location("freeze_a092_v2_protocol", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    record = module.build_freeze_record()

    for component, expected in record["components"].items():
        actual = hashlib.sha256((ROOT / component).read_bytes()).hexdigest()
        assert actual == expected

    frozen = _load_json("protocols/a092_v2/protocol_freeze.json")
    assert frozen == record
