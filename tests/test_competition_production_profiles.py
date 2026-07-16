from __future__ import annotations

import hashlib
import json
import sys
from argparse import Namespace
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_runtime_pack import (  # noqa: E402
    COMPETITION_PRODUCTION_FILES_AFTER_GATE,
    COMPETITION_PRODUCTION_PROFILES,
    build_manifest,
    build_pack,
    resolve_pack_files,
)
from run_workflow import (  # noqa: E402
    competition_production_enabled,
    create_full_replay_run,
    create_new_problem_run,
)


NEW_PROBLEM_SHA256 = {
    "general": "9234ef92c49842b7086fe2af1224377ba2eb9fe5a249ac452e4aed1776ff7293",
    "engineering_optimization": "3904b3572a87ac4437535df8684c006fea7333a89c68d892c0c0c8e2854ae864",
    "evaluation": "e2e891e9d6e36e28c9e1f1b2ebac872cccfd0dd609380e9cfab4cd47c45d4f49",
    "prediction": "bb7afd2b4cc03be2d1a0724c63554bafa70f902f571fa08a2312696571aa478c",
}


def test_capability_registry_is_full_replay_passed_but_not_default() -> None:
    capability = json.loads(
        (ROOT / "runtime_contracts" / "competition_production_capability_v1.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (ROOT / "schemas" / "competition_production_capability.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not list(Draft202012Validator(schema).iter_errors(capability))
    assert capability["lifecycle"] == "full_replay_passed"
    assert capability["activation_contexts"] == ["full_replay"]
    assert capability["new_problem_default_enabled"] is False
    evidence = capability["promotion_evidence"]
    report_path = ROOT / evidence["path"]
    report_text = report_path.read_text(encoding="utf-8")
    assert hashlib.sha256(report_text.encode("utf-8")).hexdigest() == evidence["sha256"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["derived_lifecycle"] == "full_replay_passed"


def test_full_replay_compiles_v3_chain_in_gate_order_for_four_profiles() -> None:
    flattened = {
        path for paths in COMPETITION_PRODUCTION_FILES_AFTER_GATE.values() for path in paths
    }
    for profile in sorted(COMPETITION_PRODUCTION_PROFILES):
        files = resolve_pack_files(profile, "full_replay")
        assert flattened.issubset(files)
        assert files.index("checklists/gate_0_material_diagnosis.md") < files.index(
            "prompt_plugins/plugin_competition_production_v1.md"
        ) < files.index("checklists/gate_1_model_route.md")
        assert files.index("schemas/model_route_v3.schema.json") < files.index(
            "checklists/gate_1_model_route.md"
        )
        assert files.index("schemas/route_execution_report.schema.json") < files.index(
            "checklists/gate_2_code_plan.md"
        )
        assert files.index("schemas/competition_gate3_decision.schema.json") < files.index(
            "checklists/gate_3_results_confirmation.md"
        )
        assert files.index("runtime_contracts/score_v3_policy_v1.json") < files.index(
            "checklists/gate_4_paper_confirmation.md"
        )

        pack = build_pack(profile, "full_replay")
        assert "competition_production_v1" in pack
        assert "model_route_v3" in pack
        assert "score_v3_policy_v1" in pack
        assert ".vendor/mathmodelagent" not in pack
        manifest = build_manifest(profile, "full_replay", pack)
        manifest_paths = {
            item["path"]
            for key in ("plugins", "other_files")
            for item in manifest[key]
        }
        assert flattened.issubset(manifest_paths)


def test_new_problem_and_prompt_regression_do_not_compile_non_default_capability() -> None:
    capability_path = "runtime_contracts/competition_production_capability_v1.json"
    adapter_path = "prompt_plugins/plugin_competition_production_v1.md"
    for profile, expected_sha in NEW_PROBLEM_SHA256.items():
        new_files = resolve_pack_files(profile, "new_problem")
        regression_files = resolve_pack_files(profile, "prompt_regression")
        assert capability_path not in new_files
        assert adapter_path not in new_files
        assert capability_path not in regression_files
        assert adapter_path not in regression_files
        actual = hashlib.sha256(build_pack(profile, "new_problem").encode()).hexdigest()
        assert actual == expected_sha


def test_workflow_marker_is_derived_and_rejects_context_spoofing() -> None:
    assert competition_production_enabled(
        {
            "workflow": "full_replay",
            "profile": "general",
            "competition_production_contract_version": "1.0.0",
        }
    )
    assert not competition_production_enabled(
        {"workflow": "new_problem", "profile": "general"}
    )
    try:
        competition_production_enabled(
            {
                "workflow": "new_problem",
                "profile": "general",
                "competition_production_contract_version": "1.0.0",
            }
        )
    except ValueError as exc:
        assert "只允许用于 full_replay" in str(exc)
    else:
        raise AssertionError("new_problem 不得伪装启用 review_ready 能力")


def test_run_initialization_marks_only_explicit_full_replay(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"competition production profile fixture"
    (materials / "problem.pdf").write_bytes(problem)
    (materials / "material_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "1.0.0",
                "problem_id": "2024-C",
                "material_root": ".",
                "source": {"kind": "official", "reference": "https://example.com"},
                "contains_answer_or_solution": False,
                "categories": {
                    "problem": {
                        "required": True,
                        "files": [
                            {
                                "path": "problem.pdf",
                                "sha256": hashlib.sha256(problem).hexdigest(),
                            }
                        ],
                    },
                    "attachments": {"required": False, "files": []},
                    "templates": {"required": False, "files": []},
                },
            }
        ),
        encoding="utf-8",
    )
    common = {
        "output_root": str(tmp_path / "runs"),
        "problem": "2024-C",
        "profile": "general",
        "gates": "0-5",
        "materials": str(materials),
        "candidate_patch": [],
        "exclude_patch": [],
        "material_file": [],
        "promotion_evidence": False,
        "experiment_group_id": None,
        "experiment_role": None,
        "target_patch": None,
        "mode": "standard",
    }

    replay_dir, replay_ready = create_full_replay_run(
        Namespace(**common, run_id="review_ready_replay", workflow="full_replay")
    )
    new_dir, new_ready = create_new_problem_run(
        Namespace(**common, run_id="default_new_problem", workflow="new_problem")
    )
    replay_manifest = json.loads(
        (replay_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    new_manifest = json.loads((new_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert replay_ready and new_ready
    assert replay_manifest["competition_production_contract_version"] == "1.0.0"
    assert competition_production_enabled(replay_manifest)
    assert "competition_production_contract_version" not in new_manifest
    assert not competition_production_enabled(new_manifest)
