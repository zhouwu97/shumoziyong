"""从 Runtime Profile 引用的证据现场派生只读状态报告。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def derive_profile_report(
    profile: dict[str, Any],
    patches: list[dict[str, Any]],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """验证唯一证据引用并派生来源、回归和比赛状态。"""
    records = profile.get("validation_records", [])
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_evidence_keys: set[str] = set()
    valid_records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, str]] = []
    for record in records:
        record_id = str(record.get("record_id", ""))
        path_text = str(record.get("path", ""))
        error: str | None = None
        if record_id in seen_ids:
            error = "duplicate_record_id"
        elif path_text in seen_paths:
            error = "duplicate_path"
        seen_ids.add(record_id)
        seen_paths.add(path_text)
        path = (root / path_text).resolve()
        if error is None and not path.is_relative_to(root.resolve()):
            error = "path_outside_repository"
        if error is None and not path.is_file():
            error = "missing_file"
        if error is None:
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_sha != record.get("sha256"):
                error = "sha256_mismatch"
        evidence: dict[str, Any] | None = None
        if error is None:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                error = "invalid_json"
            else:
                if not isinstance(loaded, dict):
                    error = "evidence_not_object"
                else:
                    evidence = loaded

        evidence_key: str | None = None
        actual_control_type: str | None = None
        kind = record.get("kind")
        if error is None and evidence is not None:
            if kind == "control_review":
                group_id = evidence.get("experiment_group_id")
                actual_control_type = evidence.get("control_type")
                if not isinstance(group_id, str) or not group_id.strip():
                    error = "missing_experiment_group_id"
                elif actual_control_type not in {"positive", "boundary", "negative"}:
                    error = "invalid_control_type"
                elif record.get("control_type") != actual_control_type:
                    error = "control_type_mismatch"
                elif evidence.get("final_conclusion") != "pass":
                    error = "control_not_passed"
                else:
                    evidence_key = f"experiment_group:{group_id}"
            elif kind == "full_run":
                run_id = evidence.get("run_id")
                if evidence.get("seal_version") != "1.0.0":
                    error = "full_run_not_sealed"
                elif not isinstance(run_id, str) or not run_id.strip():
                    error = "missing_run_id"
                else:
                    sealed_files = {
                        "run_manifest_sha256": path.parent / "run_manifest.json",
                        "transitions_sha256": path.parent / "transitions.jsonl",
                        "evidence_manifest_sha256": path.parent
                        / "run_evidence_manifest.json",
                    }
                    for field, sealed_path in sealed_files.items():
                        if not sealed_path.is_file() or evidence.get(field) != hashlib.sha256(
                            sealed_path.read_bytes()
                        ).hexdigest():
                            error = "full_run_seal_invalid"
                            break
                    if error is None:
                        evidence_key = f"full_run:{run_id}"
            elif kind == "competition":
                run_id = evidence.get("run_id")
                result = evidence.get("result", evidence.get("final_result"))
                if not isinstance(run_id, str) or not run_id.strip():
                    error = "missing_run_id"
                elif result != "pass":
                    error = "competition_not_passed"
                else:
                    evidence_key = f"competition:{run_id}"
            else:
                error = "unknown_kind"

        if error is None and evidence_key is not None:
            if evidence_key in seen_evidence_keys:
                error = "duplicate_evidence_identity"
            else:
                seen_evidence_keys.add(evidence_key)

        if error is None:
            enriched = dict(record)
            enriched["derived_control_type"] = actual_control_type
            enriched["evidence_key"] = evidence_key
            valid_records.append(enriched)
        else:
            invalid_records.append({"record_id": record_id, "error": error})

    controls = {
        record.get("derived_control_type")
        for record in valid_records
        if record.get("kind") == "control_review"
    }
    full_runs = [record for record in valid_records if record.get("kind") == "full_run"]
    competitions = [record for record in valid_records if record.get("kind") == "competition"]
    regression_complete = controls == {"positive", "boundary", "negative"} and bool(full_runs)
    competition_complete = regression_complete and bool(competitions)

    deprecation = profile.get("deprecation")
    if isinstance(deprecation, dict) and deprecation.get("reason"):
        computed_maturity = "deprecated"
    elif competition_complete:
        computed_maturity = "competition_evidenced"
    elif regression_complete:
        computed_maturity = "regression_verified"
    elif profile.get("plugin_version") is not None or profile.get("profile_id") == "general":
        computed_maturity = "assembled"
    else:
        computed_maturity = "draft"

    source_patches = [
        {
            "patch_id": patch.get("patch_id"),
            "status": patch.get("status"),
            "knowledge_card": patch.get("source", {}).get("knowledge_card"),
        }
        for patch in patches
        if profile.get("profile_id") in patch.get("runtime_profiles", [])
    ]
    return {
        "profile_id": profile.get("profile_id"),
        "computed_maturity": computed_maturity,
        "source_provenance": {"patches": source_patches},
        "regression_status": {
            "control_types": sorted(item for item in controls if isinstance(item, str)),
            "full_run_count": len(full_runs),
            "complete": regression_complete,
        },
        "competition_evidence": {
            "record_count": len(competitions),
            "complete": competition_complete,
        },
        "invalid_records": invalid_records,
    }


def load_and_derive(profile_path: Path) -> dict[str, Any]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    patches = json.loads((ROOT / "prompt_patches" / "patch_index.json").read_text(encoding="utf-8"))
    return derive_profile_report(profile, patches)
