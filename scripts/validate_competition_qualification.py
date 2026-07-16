"""验证 Competition Production 六题隐藏盲测与双盲人工评审证据。"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from formal_result.canonicalization import canonical_bytes
from formal_result.hashing import file_sha256, semantic_sha256


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "runtime_contracts" / "competition_qualification_protocol_v1.json"
AUTHORITY_REGISTRY_PATH = (
    ROOT / "policies" / "competition_qualification_authorities_v1.json"
)
SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class QualificationError(ValueError):
    """资格证据无法安全解释。"""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{label}无法读取：{exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label}必须是 JSON 对象")
    return value


def _validate_schema(value: Mapping[str, Any], schema_name: str, label: str) -> None:
    schema = _load_json(ROOT / "schemas" / schema_name, f"{label} Schema")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.absolute_path) or "<root>"
        raise QualificationError(f"{label}不符合 Schema：{location}: {first.message}")


def _parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:  # Schema 已覆盖普通格式错误。
        raise QualificationError(f"{label}不是合法时间") from exc
    if parsed.tzinfo is None:
        raise QualificationError(f"{label}必须包含时区")
    return parsed


def _safe_ref(root: Path, relative: str, label: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise QualificationError(f"{label}越出工作区") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise QualificationError(f"{label}不是普通文件：{relative}")
    return candidate


def _verify_file_ref(
    root: Path,
    ref: Mapping[str, Any],
    *,
    expected_path: str,
    label: str,
) -> Path:
    if ref.get("path") != expected_path:
        raise QualificationError(f"{label}路径必须为 {expected_path}")
    path = _safe_ref(root, expected_path, label)
    if file_sha256(path) != ref.get("sha256"):
        raise QualificationError(f"{label} SHA-256 漂移")
    return path


def _unsigned(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    payload.pop("signature", None)
    return payload


def _verify_rsa_signature(
    payload: Mapping[str, Any], signature_text: str, key: Mapping[str, Any], label: str
) -> None:
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except ValueError as exc:
        raise QualificationError(f"{label}签名不是严格 Base64") from exc
    modulus = int(str(key["rsa_modulus_hex"]), 16)
    exponent = int(key["rsa_exponent"])
    width = (modulus.bit_length() + 7) // 8
    if len(signature) != width:
        raise QualificationError(f"{label}签名长度与公钥不一致")
    decoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(width, "big")
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(canonical_bytes(payload)).digest()
    padding_size = width - len(digest_info) - 3
    expected = b"\x00\x01" + b"\xff" * padding_size + b"\x00" + digest_info
    if padding_size < 8 or not hmac.compare_digest(decoded, expected):
        raise QualificationError(f"{label}签名验证失败")


def _active_key(
    keys: Mapping[str, Mapping[str, Any]],
    key_id: str,
    *,
    role: str,
    signed_at: datetime,
    label: str,
) -> Mapping[str, Any]:
    key = keys.get(key_id)
    if key is None or key.get("status") != "active":
        raise QualificationError(f"{label}未使用 active 可信公钥")
    if key.get("role") != role or key.get("human_identity_verified") is not True:
        raise QualificationError(f"{label}角色或人工身份核验状态非法")
    if key.get("signature_algorithm") != "RSASSA-PKCS1-v1_5-SHA256":
        raise QualificationError(f"{label}签名算法非法")
    if not _parse_time(str(key["not_before"]), f"{label}.not_before") <= signed_at <= _parse_time(
        str(key["not_after"]), f"{label}.not_after"
    ):
        raise QualificationError(f"{label}签名时间不在公钥有效期")
    return key


def qualification_evidence_digest(evidence: Mapping[str, Any]) -> str:
    """生成供最终人工批准绑定的稳定摘要，不包含批准记录本身。"""
    core = copy.deepcopy(dict(evidence))
    core.pop("promotion_approval", None)
    return semantic_sha256(core)


def qualification_campaign_digest(evidence: Mapping[str, Any]) -> str:
    """绑定协调员证明产生前的题目、运行指标、匿名包和全部盲评。"""
    core = copy.deepcopy(dict(evidence))
    core.pop("coordinator_attestation", None)
    core.pop("promotion_approval", None)
    return semantic_sha256(core)


def _commitment_root(cases: list[Mapping[str, Any]]) -> str:
    value = [
        {
            "case_slot": item["case_slot"],
            "material_commitment_sha256": item["material_commitment_sha256"],
        }
        for item in sorted(cases, key=lambda entry: str(entry["case_slot"]))
    ]
    return semantic_sha256(value)


def _mapping_digest(cases: list[Mapping[str, Any]]) -> str:
    value = [
        {
            "case_slot": item["case_slot"],
            "package_arm_mapping": item["package_arm_mapping"],
        }
        for item in sorted(cases, key=lambda entry: str(entry["case_slot"]))
    ]
    return semantic_sha256(value)


def _rate(overclaims: int, supported: int) -> float:
    total = overclaims + supported
    return overclaims / total if total else 0.0


def _empty_metrics() -> dict[str, float | int]:
    return {
        "baseline_model_quality": 0.0,
        "treatment_model_quality": 0.0,
        "model_quality_gain": 0.0,
        "baseline_paper_quality": 0.0,
        "treatment_paper_quality": 0.0,
        "paper_quality_gain": 0.0,
        "baseline_executable_rate": 0.0,
        "treatment_executable_rate": 0.0,
        "baseline_manual_revision_minutes": 0.0,
        "treatment_manual_revision_minutes": 0.0,
        "revision_time_reduction_ratio": 0.0,
        "baseline_overclaim_rate": 0.0,
        "treatment_overclaim_rate": 0.0,
        "cases_with_combined_quality_gain": 0,
    }


def validate_qualification(
    evidence: Mapping[str, Any],
    protocol: Mapping[str, Any],
    authority_registry: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """复算资格指标并按证据强度派生生命周期。"""
    _validate_schema(protocol, "competition_qualification_protocol.schema.json", "资格协议")
    _validate_schema(
        authority_registry,
        "competition_qualification_authority_registry.schema.json",
        "资格评审公钥注册表",
    )
    _validate_schema(evidence, "competition_qualification_evidence.schema.json", "资格证据")
    protocol_path = _verify_file_ref(
        root,
        evidence["protocol_ref"],
        expected_path="runtime_contracts/competition_qualification_protocol_v1.json",
        label="资格协议引用",
    )
    registry_path = _verify_file_ref(
        root,
        evidence["authority_registry_ref"],
        expected_path="policies/competition_qualification_authorities_v1.json",
        label="资格评审公钥注册表引用",
    )
    registered_authorities = _load_json(registry_path, "已登记资格评审公钥注册表")
    if registered_authorities != authority_registry:
        raise QualificationError("调用方提供的资格评审公钥注册表与哈希绑定文件不一致")
    capability_path = _verify_file_ref(
        root,
        evidence["source_capability_ref"],
        expected_path="runtime_contracts/competition_production_capability_v1.json",
        label="源能力引用",
    )
    capability = _load_json(capability_path, "源能力")
    if capability.get("lifecycle") != "full_replay_passed":
        raise QualificationError("资格活动只能从 full_replay_passed 启动")
    if authority_registry.get("status") != "active":
        raise QualificationError("真实人工评审公钥注册表尚未激活")
    keys = {str(item["key_id"]): item for item in authority_registry["keys"]}
    if len(keys) != len(authority_registry["keys"]):
        raise QualificationError("资格评审公钥 key_id 重复")

    gaps: list[str] = []
    fatal_codes: list[str] = []
    locked_at = _parse_time(str(evidence["locked_at"]), "locked_at")
    cases = list(evidence["cases"])
    expected_slots = list(protocol["case_slots"])
    slots = [str(item["case_slot"]) for item in cases]
    if sorted(slots) != sorted(expected_slots) or len(slots) != len(set(slots)):
        raise QualificationError("资格证据未精确覆盖固定六个盲测槽位")

    selection_attestation = evidence["selection_attestation"]
    selection_signed_at = _parse_time(
        str(selection_attestation["locked_at"]), "selection_attestation.locked_at"
    )
    selection_key = _active_key(
        keys,
        str(selection_attestation["coordinator_key_id"]),
        role="qualification_coordinator",
        signed_at=selection_signed_at,
        label="隐藏题选题承诺",
    )
    if selection_signed_at != locked_at:
        raise QualificationError("隐藏题选题承诺时间与 Campaign locked_at 不一致")
    if selection_attestation["case_commitment_root"] != _commitment_root(cases):
        raise QualificationError("隐藏题选题承诺根与六题材料承诺不一致")
    _verify_rsa_signature(
        _unsigned(selection_attestation),
        str(selection_attestation["signature"]),
        selection_key,
        "隐藏题选题承诺",
    )

    package_to_arm: dict[str, tuple[str, str, datetime]] = {}
    run_metrics: dict[str, list[Mapping[str, Any]]] = {"baseline": [], "treatment": []}
    for case in cases:
        slot = str(case["case_slot"])
        selection_locked = _parse_time(str(case["selection_locked_at"]), f"{slot}.selection")
        first_revealed = _parse_time(
            str(case["first_revealed_to_runner_at"]), f"{slot}.first_revealed"
        )
        if selection_locked > locked_at or first_revealed <= locked_at:
            fatal_codes.append("QF_POST_HOC_CASE_REPLACEMENT")
        if case["answer_leakage_detected"] or case["time_leakage_detected"]:
            fatal_codes.append("QF_CASE_LEAKAGE")
        baseline = case["baseline"]
        treatment = case["treatment"]
        for arm_name, arm in (("baseline", baseline), ("treatment", treatment)):
            started = _parse_time(str(arm["started_at"]), f"{slot}.{arm_name}.started")
            completed = _parse_time(str(arm["completed_at"]), f"{slot}.{arm_name}.completed")
            if not first_revealed <= started <= completed:
                fatal_codes.append("QF_RUN_TIME_ORDER")
            if arm["formal_validation_passed"] is not True:
                fatal_codes.append("QF_MISSING_FORMAL_VALIDATION")
            if int(arm["overclaim_count"]) > int(arm["supported_claim_count"]):
                fatal_codes.append("QF_INVALID_CLAIM_COUNTS")
            run_metrics[arm_name].append(arm)
        if baseline["execution_controls_sha256"] != treatment["execution_controls_sha256"]:
            fatal_codes.append("QF_UNEQUAL_EXECUTION_CONTROLS")
        if treatment["fatal_error"] is True:
            fatal_codes.append("QF_TREATMENT_FATAL_ERROR")

        packages = list(case["review_packages"])
        labels = [str(item["label"]) for item in packages]
        if sorted(labels) != ["X", "Y"]:
            raise QualificationError(f"{slot} 未精确提供 X/Y 两个匿名包")
        package_ids = [str(item["package_id"]) for item in packages]
        if len(package_ids) != len(set(package_ids)):
            raise QualificationError(f"{slot} 匿名包 ID 重复")
        latest_run = max(
            _parse_time(str(baseline["completed_at"]), f"{slot}.baseline.completed"),
            _parse_time(str(treatment["completed_at"]), f"{slot}.treatment.completed"),
        )
        mapping = case["package_arm_mapping"]
        mapping_revealed = _parse_time(
            str(case["mapping_revealed_at"]), f"{slot}.mapping_revealed"
        )
        for package in packages:
            created = _parse_time(str(package["created_at"]), f"{slot}.package.created")
            if created < latest_run:
                fatal_codes.append("QF_PACKAGE_BEFORE_RUN_COMPLETE")
            package_id = str(package["package_id"])
            if package_id in package_to_arm:
                raise QualificationError("跨题匿名包 ID 重复")
            package_to_arm[package_id] = (slot, str(mapping[package["label"]]), mapping_revealed)

    reviews = list(evidence["blind_reviews"])
    review_ids = [str(item["review_id"]) for item in reviews]
    if len(review_ids) != len(set(review_ids)):
        raise QualificationError("盲评记录 review_id 重复")
    reviews_by_package: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    arm_reviews: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    case_arm_reviews: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    reviewer_ids: set[str] = set()
    for review in reviews:
        package_id = str(review["package_id"])
        package_binding = package_to_arm.get(package_id)
        if package_binding is None:
            raise QualificationError("盲评引用了未知匿名包")
        slot, arm_name, mapping_revealed = package_binding
        if review["case_slot"] != slot:
            raise QualificationError("盲评 case_slot 与匿名包不一致")
        signed_at = _parse_time(str(review["signed_at"]), f"{review['review_id']}.signed_at")
        if signed_at >= mapping_revealed:
            fatal_codes.append("QF_ARM_IDENTITY_LEAKAGE")
        key_id = str(review["reviewer_key_id"])
        key = _active_key(
            keys,
            key_id,
            role="human_reviewer",
            signed_at=signed_at,
            label=f"盲评 {review['review_id']}",
        )
        _verify_rsa_signature(
            _unsigned(review), str(review["signature"]), key, f"盲评 {review['review_id']}"
        )
        reviewer_ids.add(key_id)
        reviews_by_package[package_id].append(review)
        arm_reviews[arm_name].append(review)
        case_arm_reviews[(slot, arm_name)].append(review)

    expected_reviewers = int(protocol["blinding"]["reviewers_per_package"])
    for package_id in package_to_arm:
        package_reviews = reviews_by_package.get(package_id, [])
        package_reviewer_ids = {str(item["reviewer_key_id"]) for item in package_reviews}
        if len(package_reviews) != expected_reviewers or len(package_reviewer_ids) != expected_reviewers:
            gaps.append(f"匿名包 {package_id} 未获得 {expected_reviewers} 名独立人工评审")
    if len(reviews) != len(package_to_arm) * expected_reviewers:
        gaps.append("盲评总数未精确覆盖六题双臂双评审")

    latest_review = max(
        (_parse_time(str(item["signed_at"]), f"{item['review_id']}.signed_at") for item in reviews),
        default=locked_at,
    )
    for case in cases:
        mapping_revealed = _parse_time(
            str(case["mapping_revealed_at"]), f"{case['case_slot']}.mapping_revealed"
        )
        if mapping_revealed <= latest_review:
            fatal_codes.append("QF_ARM_IDENTITY_LEAKAGE")

    attestation = evidence["coordinator_attestation"]
    coordinator_signed_at = _parse_time(
        str(attestation["signed_at"]), "coordinator_attestation.signed_at"
    )
    coordinator_key = _active_key(
        keys,
        str(attestation["coordinator_key_id"]),
        role="qualification_coordinator",
        signed_at=coordinator_signed_at,
        label="资格协调员证明",
    )
    if coordinator_signed_at <= latest_review:
        fatal_codes.append("QF_COORDINATOR_ATTESTED_TOO_EARLY")
    if attestation["case_commitment_root"] != _commitment_root(cases):
        fatal_codes.append("QF_CASE_COMMITMENT_DRIFT")
    if attestation["mapping_sha256"] != _mapping_digest(cases):
        fatal_codes.append("QF_MAPPING_DRIFT")
    if attestation["campaign_evidence_digest"] != qualification_campaign_digest(evidence):
        fatal_codes.append("QF_CAMPAIGN_EVIDENCE_DRIFT")
    _verify_rsa_signature(
        _unsigned(attestation),
        str(attestation["signature"]),
        coordinator_key,
        "资格协调员证明",
    )

    metrics = _empty_metrics()
    if all(arm_reviews.get(arm) for arm in ("baseline", "treatment")):
        for arm in ("baseline", "treatment"):
            metrics[f"{arm}_model_quality"] = fmean(
                float(item["model_quality_score"]) for item in arm_reviews[arm]
            )
            metrics[f"{arm}_paper_quality"] = fmean(
                float(item["paper_quality_score"]) for item in arm_reviews[arm]
            )
            arm_runs = run_metrics[arm]
            metrics[f"{arm}_executable_rate"] = sum(
                bool(item["executable_solution"]) for item in arm_runs
            ) / len(arm_runs)
            metrics[f"{arm}_manual_revision_minutes"] = sum(
                float(item["manual_revision_minutes"]) for item in arm_runs
            )
            supported = sum(int(item["supported_claim_count"]) for item in arm_runs)
            overclaims = sum(int(item["overclaim_count"]) for item in arm_runs)
            metrics[f"{arm}_overclaim_rate"] = _rate(overclaims, supported)
        metrics["model_quality_gain"] = (
            float(metrics["treatment_model_quality"]) - float(metrics["baseline_model_quality"])
        )
        metrics["paper_quality_gain"] = (
            float(metrics["treatment_paper_quality"]) - float(metrics["baseline_paper_quality"])
        )
        baseline_minutes = float(metrics["baseline_manual_revision_minutes"])
        treatment_minutes = float(metrics["treatment_manual_revision_minutes"])
        metrics["revision_time_reduction_ratio"] = (
            (baseline_minutes - treatment_minutes) / baseline_minutes
            if baseline_minutes > 0
            else 0.0
        )
        combined_gains = 0
        for slot in expected_slots:
            baseline_scores = case_arm_reviews[(slot, "baseline")]
            treatment_scores = case_arm_reviews[(slot, "treatment")]
            if baseline_scores and treatment_scores:
                baseline_combined = fmean(
                    (float(item["model_quality_score"]) + float(item["paper_quality_score"])) / 2
                    for item in baseline_scores
                )
                treatment_combined = fmean(
                    (float(item["model_quality_score"]) + float(item["paper_quality_score"])) / 2
                    for item in treatment_scores
                )
                combined_gains += treatment_combined > baseline_combined
        metrics["cases_with_combined_quality_gain"] = combined_gains

    thresholds = protocol["promotion_thresholds"]
    comparisons = [
        (
            float(metrics["treatment_model_quality"])
            >= float(thresholds["minimum_treatment_model_quality"]),
            "Treatment 模型质量均分未达 80",
        ),
        (
            float(metrics["model_quality_gain"])
            >= float(thresholds["minimum_model_quality_gain"]),
            "Treatment 模型质量增益未达 3 分",
        ),
        (
            float(metrics["treatment_paper_quality"])
            >= float(thresholds["minimum_treatment_paper_quality"]),
            "Treatment 论文质量均分未达 80",
        ),
        (
            float(metrics["paper_quality_gain"])
            >= float(thresholds["minimum_paper_quality_gain"]),
            "Treatment 论文质量增益未达 3 分",
        ),
        (
            float(metrics["treatment_executable_rate"])
            >= float(thresholds["minimum_treatment_executable_rate"]),
            "Treatment 可执行方案率不足 5/6",
        ),
        (
            float(metrics["treatment_executable_rate"])
            >= float(metrics["baseline_executable_rate"]),
            "Treatment 可执行方案率低于 Baseline",
        ),
        (
            float(metrics["revision_time_reduction_ratio"])
            >= float(thresholds["minimum_revision_time_reduction_ratio"]),
            "人工修订时间降幅未达 10%",
        ),
        (
            float(metrics["treatment_overclaim_rate"])
            <= float(thresholds["maximum_treatment_overclaim_rate"]),
            "Treatment 结论越界率超过 5%",
        ),
        (
            float(metrics["treatment_overclaim_rate"])
            <= float(metrics["baseline_overclaim_rate"]),
            "Treatment 结论越界率高于 Baseline",
        ),
        (
            int(metrics["cases_with_combined_quality_gain"])
            >= int(thresholds["minimum_cases_with_combined_quality_gain"]),
            "逐题综合质量提升不足 4/6",
        ),
    ]
    gaps.extend(message for passed, message in comparisons if not passed)
    if any(
        bool(item["fatal_error"])
        for item in arm_reviews.get("treatment", [])
    ):
        fatal_codes.append("QF_TREATMENT_FATAL_ERROR")

    fatal_codes = sorted(set(fatal_codes))
    derived_lifecycle = "full_replay_passed"
    status = "failed"
    double_blind_attested = not fatal_codes and not any("盲评" in item for item in gaps)
    if not fatal_codes:
        derived_lifecycle = "qualification_candidate"
        status = "qualification_candidate"
        if not gaps:
            derived_lifecycle = "blind_review_passed"
            status = "blind_review_passed"

    approval = evidence.get("promotion_approval")
    if status == "blind_review_passed" and isinstance(approval, Mapping):
        approved_at = _parse_time(str(approval["approved_at"]), "promotion_approval.approved_at")
        approval_key = _active_key(
            keys,
            str(approval["coordinator_key_id"]),
            role="qualification_coordinator",
            signed_at=approved_at,
            label="默认候选人工批准",
        )
        if approved_at <= coordinator_signed_at:
            raise QualificationError("默认候选人工批准早于资格协调员证明")
        expected_digest = qualification_evidence_digest(evidence)
        if approval["evidence_digest"] != expected_digest:
            raise QualificationError("默认候选人工批准未绑定当前资格证据摘要")
        _verify_rsa_signature(
            _unsigned(approval), str(approval["signature"]), approval_key, "默认候选人工批准"
        )
        derived_lifecycle = "default_candidate"
        status = "default_candidate"
    elif status == "blind_review_passed":
        gaps.append("尚缺独立的 default_candidate 人工批准；盲评通过不自动启用默认能力")

    report = {
        "schema_version": "1.0.0",
        "report_id": f"{evidence['campaign_id']}-report",
        "campaign_id": evidence["campaign_id"],
        "protocol_sha256": file_sha256(protocol_path),
        "evidence_sha256": semantic_sha256(evidence),
        "status": status,
        "derived_lifecycle": derived_lifecycle,
        "new_problem_default_enabled": False,
        "metrics": metrics,
        "fatal_codes": fatal_codes,
        "gaps": gaps,
        "review_summary": {
            "review_count": len(reviews),
            "distinct_human_reviewers": len(reviewer_ids),
            "all_signatures_valid": True,
            "double_blind_attested": double_blind_attested,
        },
    }
    _validate_schema(report, "competition_qualification_report.schema.json", "资格派生报告")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path, help="私有资格证据 JSON")
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--authority-registry", type=Path, default=AUTHORITY_REGISTRY_PATH)
    parser.add_argument("--workspace-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    evidence = _load_json(args.evidence, "资格证据")
    protocol = _load_json(args.protocol, "资格协议")
    registry = _load_json(args.authority_registry, "资格评审公钥注册表")
    try:
        report = validate_qualification(
            evidence,
            protocol,
            registry,
            root=args.workspace_root.resolve(),
        )
    except QualificationError as exc:
        raise SystemExit(f"资格验证失败：{exc}") from exc
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")


if __name__ == "__main__":
    main()
