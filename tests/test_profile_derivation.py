from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from profile_derivation import derive_profile_report  # noqa: E402
from validate_repository import RepositoryValidator  # noqa: E402


def _record(root: Path, record_id: str, kind: str, control_type: str | None = None) -> dict[str, str]:
    path = root / f"{record_id}.json"
    path.write_text(json.dumps({"record_id": record_id}), encoding="utf-8")
    record = {
        "record_id": record_id,
        "kind": kind,
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    if control_type is not None:
        record["control_type"] = control_type
    return record


def test_profile_status_is_recomputed_from_unique_evidence(tmp_path: Path) -> None:
    records = [
        _record(tmp_path, "positive", "control_review", "positive"),
        _record(tmp_path, "boundary", "control_review", "boundary"),
        _record(tmp_path, "negative", "control_review", "negative"),
        _record(tmp_path, "full", "full_run"),
    ]
    profile = {
        "profile_id": "engineering_optimization",
        "plugin_version": "1.0.0",
        "validation_records": records,
    }

    report = derive_profile_report(profile, [], root=tmp_path)

    assert report["computed_maturity"] == "regression_verified"
    assert report["regression_status"]["complete"] is True
    assert report["competition_evidence"]["complete"] is False


def test_competition_record_advances_only_after_regression(tmp_path: Path) -> None:
    profile = {
        "profile_id": "engineering_optimization",
        "plugin_version": "1.0.0",
        "validation_records": [_record(tmp_path, "competition", "competition")],
    }
    assert derive_profile_report(profile, [], root=tmp_path)["computed_maturity"] == "assembled"


def test_duplicate_evidence_path_is_not_counted_twice(tmp_path: Path) -> None:
    record = _record(tmp_path, "positive", "control_review", "positive")
    duplicate = {**record, "record_id": "positive-copy"}
    profile = {
        "profile_id": "engineering_optimization",
        "plugin_version": "1.0.0",
        "validation_records": [record, duplicate],
    }

    report = derive_profile_report(profile, [], root=tmp_path)

    assert report["regression_status"]["control_types"] == ["positive"]
    assert report["invalid_records"] == [
        {"record_id": "positive-copy", "error": "duplicate_path"}
    ]


def test_runtime_profile_schema_rejects_old_manual_counters() -> None:
    profile = json.loads(
        (ROOT / "runtime_profiles" / "engineering_optimization.json").read_text(
            encoding="utf-8"
        )
    )
    profile["validation"] = {"gate_0_5": 99, "negative_control": 99}
    profile["competition_verified"] = True

    validator = RepositoryValidator()
    assert not validator.validate_schema(
        profile, "runtime_profile.schema.json", "legacy profile counters"
    )


def test_old_state_names_are_rejected() -> None:
    validator = RepositoryValidator()
    profile = json.loads(
        (ROOT / "runtime_profiles" / "general.json").read_text(encoding="utf-8")
    )
    profile["maturity"] = "candidate"
    assert not validator.validate_schema(profile, "runtime_profile.schema.json", "old profile state")

    patches = json.loads(
        (ROOT / "prompt_patches" / "patch_index.json").read_text(encoding="utf-8")
    )
    patches[0]["status"] = "verified_candidate"
    assert not validator.validate_schema(patches, "patch_index.schema.json", "old patch state")
