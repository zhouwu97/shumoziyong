"""验证完整 72 小时模拟赛证据，AI 仅记录、人工最终确认。"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from formal_result.hashing import file_sha256, semantic_sha256
from validate_competition_qualification import (
    QualificationError,
    _active_key,
    _load_json,
    _parse_time,
    _unsigned,
    _validate_schema,
    _verify_file_ref,
    _verify_rsa_signature,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "runtime_contracts" / "competition_72h_simulation_protocol_v1.json"
AUTHORITY_REGISTRY_PATH = (
    ROOT / "policies" / "competition_72h_simulation_authorities_v1.json"
)


def simulation_evidence_digest(evidence: Mapping[str, Any]) -> str:
    """计算排除观察员证明的证据摘要，避免签名字段形成循环引用。"""
    core = copy.deepcopy(dict(evidence))
    core.pop("observer_attestation", None)
    return semantic_sha256(core)


def _verify_artifact_ref(root: Path, ref: Mapping[str, Any], label: str) -> Path:
    relative = str(ref.get("path", ""))
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise QualificationError(f"{label}越出证据根目录") from exc
    if not candidate.is_file():
        raise QualificationError(f"{label}文件不存在：{relative}")
    if file_sha256(candidate) != ref.get("sha256"):
        raise QualificationError(f"{label} SHA-256 漂移：{relative}")
    return candidate


def validate_simulation(
    evidence: Mapping[str, Any],
    protocol: Mapping[str, Any],
    authority_registry: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """复算模拟赛时序、流程开销和提交物闭包。"""
    _validate_schema(protocol, "competition_72h_simulation_protocol.schema.json", "72 小时模拟赛协议")
    _validate_schema(
        authority_registry,
        "competition_72h_simulation_authority_registry.schema.json",
        "72 小时模拟赛人工公钥注册表",
    )
    _validate_schema(evidence, "competition_72h_simulation_evidence.schema.json", "72 小时模拟赛证据")

    protocol_path = _verify_file_ref(
        root,
        evidence["protocol_ref"],
        expected_path="runtime_contracts/competition_72h_simulation_protocol_v1.json",
        label="72 小时模拟赛协议引用",
    )
    registry_path = _verify_file_ref(
        root,
        evidence["authority_registry_ref"],
        expected_path="policies/competition_72h_simulation_authorities_v1.json",
        label="72 小时模拟赛人工公钥注册表引用",
    )
    registered = _load_json(registry_path, "已登记模拟赛人工公钥注册表")
    if registered != authority_registry:
        raise QualificationError("调用方提供的模拟赛人工公钥注册表与哈希绑定文件不一致")
    if authority_registry.get("status") != "active":
        raise QualificationError("72 小时模拟赛人工公钥注册表尚未激活")

    qualification_path = _verify_artifact_ref(
        root, evidence["source_qualification_ref"], "可信资格报告引用"
    )
    qualification = _load_json(qualification_path, "可信资格报告")
    if qualification.get("derived_lifecycle") != "blind_review_passed":
        raise QualificationError("72 小时模拟赛只能从可信 blind_review_passed 启动")

    started_at = _parse_time(str(evidence["started_at"]), "started_at")
    completed_at = _parse_time(str(evidence["completed_at"]), "completed_at")
    elapsed_hours = (completed_at - started_at).total_seconds() / 3600
    fatal_codes: list[str] = []
    gaps: list[str] = []
    if elapsed_hours < 0 or elapsed_hours > float(protocol["maximum_elapsed_hours"]):
        fatal_codes.append("SIM_ELAPSED_TIME_OVER_72H")

    stages = list(evidence["stages"])
    stage_ids = [str(item["stage_id"]) for item in stages]
    if stage_ids != list(protocol["required_stages"]):
        fatal_codes.append("SIM_STAGE_SEQUENCE_INVALID")
    previous_completed = started_at
    for stage in stages:
        stage_started = _parse_time(
            str(stage["started_at"]), f"{stage['stage_id']}.started_at"
        )
        stage_completed = _parse_time(
            str(stage["completed_at"]), f"{stage['stage_id']}.completed_at"
        )
        if not previous_completed <= stage_started <= stage_completed <= completed_at:
            fatal_codes.append("SIM_STAGE_TIME_ORDER")
        previous_completed = stage_completed

    timing = evidence["timing"]
    stage_audit_minutes = sum(float(item["audit_minutes"]) for item in stages)
    stage_active_minutes = sum(
        float(item["human_minutes"]) + float(item["ai_minutes"]) for item in stages
    )
    if abs(stage_audit_minutes - float(timing["audit_process_minutes"])) > 0.01:
        gaps.append("阶段审计耗时合计与 timing.audit_process_minutes 不一致")
    if abs(stage_active_minutes - float(timing["active_work_minutes"])) > 0.01:
        gaps.append("阶段人工与 AI 工作耗时合计与 timing.active_work_minutes 不一致")
    denominator = float(timing["active_work_minutes"]) + float(
        timing["audit_process_minutes"]
    )
    audit_ratio = float(timing["audit_process_minutes"]) / denominator if denominator else 1.0
    if audit_ratio > float(protocol["maximum_audit_overhead_ratio"]):
        gaps.append("审计流程耗时占比超过预注册上限 25%")

    for artifact_name in protocol["required_artifacts"]:
        _verify_artifact_ref(root, evidence["artifacts"][artifact_name], f"提交物 {artifact_name}")

    recorder = evidence["ai_recorder"]
    recorder_started = _parse_time(str(recorder["started_at"]), "ai_recorder.started_at")
    recorder_completed = _parse_time(
        str(recorder["completed_at"]), "ai_recorder.completed_at"
    )
    if recorder["decision_authority"] is not False:
        fatal_codes.append("SIM_AI_DECISION_SUBSTITUTION")

    attestation = evidence["observer_attestation"]
    signed_at = _parse_time(str(attestation["signed_at"]), "observer_attestation.signed_at")
    if not started_at <= recorder_started <= recorder_completed <= signed_at:
        fatal_codes.append("SIM_AI_RECORD_TIME_ORDER")
    if signed_at <= completed_at:
        fatal_codes.append("SIM_HUMAN_ATTESTATION_TOO_EARLY")
    if attestation["evidence_digest"] != simulation_evidence_digest(evidence):
        fatal_codes.append("SIM_EVIDENCE_DIGEST_DRIFT")
    if attestation["ai_decision_authority"] is not False:
        fatal_codes.append("SIM_AI_DECISION_SUBSTITUTION")

    keys = {str(item["key_id"]): item for item in authority_registry["keys"]}
    observer_key = _active_key(
        keys,
        str(attestation["observer_key_id"]),
        role="simulation_observer",
        signed_at=signed_at,
        label="72 小时模拟赛人工观察员证明",
    )
    _verify_rsa_signature(
        _unsigned(attestation),
        str(attestation["signature"]),
        observer_key,
        "72 小时模拟赛人工观察员证明",
    )

    fatal_codes = sorted(set(fatal_codes))
    passed = not fatal_codes and not gaps
    report = {
        "schema_version": "1.0.0",
        "report_id": f"{evidence['simulation_id']}-report",
        "simulation_id": evidence["simulation_id"],
        "protocol_sha256": file_sha256(protocol_path),
        "evidence_sha256": semantic_sha256(evidence),
        "status": "competition_72h_simulation_passed" if passed else "failed",
        "default_candidate_eligible": passed,
        "elapsed_hours": elapsed_hours,
        "audit_overhead_ratio": audit_ratio,
        "stage_count": len(stages),
        "artifact_count": len(evidence["artifacts"]),
        "human_attested": True,
        "ai_record_only": recorder["decision_authority"] is False,
        "fatal_codes": fatal_codes,
        "gaps": gaps,
    }
    _validate_schema(report, "competition_72h_simulation_report.schema.json", "72 小时模拟赛报告")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--authority-registry", type=Path, default=AUTHORITY_REGISTRY_PATH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = _load_json(args.evidence, "72 小时模拟赛证据")
    protocol = _load_json(args.protocol, "72 小时模拟赛协议")
    registry = _load_json(args.authority_registry, "72 小时模拟赛人工公钥注册表")
    report = validate_simulation(evidence, protocol, registry, root=ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
