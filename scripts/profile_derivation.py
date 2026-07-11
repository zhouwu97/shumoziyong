"""从 Runtime Profile 引用的证据现场派生只读状态报告。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from evidence_validation import validate_profile_record


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policies" / "promotion_policy.json"


def _load_policy() -> dict[str, Any]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):  # pragma: no cover - 仓库 Schema 会先阻断
        raise ValueError("promotion_policy.json 必须是 JSON 对象")
    return value


def derive_profile_report(
    profile: dict[str, Any],
    patches: list[dict[str, Any]],
    *,
    root: Path = ROOT,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """深验证唯一证据引用并派生来源、回归和比赛状态。"""
    active_policy = policy if policy is not None else _load_policy()
    records = profile.get("validation_records", [])
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_evidence_keys: set[str] = set()
    valid_records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, str]] = []

    for raw_record in records:
        if not isinstance(raw_record, Mapping):
            invalid_records.append({"record_id": "", "error": "record_not_object"})
            continue
        record = dict(raw_record)
        record_id = str(record.get("record_id", ""))
        path_text = str(record.get("path", ""))
        error: str | None = None
        if record_id in seen_ids:
            error = "duplicate_record_id"
        elif path_text in seen_paths:
            error = "duplicate_path"
        seen_ids.add(record_id)
        seen_paths.add(path_text)

        outcome = None
        if error is None:
            outcome = validate_profile_record(
                record,
                str(profile.get("profile_id", "")),
                patches,
                active_policy,
                root=root,
            )
            if not outcome.valid:
                error = "evidence_validation_failed: " + "; ".join(outcome.errors)

        evidence_key = (
            str(outcome.identity.get("evidence_key"))
            if outcome is not None and outcome.valid
            else None
        )
        if error is None and evidence_key is not None:
            if evidence_key in seen_evidence_keys:
                error = "duplicate_evidence_identity"
            else:
                seen_evidence_keys.add(evidence_key)

        if error is None and outcome is not None:
            enriched = dict(record)
            enriched["derived_control_type"] = outcome.identity.get("control_type")
            enriched["evidence_key"] = evidence_key
            valid_records.append(enriched)
        else:
            invalid_records.append({"record_id": record_id, "error": error or "invalid"})

    controls = {
        record.get("derived_control_type")
        for record in valid_records
        if record.get("kind") == "control_review"
    }
    full_runs = [record for record in valid_records if record.get("kind") == "full_run"]
    competitions = [
        record for record in valid_records if record.get("kind") == "competition"
    ]
    regression_complete = controls == {"positive", "boundary", "negative"} and bool(
        full_runs
    )
    competition_complete = regression_complete and bool(competitions)
    competition_errors: list[str] = []
    if competitions:
        stable_requirements = active_policy.get(
            "runtime_profile_stable_requirements", {}
        )
        minimum_full_runs = stable_requirements.get("minimum_gate_0_5", 1)
        minimum_competitions = stable_requirements.get(
            "minimum_competition_validation_records", 1
        )
        minimum_negative_controls = (
            active_policy.get("status_rules", {})
            .get("competition_evidenced", {})
            .get("repetition", {})
            .get("min_negative_control_runs", 1)
        )
        negative_controls = [
            record
            for record in valid_records
            if record.get("kind") == "control_review"
            and record.get("derived_control_type") == "negative"
        ]
        if len(full_runs) < minimum_full_runs:
            competition_errors.append(
                f"完整 Gate 0-5 运行至少需要 {minimum_full_runs} 条，当前 {len(full_runs)} 条"
            )
        if len(competitions) < minimum_competitions:
            competition_errors.append(
                f"比赛验证至少需要 {minimum_competitions} 条，当前 {len(competitions)} 条"
            )
        if len(negative_controls) < minimum_negative_controls:
            competition_errors.append(
                f"独立负控至少需要 {minimum_negative_controls} 组，"
                f"当前 {len(negative_controls)} 组"
            )
        if stable_requirements.get("require_non_empty_validation_evidence", True) and not records:
            competition_errors.append("competition Profile validation_records 不能为空")
        if stable_requirements.get("require_empty_known_failures", True) and profile.get(
            "known_failures"
        ):
            competition_errors.append("competition Profile known_failures 必须为空")
        if competition_errors:
            competition_complete = False
            invalid_records.append(
                {
                    "record_id": "<profile>",
                    "error": "competition_requirements_failed: "
                    + "; ".join(competition_errors),
                }
            )

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
            "errors": competition_errors,
        },
        "invalid_records": invalid_records,
    }


def load_and_derive(profile_path: Path) -> dict[str, Any]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    patches = json.loads(
        (ROOT / "prompt_patches" / "patch_index.json").read_text(encoding="utf-8")
    )
    return derive_profile_report(profile, patches)
