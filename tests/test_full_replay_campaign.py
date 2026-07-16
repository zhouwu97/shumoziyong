from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_full_replay_campaign as campaign  # noqa: E402
from export_runtime_pack import build_manifest, build_pack  # noqa: E402


PROBLEMS = {
    "2016-C": "2016_C",
    "2023-B": "2023_B",
    "2024-B": "2024_B",
    "2024-C": "2024_C",
    "2024-D": "2024_D",
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _material(workspace: Path, problem_id: str, material_key: str) -> tuple[Path, str]:
    root = workspace / "official_materials" / material_key
    problem = root / "problem" / "problem.txt"
    problem.parent.mkdir(parents=True)
    problem.write_text(f"official fixture {problem_id}", encoding="utf-8")
    manifest = {
        "manifest_version": "1.0.0",
        "problem_id": problem_id,
        "material_root": ".",
        "source": {"kind": "official", "reference": "https://example.test/official"},
        "contains_answer_or_solution": False,
        "categories": {
            "problem": {"required": True, "files": [{"path": "problem/problem.txt", "sha256": _sha(problem)}]},
            "attachments": {"required": False, "files": []},
            "templates": {"required": False, "files": []},
        },
    }
    manifest_path = root / "material_manifest.json"
    _write_json(manifest_path, manifest)
    return root, _sha(manifest_path)


def _adapter(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": "competition_production_adapter_report_v1",
        "adapter_id": "plugin_competition_production_v1",
        "run_id": run_id,
        "source_commit": "be9c59c1aaa13c3dcb74452ea5cae11dada27589",
        "status": "advisory_only",
        "authority": {
            "generate_results": False,
            "modify_paper": False,
            "decide_gate_pass": False,
            "advance_stage": False,
        },
        "applications": [],
    }


def _make_run(workspace: Path, problem_id: str, material_key: str) -> dict[str, str]:
    run_id = f"pr7-{material_key.lower()}-20260717"
    run_relative = f"runs/{run_id}"
    run_root = workspace / run_relative
    run_root.mkdir(parents=True)
    _material_root, material_sha = _material(workspace, problem_id, material_key)
    pack = build_pack("engineering_optimization", "full_replay")
    pack_manifest = build_manifest("engineering_optimization", "full_replay", pack)
    (run_root / "runtime_pack.md").write_bytes(pack.encode("utf-8"))
    _write_json(run_root / "runtime_pack.manifest.json", pack_manifest)
    run_manifest = {
        "manifest_version": "2.0.0",
        "run_id": run_id,
        "workflow": "full_replay",
        "created_at": "2026-07-17T08:00:00+08:00",
        "problem_id": problem_id,
        "profile": "engineering_optimization",
        "runtime_version": pack_manifest["runtime_version"],
        "runtime_pack_sha256": pack_manifest["runtime_pack_sha256"],
        "material_manifest_sha256": material_sha,
        "material_status": "ready",
        "competition_production_contract_version": "1.0.0",
    }
    _write_json(run_root / "run_manifest.json", run_manifest)
    _write_json(run_root / "competition_production_adapter_report.json", _adapter(run_id))
    _write_json(
        run_root / "full_replay_run_record.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "competition_full_replay_run_record_v1",
            "run_id": run_id,
            "problem_id": problem_id,
            "operator_id": "fixture-operator",
            "source_control_commit": "c7f15a3da6a5c61182ec1d3a15e78664c60e2d98",
            "started_at": "2026-07-17T08:00:00+08:00",
            "completed_at": "2026-07-17T08:02:00+08:00",
            "runtime_seconds": 120,
            "manual_interventions": [],
            "answer_leakage_detected": False,
            "historical_assets_modified": False,
            "declared_complete": True,
        },
    )
    _write_json(
        run_root / "model_route_v3.json",
        {
            "schema_version": "3.0.0",
            "artifact_type": "model_route_v3",
            "run_id": run_id,
            "problem_id": problem_id,
            "profile": "engineering_optimization",
            "runtime_version": pack_manifest["runtime_version"],
            "runtime_pack_sha256": pack_manifest["runtime_pack_sha256"],
            "lifecycle": "review_ready",
            "subproblems": [{"subproblem_id": "Q1"}],
            "human_decisions_required": ["fixture approval"],
        },
    )
    return {
        "problem_id": problem_id,
        "run_id": run_id,
        "run_path": run_relative,
        "material_root": f"official_materials/{material_key}",
    }


def _campaign_manifest(workspace: Path) -> Path:
    manifest = {
        "schema_version": "1.0.0",
        "campaign_id": "competition-production-pr7-20260717",
        "contract": {
            "path": "runtime_contracts/competition_full_replay_campaign_v1.json",
            "sha256": _sha(campaign.CONTRACT_PATH),
        },
        "runs": [_make_run(workspace, problem_id, key) for problem_id, key in PROBLEMS.items()],
    }
    path = workspace / "campaign_manifest.json"
    _write_json(path, manifest)
    return path


def _stub_deep_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(campaign, "validate_artifact", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        campaign,
        "_validate_subproblem",
        lambda *_args, **_kwargs: (False, False, []),
    )
    monkeypatch.setattr(campaign, "_validate_paper", lambda *_args, **_kwargs: [])


def test_campaign_contract_freezes_problem_set_and_lifecycle() -> None:
    contract = json.loads(campaign.CONTRACT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas" / "competition_full_replay_campaign.schema.json").read_text(encoding="utf-8")
    )
    assert not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(contract))
    assert {item["problem_id"] for item in contract["required_problems"]} == set(PROBLEMS)
    assert contract["current_lifecycle"] == "review_ready"
    assert contract["target_lifecycle"] == "full_replay_passed"
    assert contract["new_problem_default_enabled"] is False


def test_five_verified_runs_derive_full_replay_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_deep_validators(monkeypatch)
    manifest_path = _campaign_manifest(tmp_path)
    report = campaign.evaluate_campaign(manifest_path, tmp_path, tmp_path)
    assert report["status"] == "passed"
    assert report["derived_lifecycle"] == "full_replay_passed"
    assert report["metrics"] == {
        "problem_count": 5,
        "passed_problem_count": 5,
        "subproblem_count": 5,
        "runtime_seconds": 600.0,
        "manual_intervention_count": 0,
        "baseline_win_rate": 0.0,
        "fatal_error_rate": 0.0,
        "submission_admission_rate": 1.0,
    }
    assert report["new_problem_default_enabled"] is False


def test_missing_run_keeps_campaign_review_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_deep_validators(monkeypatch)
    manifest_path = _campaign_manifest(tmp_path)
    missing = tmp_path / "runs" / "pr7-2024_d-20260717"
    for path in sorted(missing.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    missing.rmdir()
    report = campaign.evaluate_campaign(manifest_path, tmp_path, tmp_path)
    assert report["status"] == "failed"
    assert report["derived_lifecycle"] == "review_ready"
    failed = next(item for item in report["runs"] if item["problem_id"] == "2024-D")
    assert failed["failure_codes"] == ["FRV_RUN_MISSING"]


def test_duplicate_run_id_is_rejected_before_evidence_validation(tmp_path: Path) -> None:
    manifest_path = _campaign_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runs"][1]["run_id"] = manifest["runs"][0]["run_id"]
    _write_json(manifest_path, manifest)
    with pytest.raises(campaign.FullReplayCampaignError, match="Run ID 必须唯一"):
        campaign.evaluate_campaign(manifest_path, tmp_path, tmp_path)


def test_runtime_pack_without_adapter_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_deep_validators(monkeypatch)
    manifest_path = _campaign_manifest(tmp_path)
    run_root = tmp_path / "runs" / "pr7-2016_c-20260717"
    runtime_path = run_root / "runtime_pack.manifest.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["plugins"] = [
        item for item in runtime["plugins"] if item["path"] != campaign.PLUGIN_PATH
    ]
    _write_json(runtime_path, runtime)
    report = campaign.evaluate_campaign(manifest_path, tmp_path, tmp_path)
    failed = next(item for item in report["runs"] if item["problem_id"] == "2016-C")
    assert failed["failure_codes"] == ["FRV_ADAPTER_NOT_COMPILED"]
    assert report["derived_lifecycle"] == "review_ready"


def test_execution_provenance_rejects_source_commit_drift(tmp_path: Path) -> None:
    child_root = tmp_path / "route_runs" / "Q1" / "R-BASELINE"
    attestation_path = child_root / "sandboxie_run_execution_attestation.json"
    fixture_path = ROOT / "tests" / "fixtures" / "m3a_verified_run" / attestation_path.name
    attestation = json.loads(fixture_path.read_text(encoding="utf-8"))
    _write_json(attestation_path, attestation)
    formal_results = [
        {
            "child_run_id": attestation["run_id"],
            "formal_result_id": attestation["formal_result_id"],
            "envelope_path": (
                "route_runs/Q1/R-BASELINE/formal_results/"
                f"{attestation['formal_result_id']}/formal_result_envelope.json"
            ),
        }
    ] * 3
    record = {
        "source_control_commit": "a" * 40,
        "started_at": "2026-07-13T09:00:00+08:00",
        "completed_at": "2026-07-13T10:00:00+08:00",
    }
    with pytest.raises(campaign.FullReplayCampaignError) as caught:
        campaign._validate_execution_provenance(tmp_path, formal_results, record)
    assert caught.value.code == "FRV_SOURCE_COMMIT"
