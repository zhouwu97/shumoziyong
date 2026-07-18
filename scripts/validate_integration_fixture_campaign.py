"""复算五题简化集成 fixture，但禁止据此宣称完整旧题回放。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from competition_route_runtime import EVIDENCE_FILENAMES, evaluate_competition_gate3
from paper.gate4_candidate import verify_candidate_manifest
from route_contract_dispatch import validate_artifact
from score_v3 import build_score_v3
from verify_materials import verify_materials


CONTRACT_PATH = ROOT / "runtime_contracts" / "competition_integration_fixture_campaign_v1.json"
PLUGIN_PATH = "prompt_plugins/plugin_competition_production_v1.md"
ALLOWED_PROFILES = {"general", "engineering_optimization", "evaluation", "prediction"}


class FullReplayCampaignError(ValueError):
    """Campaign 输入或单题证据不满足受控回放合同。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FullReplayCampaignError("FRV_JSON_INVALID", f"{label} 无法读取：{exc}") from exc
    if not isinstance(value, dict):
        raise FullReplayCampaignError("FRV_JSON_INVALID", f"{label} 顶层必须是对象")
    return value


def _validate_schema(value: Mapping[str, Any], schema_name: str, label: str) -> None:
    schema = _load_object(ROOT / "schemas" / schema_name, f"Schema {schema_name}")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise FullReplayCampaignError(
            "FRV_SCHEMA_INVALID", f"{label} 不符合 Schema：{location}: {error.message}"
        )


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise FullReplayCampaignError(code, message)


def _safe_path(root: Path, relative: str, label: str) -> Path:
    pure = PurePosixPath(relative)
    _require(
        not pure.is_absolute() and ".." not in pure.parts and "\\" not in relative and ":" not in relative,
        "FRV_PATH_UNSAFE",
        f"{label} 必须是安全 POSIX 相对路径",
    )
    candidate = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor /= part
        _require(not cursor.is_symlink(), "FRV_PATH_UNSAFE", f"{label} 禁止符号链接")
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise FullReplayCampaignError("FRV_PATH_UNSAFE", f"{label} 越出允许根目录") from exc
    return candidate


def _evidence_ref(run_root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(run_root).as_posix(), "sha256": _sha256(path)}


def _parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FullReplayCampaignError("FRV_TIME_INVALID", f"{label} 不是合法时间") from exc
    _require(parsed.tzinfo is not None, "FRV_TIME_INVALID", f"{label} 必须含时区")
    return parsed


def _validate_runtime_pack(
    run_root: Path,
    run_manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    pack_path = run_root / "runtime_pack.md"
    manifest_path = run_root / "runtime_pack.manifest.json"
    _require(pack_path.is_file(), "FRV_RUNTIME_PACK_MISSING", "缺少 runtime_pack.md")
    runtime = _load_object(manifest_path, "runtime_pack.manifest.json")
    _validate_schema(runtime, "runtime_pack_manifest.schema.json", "runtime_pack.manifest.json")
    _require(runtime["workflow_context"] == "full_replay", "FRV_CONTEXT_INVALID", "Runtime Pack 不是 full_replay")
    _require(runtime["profile"] == run_manifest.get("profile"), "FRV_IDENTITY_MISMATCH", "Runtime Pack Profile 不一致")
    _require(runtime["runtime_version"] == run_manifest.get("runtime_version"), "FRV_IDENTITY_MISMATCH", "Runtime Pack 版本不一致")
    actual_pack_sha = _sha256(pack_path)
    _require(actual_pack_sha == runtime["runtime_pack_sha256"], "FRV_RUNTIME_PACK_HASH", "Runtime Pack 正文哈希不一致")
    _require(actual_pack_sha == run_manifest.get("runtime_pack_sha256"), "FRV_IDENTITY_MISMATCH", "Run 与 Runtime Pack 哈希不一致")

    expected_plugin = contract["required_runtime_plugin"]
    records = [
        item
        for key in ("plugins", "other_files")
        for item in runtime[key]
        if item.get("path") == PLUGIN_PATH
    ]
    _require(len(records) == 1, "FRV_ADAPTER_NOT_COMPILED", "Runtime Pack 未唯一编译 Competition Production Adapter")
    _require(records[0] == expected_plugin, "FRV_ADAPTER_HASH", "Runtime Pack Adapter 哈希不符合 Campaign 合同")
    _require(_sha256(ROOT / PLUGIN_PATH) == expected_plugin["sha256"], "FRV_ADAPTER_HASH", "仓库 Adapter 已漂移")
    return runtime, [_evidence_ref(run_root, pack_path), _evidence_ref(run_root, manifest_path)]


def _validate_materials(
    workspace_root: Path,
    entry: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
    material_key: str,
) -> dict[str, str]:
    expected_relative = f"official_materials/{material_key}"
    _require(entry["material_root"] == expected_relative, "FRV_MATERIAL_PATH", "材料目录与固定题号映射不一致")
    material_root = _safe_path(workspace_root, entry["material_root"], "material_root")
    verification = verify_materials(material_root, expected_problem_id=str(entry["problem_id"]))
    _require(verification.ready, "FRV_MATERIAL_INVALID", "官方材料缺失、含泄漏或哈希不闭合")
    _require(
        verification.manifest_sha256 == run_manifest.get("material_manifest_sha256"),
        "FRV_MATERIAL_HASH",
        "Run 未绑定当前材料清单哈希",
    )
    return {
        "path": f"{entry['material_root']}/material_manifest.json",
        "sha256": str(verification.manifest_sha256),
    }


def _validate_run_record(
    run_root: Path,
    entry: Mapping[str, Any],
    earliest: datetime,
) -> tuple[dict[str, Any], dict[str, str]]:
    path = run_root / "full_replay_run_record.json"
    record = _load_object(path, "full_replay_run_record.json")
    _validate_schema(record, "competition_full_replay_run_record.schema.json", path.name)
    _require(record["run_id"] == entry["run_id"], "FRV_IDENTITY_MISMATCH", "运行记录 run_id 不一致")
    _require(record["problem_id"] == entry["problem_id"], "FRV_IDENTITY_MISMATCH", "运行记录 problem_id 不一致")
    started = _parse_time(record["started_at"], "started_at")
    completed = _parse_time(record["completed_at"], "completed_at")
    _require(started >= earliest and completed > started, "FRV_TIME_INVALID", "运行时间不在本 Campaign 有效窗口")
    observed_seconds = (completed - started).total_seconds()
    _require(abs(observed_seconds - float(record["runtime_seconds"])) <= 1.0, "FRV_TIME_INVALID", "runtime_seconds 与起止时间不一致")
    return record, _evidence_ref(run_root, path)


def _validate_adapter(run_root: Path, run_id: str) -> dict[str, str]:
    path = run_root / "competition_production_adapter_report.json"
    adapter = _load_object(path, path.name)
    _validate_schema(adapter, "competition_production_adapter_report.schema.json", path.name)
    _require(adapter["run_id"] == run_id, "FRV_IDENTITY_MISMATCH", "Adapter 报告 run_id 不一致")
    return _evidence_ref(run_root, path)


def _validate_execution_provenance(
    run_root: Path,
    formal_results: list[dict[str, Any]],
    record: Mapping[str, Any],
) -> list[dict[str, str]]:
    replay_started = _parse_time(str(record["started_at"]), "full_replay.started_at")
    replay_completed = _parse_time(str(record["completed_at"]), "full_replay.completed_at")
    expected_commit = str(record["source_control_commit"])
    evidence: list[dict[str, str]] = []
    seen_paths: set[Path] = set()
    for item in formal_results:
        envelope_relative = str(item["envelope_path"])
        envelope_pure = PurePosixPath(envelope_relative)
        _require(
            len(envelope_pure.parts) >= 4
            and envelope_pure.parts[-3] == "formal_results"
            and envelope_pure.name == "formal_result_envelope.json",
            "FRV_EXECUTION_PROVENANCE",
            "Gate 3 Formal Result 路径无法定位 child Run",
        )
        child_relative = PurePosixPath(*envelope_pure.parts[:-3]).as_posix()
        child_root = _safe_path(run_root, child_relative, "child_root")
        attestation_path = child_root / "sandboxie_run_execution_attestation.json"
        _require(
            attestation_path not in seen_paths,
            "FRV_EXECUTION_PROVENANCE",
            "多条路线复用了同一份可信执行证明",
        )
        seen_paths.add(attestation_path)
        attestation = _load_object(attestation_path, attestation_path.name)
        _validate_schema(
            attestation,
            "sandboxie_run_execution_attestation.schema.json",
            attestation_path.name,
        )
        _require(
            attestation["run_id"] == item["child_run_id"]
            and attestation["formal_result_id"] == item["formal_result_id"],
            "FRV_EXECUTION_PROVENANCE",
            "可信执行证明与 Gate 3 Formal Result 身份不一致",
        )
        _require(
            attestation["git_head"] == expected_commit,
            "FRV_SOURCE_COMMIT",
            "可信执行证明未绑定 full_replay 运行记录提交",
        )
        execution_started = _parse_time(attestation["started_at"], "route_execution.started_at")
        execution_completed = _parse_time(
            attestation["completed_at"], "route_execution.completed_at"
        )
        _require(
            replay_started <= execution_started < execution_completed <= replay_completed,
            "FRV_TIME_INVALID",
            "可信路线执行时间不在 full_replay 运行记录窗口内",
        )
        evidence.append(_evidence_ref(run_root, attestation_path))
    _require(
        len(evidence) == 3,
        "FRV_EXECUTION_PROVENANCE",
        "每个子问题必须绑定三份独立可信执行证明",
    )
    return evidence


def _validate_subproblem(
    run_root: Path,
    run_id: str,
    subproblem_id: str,
    record: Mapping[str, Any],
) -> tuple[bool, bool, list[dict[str, str]]]:
    decision_path = run_root / EVIDENCE_FILENAMES["decision"].format(subproblem_id=subproblem_id)
    decision = _load_object(decision_path, decision_path.name)
    validator_id = str(decision.get("validator", {}).get("validator_id", ""))
    recomputed = evaluate_competition_gate3(run_root, subproblem_id, validator_id, write_report=False)
    _require(decision == recomputed, "FRV_GATE3_DRIFT", f"{subproblem_id} Gate 3 无法从当前证据复算")
    _require(decision["run_id"] == run_id, "FRV_IDENTITY_MISMATCH", f"{subproblem_id} Gate 3 run_id 不一致")
    _require(decision["decision"] == "allow_paper", "FRV_GATE3_NOT_ADMITTED", f"{subproblem_id} 未获 Gate 3 论文准入")
    execution_evidence = _validate_execution_provenance(
        run_root, decision["formal_results"], record
    )

    ratings_path = run_root / f"score_v3_ratings_{subproblem_id}.json"
    score_path = run_root / f"score_v3_{subproblem_id}.json"
    stored_score = _load_object(score_path, score_path.name)
    recomputed_score = build_score_v3(run_root, subproblem_id, ratings_path, write_report=False)
    _require(stored_score == recomputed_score, "FRV_SCORE_DRIFT", f"{subproblem_id} score_v3 无法从当前证据复算")
    _require(stored_score["submission_allowed"] is True, "FRV_SCORE_NOT_ADMITTED", f"{subproblem_id} score_v3 禁止提交稿")
    _require(not stored_score["fatal_codes"], "FRV_FATAL_CODE", f"{subproblem_id} 命中 V3F 致命规则")

    comparison_path = run_root / EVIDENCE_FILENAMES["comparison"].format(subproblem_id=subproblem_id)
    comparison = _load_object(comparison_path, comparison_path.name)
    _require(
        all(item["data_leakage_detected"] is False for item in comparison["route_results"]),
        "FRV_TIME_LEAKAGE",
        f"{subproblem_id} 路线比较检测到时间泄漏",
    )
    selected = next(item for item in comparison["route_results"] if item["route_id"] == comparison["selected_route_id"])
    baseline_won = selected["role"] == "baseline"
    evidence = execution_evidence + [
        _evidence_ref(run_root, decision_path),
        _evidence_ref(run_root, ratings_path),
        _evidence_ref(run_root, score_path),
        _evidence_ref(run_root, comparison_path),
    ]
    return baseline_won, bool(stored_score["fatal_codes"]), evidence


def _validate_paper(run_root: Path, run_manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    binding = {
        field: str(run_manifest[field])
        for field in ("run_id", "problem_id", "profile", "runtime_version", "runtime_pack_sha256")
    }
    verify_candidate_manifest(run_root, binding)
    paths = [run_root / "paper_candidate_manifest.json", run_root / "paper_production_manifest_v2.json"]
    return [_evidence_ref(run_root, path) for path in paths]


def _empty_run_result(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "problem_id": entry["problem_id"],
        "run_id": entry["run_id"],
        "profile": "",
        "runtime_pack_sha256": "",
        "status": "failed",
        "failure_codes": [],
        "subproblem_count": 0,
        "runtime_seconds": 0.0,
        "manual_intervention_count": 0,
        "baseline_wins": 0,
        "baseline_win_rate": 0.0,
        "fatal_error_count": 0,
        "fatal_error_rate": 0.0,
        "submission_admission": False,
        "evidence": [],
    }


def _validate_run(
    workspace_root: Path,
    runs_root: Path,
    entry: Mapping[str, Any],
    requirement: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    result = _empty_run_result(entry)
    try:
        run_root = _safe_path(runs_root, str(entry["run_path"]), "run_path")
        _require(run_root.is_dir(), "FRV_RUN_MISSING", f"Run 目录不存在：{entry['run_path']}")
        manifest_path = run_root / "run_manifest.json"
        run_manifest = _load_object(manifest_path, "run_manifest.json")
        result["profile"] = str(run_manifest.get("profile", ""))
        result["runtime_pack_sha256"] = str(run_manifest.get("runtime_pack_sha256", ""))
        result["evidence"].append(_evidence_ref(run_root, manifest_path))
        _require(run_manifest.get("run_id") == entry["run_id"], "FRV_IDENTITY_MISMATCH", "run_manifest.run_id 不一致")
        _require(run_manifest.get("problem_id") == entry["problem_id"], "FRV_IDENTITY_MISMATCH", "run_manifest.problem_id 不一致")
        _require(run_manifest.get("workflow") == "full_replay", "FRV_CONTEXT_INVALID", "Run 不是 full_replay")
        _require(run_manifest.get("profile") in requirement["allowed_profiles"], "FRV_PROFILE_INVALID", "Run Profile 不在合同允许范围")
        _require(run_manifest.get("profile") in ALLOWED_PROFILES, "FRV_PROFILE_INVALID", "Run Profile 不支持生产链")
        _require(run_manifest.get("competition_production_contract_version") == "1.0.0", "FRV_CAPABILITY_DISABLED", "Run 未显式启用 Competition Production")
        _require(run_manifest.get("material_status") == "ready", "FRV_MATERIAL_INVALID", "Run 材料状态不是 ready")
        created = _parse_time(str(run_manifest.get("created_at", "")), "run_manifest.created_at")
        earliest = _parse_time(contract["earliest_run_created_at"], "earliest_run_created_at")
        _require(created >= earliest, "FRV_RUN_NOT_NEW", "Run 早于 PR-7 Campaign 窗口")

        _runtime, runtime_evidence = _validate_runtime_pack(run_root, run_manifest, contract)
        result["evidence"].extend(runtime_evidence)
        result["evidence"].append(
            _validate_materials(workspace_root, entry, run_manifest, str(requirement["material_key"]))
        )
        record, record_ref = _validate_run_record(run_root, entry, earliest)
        result["runtime_seconds"] = float(record["runtime_seconds"])
        result["manual_intervention_count"] = len(record["manual_interventions"])
        result["evidence"].append(record_ref)
        result["evidence"].append(_validate_adapter(run_root, str(entry["run_id"])))

        model_path = run_root / "model_route_v3.json"
        model = _load_object(model_path, model_path.name)
        validate_artifact(model, context="full_replay")
        for field in ("run_id", "problem_id", "profile", "runtime_version", "runtime_pack_sha256"):
            _require(model.get(field) == run_manifest.get(field), "FRV_IDENTITY_MISMATCH", f"model_route_v3.{field} 与 Run 不一致")
        result["evidence"].append(_evidence_ref(run_root, model_path))

        subproblem_ids = [str(item["subproblem_id"]) for item in model["subproblems"]]
        _require(len(subproblem_ids) == len(set(subproblem_ids)), "FRV_SUBPROBLEM_DUPLICATE", "model_route_v3 子问题 ID 重复")
        result["subproblem_count"] = len(subproblem_ids)
        for subproblem_id in subproblem_ids:
            baseline_won, fatal, evidence = _validate_subproblem(
                run_root, str(entry["run_id"]), subproblem_id, record
            )
            result["baseline_wins"] += int(baseline_won)
            result["fatal_error_count"] += int(fatal)
            result["evidence"].extend(evidence)
        denominator = result["subproblem_count"]
        result["baseline_win_rate"] = round(result["baseline_wins"] / denominator, 6)
        result["fatal_error_rate"] = round(result["fatal_error_count"] / denominator, 6)
        result["evidence"].extend(_validate_paper(run_root, run_manifest))
        result["submission_admission"] = True
        result["status"] = "passed"
    except FullReplayCampaignError as exc:
        result["failure_codes"].append(exc.code)
    except (KeyError, StopIteration, OSError, ValueError) as exc:
        result["failure_codes"].append("FRV_RUN_EVIDENCE_INVALID")
        result["failure_codes"] = sorted(set(result["failure_codes"]))
        result["status"] = "failed"
        # 命令行会报告题号和失败码；底层异常不写入可提交报告，避免泄漏本地路径。
        _ = exc
    result["failure_codes"] = sorted(set(result["failure_codes"]))
    return result


def evaluate_campaign(
    manifest_path: Path,
    workspace_root: Path,
    runs_root: Path,
) -> dict[str, Any]:
    """验证固定五题，并仅派生集成 fixture 通过状态。"""
    contract = _load_object(CONTRACT_PATH, "competition_integration_fixture_campaign_v1.json")
    _validate_schema(
        contract,
        "competition_integration_fixture_campaign.schema.json",
        "集成 fixture Campaign 合同",
    )
    manifest = _load_object(manifest_path.resolve(), "Campaign manifest")
    _validate_schema(
        manifest,
        "competition_integration_fixture_manifest.schema.json",
        "Campaign manifest",
    )
    expected_contract_ref = {
        "path": "runtime_contracts/competition_integration_fixture_campaign_v1.json",
        "sha256": _sha256(CONTRACT_PATH),
    }
    _require(manifest["contract"] == expected_contract_ref, "FRV_CONTRACT_DRIFT", "Campaign manifest 未绑定当前合同")

    requirements = {item["problem_id"]: item for item in contract["required_problems"]}
    entries = {item["problem_id"]: item for item in manifest["runs"]}
    _require(len(entries) == len(manifest["runs"]), "FRV_PROBLEM_DUPLICATE", "Campaign 存在重复题号")
    _require(set(entries) == set(requirements), "FRV_PROBLEM_SET", "Campaign 必须恰好覆盖固定五题")
    run_ids = [item["run_id"] for item in manifest["runs"]]
    _require(len(run_ids) == len(set(run_ids)), "FRV_RUN_ID_DUPLICATE", "五题 Run ID 必须唯一")

    results = [
        _validate_run(workspace_root.resolve(), runs_root.resolve(), entries[problem_id], requirements[problem_id], contract)
        for problem_id in requirements
    ]
    subproblem_count = sum(item["subproblem_count"] for item in results)
    baseline_wins = sum(item["baseline_wins"] for item in results)
    fatal_errors = sum(item["fatal_error_count"] for item in results)
    passed = sum(item["status"] == "passed" for item in results)
    admitted = sum(item["submission_admission"] for item in results)
    campaign_passed = passed == len(requirements)
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "competition_integration_fixture_campaign_report_v1",
        "campaign_id": manifest["campaign_id"],
        "capability_id": contract["capability_id"],
        "contract": expected_contract_ref,
        "runs": results,
        "metrics": {
            "problem_count": 5,
            "passed_problem_count": passed,
            "subproblem_count": subproblem_count,
            "runtime_seconds": round(sum(item["runtime_seconds"] for item in results), 6),
            "manual_intervention_count": sum(item["manual_intervention_count"] for item in results),
            "baseline_win_rate": round(baseline_wins / subproblem_count, 6) if subproblem_count else 0.0,
            "fatal_error_rate": round(fatal_errors / subproblem_count, 6) if subproblem_count else 0.0,
            "submission_admission_rate": round(admitted / 5, 6),
        },
        "status": "passed" if campaign_passed else "failed",
        "derived_lifecycle": (
            "integration_fixture_campaign_passed" if campaign_passed else "review_ready"
        ),
        "new_problem_default_enabled": False,
    }
    _validate_schema(report, "competition_integration_fixture_report.schema.json", "Campaign report")
    return report


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workspace-root", default=ROOT, type=Path)
    parser.add_argument("--runs-root", default=ROOT, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_campaign(args.manifest, args.workspace_root, args.runs_root)
    except FullReplayCampaignError as exc:
        print(f"[FAIL] {exc.code}: {exc}")
        return 1
    if args.output:
        _write_json_atomic(args.output, report)
    for item in report["runs"]:
        print(f"[{item['status'].upper()}] {item['problem_id']} {item['run_id']}: {','.join(item['failure_codes']) or 'evidence_closed'}")
    print(json.dumps(report["metrics"], ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
