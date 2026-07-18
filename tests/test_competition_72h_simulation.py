from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from formal_result.hashing import file_sha256  # noqa: E402
import validate_competition_72h_simulation as simulation_module  # noqa: E402
from validate_competition_72h_simulation import (  # noqa: E402
    simulation_evidence_digest,
    validate_simulation,
)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = json.loads(
        (ROOT / "runtime_contracts/competition_72h_simulation_protocol_v1.json").read_text(
            encoding="utf-8"
        )
    )
    protocol_path = tmp_path / "runtime_contracts/competition_72h_simulation_protocol_v1.json"
    _write_json(protocol_path, protocol)
    registry = {
        "schema_version": "1.0.0",
        "registry_id": "competition_72h_simulation_authorities_v1",
        "status": "active",
        "identity_verification": "out_of_band_human_verification_required",
        "keys": [
            {
                "key_id": "simulation-observer",
                "pseudonym": "external-observer",
                "role": "simulation_observer",
                "human_identity_verified": True,
                "status": "active",
                "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
                "rsa_modulus_hex": "a" * 128,
                "rsa_exponent": 65537,
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
            }
        ],
    }
    registry_path = tmp_path / "policies/competition_72h_simulation_authorities_v1.json"
    _write_json(registry_path, registry)

    qualification = {"derived_lifecycle": "blind_review_passed"}
    qualification_path = tmp_path / "evidence/qualification_report_v3.json"
    _write_json(qualification_path, qualification)
    artifact_refs: dict[str, dict[str, str]] = {}
    for name in protocol["required_artifacts"]:
        path = tmp_path / "artifacts" / f"{name}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"fixture-{name}".encode())
        artifact_refs[name] = {
            "path": path.relative_to(tmp_path).as_posix(),
            "sha256": file_sha256(path),
        }

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    stages = []
    cursor = start
    for stage_id in protocol["required_stages"]:
        stage_completed = cursor + timedelta(hours=6)
        stages.append(
            {
                "stage_id": stage_id,
                "started_at": cursor.isoformat().replace("+00:00", "Z"),
                "completed_at": stage_completed.isoformat().replace("+00:00", "Z"),
                "human_minutes": 180,
                "ai_minutes": 120,
                "audit_minutes": 30,
                "completed": True,
            }
        )
        cursor = stage_completed
    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "simulation_id": "trusted-72h-fixture",
        "protocol_ref": {
            "path": protocol_path.relative_to(tmp_path).as_posix(),
            "sha256": file_sha256(protocol_path),
        },
        "authority_registry_ref": {
            "path": registry_path.relative_to(tmp_path).as_posix(),
            "sha256": file_sha256(registry_path),
        },
        "source_qualification_ref": {
            "path": qualification_path.relative_to(tmp_path).as_posix(),
            "sha256": file_sha256(qualification_path),
            "derived_lifecycle": "blind_review_passed",
        },
        "started_at": start.isoformat().replace("+00:00", "Z"),
        "completed_at": cursor.isoformat().replace("+00:00", "Z"),
        "official_problem_complete": True,
        "all_official_attachments_included": True,
        "stages": stages,
        "timing": {
            "active_work_minutes": 2400,
            "audit_process_minutes": 240,
            "human_revision_minutes": 360,
            "interruption_minutes": 240,
        },
        "artifacts": artifact_refs,
        "formal_validation_passed": True,
        "problem_validator_passed": True,
        "ai_recorder": {
            "provider": "fixture-provider",
            "model": "fixture-recorder",
            "model_version": "2026-08-01",
            "session_id": "fixture-session",
            "transcript_sha256": hashlib.sha256(b"transcript").hexdigest(),
            "started_at": "2026-08-01T00:00:00Z",
            "completed_at": "2026-08-03T00:30:00Z",
            "decision_authority": False,
        },
    }
    attestation = {
        "observer_key_id": "simulation-observer",
        "evidence_digest": simulation_evidence_digest(evidence),
        "continuous_simulation_confirmed": True,
        "all_stages_observed": True,
        "final_artifacts_opened_and_verified": True,
        "human_final_decision_confirmed": True,
        "ai_decision_authority": False,
        "signed_at": "2026-08-03T01:00:00Z",
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
        "signature": "fixture-signature",
    }
    evidence["observer_attestation"] = attestation
    return evidence, protocol, registry


def test_simulation_contracts_and_current_status_are_valid() -> None:
    pairs = [
        ("competition_72h_simulation_protocol.schema.json", "runtime_contracts/competition_72h_simulation_protocol_v1.json"),
        ("competition_72h_simulation_authority_registry.schema.json", "policies/competition_72h_simulation_authorities_v1.json"),
        ("competition_72h_simulation_status.schema.json", "capability_evidence/competition_production/simulation/status_v1.json"),
    ]
    for schema_name, instance_name in pairs:
        schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
        instance = json.loads((ROOT / instance_name).read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(instance)


def test_complete_simulation_passes_with_human_authority(
    tmp_path: Path, monkeypatch: Any
) -> None:
    evidence, protocol, registry = _fixture(tmp_path)
    monkeypatch.setattr(simulation_module, "_active_key", lambda *args, **kwargs: registry["keys"][0])
    monkeypatch.setattr(simulation_module, "_verify_rsa_signature", lambda *args, **kwargs: None)
    report = validate_simulation(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "competition_72h_simulation_passed"
    assert report["default_candidate_eligible"] is True
    assert report["elapsed_hours"] == 48
    assert report["human_attested"] is True
    assert report["ai_record_only"] is True


def test_simulation_over_72_hours_fails_closed(tmp_path: Path, monkeypatch: Any) -> None:
    evidence, protocol, registry = _fixture(tmp_path)
    evidence["completed_at"] = "2026-08-04T01:00:00Z"
    evidence["ai_recorder"]["completed_at"] = "2026-08-04T01:10:00Z"
    evidence["observer_attestation"]["signed_at"] = "2026-08-04T02:00:00Z"
    evidence["observer_attestation"]["evidence_digest"] = simulation_evidence_digest(evidence)
    monkeypatch.setattr(simulation_module, "_active_key", lambda *args, **kwargs: registry["keys"][0])
    monkeypatch.setattr(simulation_module, "_verify_rsa_signature", lambda *args, **kwargs: None)
    report = validate_simulation(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "failed"
    assert report["default_candidate_eligible"] is False
    assert "SIM_ELAPSED_TIME_OVER_72H" in report["fatal_codes"]
