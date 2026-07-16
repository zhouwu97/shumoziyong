from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_runtime_pack import PROFILE_FILES, RUNTIME_CONTRACTS, resolve_pack_files  # noqa: E402
from upstream.validate_requirements import (  # noqa: E402
    MAPPING_FILE,
    REGISTRY_FILES,
    validate_requirement_bundle,
)


REQUIREMENTS_ROOT = ROOT / "runtime_contracts" / "upstream_requirements"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_requirement_source_and_mapping_closure() -> None:
    assert validate_requirement_bundle(ROOT) == []

    requirement_ids: set[str] = set()
    strengths: set[str] = set()
    for filename in REGISTRY_FILES:
        registry = _load_json(REQUIREMENTS_ROOT / filename)
        requirements = registry["requirements"]
        assert isinstance(requirements, list)
        for requirement in requirements:
            assert isinstance(requirement, dict)
            requirement_ids.add(str(requirement["requirement_id"]))
            strengths.add(str(requirement["strength"]))

    assert len(requirement_ids) == 38
    assert strengths == {"blocking", "advisory"}

    mapping_registry = _load_json(REQUIREMENTS_ROOT / MAPPING_FILE)
    mappings = mapping_registry["mappings"]
    assert isinstance(mappings, list)
    assert len(mappings) == 13


def test_adapter_is_not_active_in_any_runtime_profile_yet() -> None:
    adapter_path = "prompt_plugins/plugin_competition_production_v1.md"
    for profile in PROFILE_FILES:
        for workflow_context in RUNTIME_CONTRACTS:
            files = resolve_pack_files(profile, workflow_context)
            assert adapter_path not in files
            assert not any(path.startswith("runtime_contracts/upstream_requirements/") for path in files)


def test_adapter_report_contract_is_advisory_only() -> None:
    schema = _load_json(ROOT / "schemas" / "competition_production_adapter_report.schema.json")
    report = {
        "schema_version": "competition_production_adapter_report_v1",
        "adapter_id": "plugin_competition_production_v1",
        "run_id": "fixture-run",
        "source_commit": "be9c59c1aaa13c3dcb74452ea5cae11dada27589",
        "status": "advisory_only",
        "authority": {
            "generate_results": False,
            "modify_paper": False,
            "decide_gate_pass": False,
            "advance_stage": False,
        },
        "applications": [
            {
                "requirement_id": "PROD-002",
                "mapping_id": "MAP-PROD-ROUTE",
                "strength": "blocking",
                "applicability": "unknown",
                "target_contracts": ["schemas/execution_spec.schema.json"],
                "evidence_requests": ["全部硬约束与可行解证明"],
                "diagnostics": ["当前证据不足，交由 Gate 2 独立裁决"],
                "rationale": "Adapter 不推断未提供的执行证据",
            }
        ],
    }
    validator = Draft202012Validator(schema)

    assert list(validator.iter_errors(report)) == []

    unauthorized = copy.deepcopy(report)
    authority = unauthorized["authority"]
    assert isinstance(authority, dict)
    authority["decide_gate_pass"] = True
    assert list(validator.iter_errors(unauthorized))


def test_runtime_adapter_contains_no_source_asset_or_upstream_controller_text() -> None:
    plugin = (ROOT / "prompt_plugins" / "plugin_competition_production_v1.md").read_text(
        encoding="utf-8"
    )

    for forbidden in (".vendor/", "1start-mathmodel", "allowed-tools:", "Bash(*)", "WebSearch"):
        assert forbidden not in plugin
    assert "现有 Runtime Profile、Gate 0–5、Collector、独立 Validator 和 Formal Result 始终是真源" in plugin
