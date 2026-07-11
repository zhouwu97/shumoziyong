"""
Patch 晋级资格统一评估引擎。

validate_repository.py 和 check_promotion_eligibility.py 都通过本模块
读取 promotion_policy.json 进行判断 —— 这是项目的唯一机器事实源。
禁止各文件自行硬编码晋级规则。

用法：
    from promotion_engine import evaluate_status_eligibility, EligibilityReport

    report = evaluate_status_eligibility(patch, target_status, policy, matrix_entry, evidence_records)
    # report.current_status_valid -> bool
    # report.next_status -> str | None
    # report.next_status_eligible -> bool
    # report.gaps_to_next_status -> list[str]
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

def stable_evidence_digest(
    patch: dict[str, Any], 
    evidence: dict[str, Any],
    patch_sha256: str = "",
    inner_component_sha256s: dict[str, str] | None = None,
    *,
    policy_version: str,
) -> str:
    """计算稳定证据的摘要，供人工批准记录绑定。"""
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ValueError("stable evidence digest 必须显式提供非空 policy_version")
    import json
    data = {
        "digest_schema_version": "2.0.0",
        "target_status": "stable",
        "policy_version": policy_version,
        "patch_id": patch.get("patch_id"),
        "patch_sha256": patch_sha256,
        "inner_component_sha256s": inner_component_sha256s or {},
        "negative_control_runs": evidence.get("negative_control_runs", []),
        "failure_fix_retests": evidence.get("failure_fix_retests", []),
        "competition_validation_records": evidence.get("competition_validation_records", []),
    }
    normalized = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def load_json(path: Path) -> Any:
    """读取 JSON 文件。"""
    import json
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class PromotionGap:
    """一条不满足的条件。"""

    def __init__(self, patch_id: str, target_status: str, condition: str) -> None:
        self.patch_id = patch_id
        self.target_status = target_status
        self.condition = condition

    def __str__(self) -> str:
        return f"[{self.patch_id}] → {self.target_status}：{self.condition}"


@dataclass
class EligibilityReport:
    """patch 对某个目标状态的资格评估结果。"""

    patch_id: str
    current_status: str
    target_status: str
    eligible: bool = False
    gaps: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def current_status_valid(self) -> bool:
        """当前状态是否满足其自身的最低门槛。"""
        return self.eligible


@dataclass
class FullEligibilityReport:
    """包含当前状态验证和下一级状态差距的完整报告。"""

    patch_id: str
    current_status: str
    current_status_valid: bool
    current_gaps: list[str]
    next_status: str | None
    next_status_eligible: bool
    gaps_to_next_status: list[str]
    details: dict[str, Any]


STATUS_ORDER = ["draft", "candidate", "verified_candidate", "stable"]


def _next_status(current: str) -> str | None:
    """返回当前状态的下一级，若已是最高级则返回 None。"""
    try:
        idx = STATUS_ORDER.index(current)
        if idx + 1 < len(STATUS_ORDER):
            return STATUS_ORDER[idx + 1]
        return None
    except ValueError:
        return None


def _get_case_metadata(matrix_entry: dict[str, Any], control: str) -> dict[str, Any]:
    """从矩阵条目中提取单条控制的 case 元数据。"""
    ctrl = matrix_entry.get(control, {})
    meta = ctrl.get("case_metadata") if isinstance(ctrl.get("case_metadata"), dict) else {}
    case_id = ctrl.get("case", "")
    if not meta:
        # 自举：从 case 字符串和矩阵上下文构造基础元数据
        return {
            "problem_id": case_id,
            "year": None,
            "mechanism_class": None,
            "relation_to_patch": control if control in ("positive", "boundary", "negative") else "unknown",
            "material_level": None,
        }
    meta.setdefault("problem_id", case_id)
    return meta


def _count_patch_level_mechanisms(
    patch: dict[str, Any],
    matrix_entry: dict[str, Any],
    all_matrix_entries: dict[str, dict[str, Any]],
) -> int:
    """统计 patch 级别的独立机制类——从矩阵 case_metadata 计数，不从 profile 继承。"""
    mechanisms: set[str] = set()
    for control in ("positive", "boundary", "negative"):
        meta = _get_case_metadata(matrix_entry, control)
        mc = meta.get("mechanism_class")
        if mc and isinstance(mc, str):
            mechanisms.add(mc)
    # 如果矩阵没有 case_metadata，回退到从 patch 的 tested_on 和 matrix 交叉推断
    # 但不得从 runtime profile 继承机制数量
    if not mechanisms:
        for control in ("positive", "boundary", "negative"):
            case = matrix_entry.get(control, {}).get("case")
            if case:
                mechanisms.add(f"unknown:{case}")
    return len(mechanisms)


def _count_distinct_cases(matrix_entry: dict[str, Any]) -> int:
    """统计矩阵中不同考题的数量。"""
    cases: set[str] = set()
    for control in ("positive", "boundary", "negative"):
        case = matrix_entry.get(control, {}).get("case")
        if case:
            cases.add(case)
    return len(cases)


def _count_distinct_years(matrix_entry: dict[str, Any]) -> int:
    """统计矩阵中不同年份的数量——从 case_metadata.year 提取。"""
    years: set[int] = set()
    for control in ("positive", "boundary", "negative"):
        meta = _get_case_metadata(matrix_entry, control)
        y = meta.get("year")
        if isinstance(y, int) and y >= 2000:
            years.add(y)
    if not years:
        # 自举：从 case 字符串如 "2024-C" 提取年份
        for control in ("positive", "boundary", "negative"):
            case = matrix_entry.get(control, {}).get("case")
            if isinstance(case, str) and len(case) >= 4 and case[:4].isdigit():
                years.add(int(case[:4]))
    return len(years)


def _check_forbidden_labels(
    patch: dict[str, Any],
    policy_rules: dict[str, Any],
) -> list[str]:
    """检查 validation_records 中是否出现禁止的 P/M 标签。"""
    gaps: list[str] = []
    forbidden_p = set(policy_rules.get("forbidden_failure_labels", []))
    forbidden_m = set(policy_rules.get("forbidden_material_risks", []))

    records = patch.get("validation_records", [])
    if not records:
        return gaps

    for record_path in records:
        # 尝试从同目录的 failure_labels.json 读取
        record = Path(record_path)
        if not record.is_absolute():
            record = Path(__file__).resolve().parents[1] / record_path
        run_dir = record.parent if record.is_file() else record
        labels_file = run_dir / "failure_labels.json"
        if labels_file.is_file():
            import json
            try:
                data = json.loads(labels_file.read_text(encoding="utf-8"))
                labels = set(data.get("labels", []))
                material_risks = set(data.get("material_risks", []))
                hits_p = labels & forbidden_p
                hits_m = material_risks & forbidden_m
                for label in sorted(hits_p):
                    gaps.append(f"validation_record 中出现禁止标签：{label}（禁止 {sorted(forbidden_p)}）")
                for label in sorted(hits_m):
                    gaps.append(f"validation_record 中出现禁止材料风险：{label}（禁止 {sorted(forbidden_m)}）")
            except (OSError, json.JSONDecodeError):
                pass

    return gaps


def _positive_boundary_differ(matrix_entry: dict[str, Any]) -> bool:
    """检查 positive 和 boundary 是否使用不同考题。"""
    pos = matrix_entry.get("positive", {}).get("case", "")
    bnd = matrix_entry.get("boundary", {}).get("case", "")
    return pos != bnd or (not pos and not bnd)


def _positive_negative_differ(matrix_entry: dict[str, Any]) -> bool:
    """检查 positive 和 negative 是否使用不同考题。"""
    pos = matrix_entry.get("positive", {}).get("case", "")
    neg = matrix_entry.get("negative", {}).get("case", "")
    return pos != neg or (not pos and not neg)


def _negative_is_out_of_scope(matrix_entry: dict[str, Any]) -> bool:
    """检查 negative case 是否与 positive/boundary 不同（即 out of scope）。

    判定：有显式 case_metadata.relation_to_patch 则以其为准；
    否则用 negative case ID 与 positive/boundary case ID 不同作为自举判定。
    2016-C vs 2024-C 这种跨年不同题天然就是 out of scope。
    """
    meta = _get_case_metadata(matrix_entry, "negative")
    explicit = meta.get("relation_to_patch")
    if explicit == "negative_out_of_scope":
        return True
    if explicit and explicit != "negative_out_of_scope":
        return False

    # 自举：negative case ID 不同于 positive 和 boundary
    neg_case = matrix_entry.get("negative", {}).get("case", "")
    pos_case = matrix_entry.get("positive", {}).get("case", "")
    bnd_case = matrix_entry.get("boundary", {}).get("case", "")
    if neg_case and (neg_case != pos_case or not pos_case) and (neg_case != bnd_case or not bnd_case):
        return True
    return False


def evaluate_status_eligibility(
    patch: dict[str, Any],
    matrix_entry: dict[str, Any],
    policy: dict[str, Any],
    target_status: str,
    *,
    all_matrix_entries: dict[str, dict[str, Any]] | None = None,
) -> EligibilityReport:
    """根据 promotion_policy.json 评估单个 patch 对指定状态的资格。

    Args:
        patch: patch_index 中的一条记录。
        matrix_entry: 负控矩阵中该 patch 的记录。
        policy: 已加载的 promotion_policy.json。
        target_status: 要评估的目标状态。
        all_matrix_entries: 完整的矩阵条目字典（用于跨 patch 分析，可选）。

    Returns:
        EligibilityReport 包含 eligible、gaps 和 details。
    """
    pid = patch.get("patch_id", "<unknown>")
    all_entries = all_matrix_entries or {}
    rules = policy.get("status_rules", {}).get(target_status)
    if rules is None:
        return EligibilityReport(
            patch_id=pid,
            current_status=patch.get("status", "draft"),
            target_status=target_status,
            eligible=False,
            gaps=[f"policy 中未定义状态：{target_status}"],
        )

    gaps: list[str] = []
    details: dict[str, Any] = {}

    # 1) 检查 required_controls
    required_controls = rules.get("required_controls", [])
    passed_controls = 0
    control_results: dict[str, str] = {}
    for control in ("positive", "boundary", "negative"):
        control_data = matrix_entry.get(control, {})
        result = control_data.get("_derived_result", control_data.get("result", "pending"))
        control_results[control] = result
        if control in required_controls and result != rules.get("required_result", "pass"):
            gaps.append(
                f"{control}-control 必须为 {rules['required_result']}（当前为 {result}）"
            )
        if result == "pass":
            passed_controls += 1
    details["control_results"] = control_results
    details["passed_controls"] = passed_controls

    # 2) 独立考题数量
    distinct_cases = _count_distinct_cases(matrix_entry)
    min_cases = rules.get("min_distinct_cases", 0)
    if distinct_cases < min_cases:
        gaps.append(
            f"至少需要 {min_cases} 道不同考题，当前 {distinct_cases} 道"
        )
    details["distinct_cases"] = distinct_cases

    # 3) 独立年份
    min_years = rules.get("min_distinct_years", 0)
    distinct_years = _count_distinct_years(matrix_entry)
    if distinct_years < min_years:
        gaps.append(
            f"至少需要 {min_years} 个不同年份，当前 {distinct_years} 个"
        )
    details["distinct_years"] = distinct_years

    # 4) positive/negative 考题不得相同
    if rules.get("positive_negative_must_differ") and not _positive_negative_differ(matrix_entry):
        gaps.append("positive 和 negative 必须使用不同考题")
    if rules.get("positive_boundary_must_differ") and not _positive_boundary_differ(matrix_entry):
        gaps.append("positive 和 boundary 必须使用不同考题")

    # 5) negative 必须为 out_of_scope
    if rules.get("negative_must_be_out_of_scope") and matrix_entry.get("negative", {}).get("result") == "pass":
        if not _negative_is_out_of_scope(matrix_entry):
            gaps.append("negative-control case 的 relation_to_patch 应标记为 negative_out_of_scope")

    # 6) 机制类覆盖（patch 级别，不从 profile 继承）
    min_mechanisms = rules.get("min_distinct_mechanisms", 0)
    mechanism_count = _count_patch_level_mechanisms(patch, matrix_entry, all_entries)
    if mechanism_count < min_mechanisms:
        gaps.append(
            f"patch 级别至少覆盖 {min_mechanisms} 个机制类，当前 {mechanism_count} 个"
        )
    details["patch_mechanisms"] = mechanism_count

    # 7) 负控证据链
    neg_rules = rules.get("negative_control", {})
    if neg_rules.get("requires_structured_evidence"):
        neg = matrix_entry.get("negative", {})
        evidence = neg.get("evidence") if isinstance(neg.get("evidence"), dict) else {}
        for field in neg_rules.get("required_evidence_fields", []):
            if not evidence.get(field):
                gaps.append(f"negative evidence 缺少必填字段：{field}")

    # 8) 禁止标签检查（真正读取 failure_labels.json）
    forbidden_gaps = _check_forbidden_labels(patch, rules)
    gaps.extend(forbidden_gaps)

    # 9) stable 专属：stable 必须 fail-closed，policy 配错不能静默跳过门禁。
    if target_status == "stable":
        stable_reqs = rules.get("stable_evidence")
        if not isinstance(stable_reqs, dict):
            gaps.append("promotion policy 缺少 stable_evidence 配置")
            stable_reqs = {}
        if stable_reqs.get("required") is not True:
            gaps.append("promotion policy 未启用 stable_evidence.required")

        evidence = patch.get("stable_evidence")
        if not isinstance(evidence, dict):
            gaps.append("stable 状态必须提供 stable_evidence 对象")
            evidence = {}

        min_nc_runs = rules.get("repetition", {}).get("min_negative_control_runs", 0)
        nc_runs = evidence.get("negative_control_runs")
        if not isinstance(nc_runs, list):
            gaps.append("stable_evidence.negative_control_runs 必须是数组")
            nc_runs = []
        group_ids = [item.get("experiment_group_id") for item in nc_runs if isinstance(item, dict)]
        if len(group_ids) != len(set(group_ids)) or any(not isinstance(gid, str) or not gid.strip() for gid in group_ids):
            gaps.append("stable 负控必须使用唯一且非空的 experiment_group_id")
        if len(set(group_ids)) < min_nc_runs:
            gaps.append(f"stable 至少需要 {min_nc_runs} 组独立负控，当前 {len(set(group_ids))} 组")

        retests = evidence.get("failure_fix_retests")
        if rules.get("requires_failure_fix_retest") and (not isinstance(retests, list) or not retests):
            gaps.append("需要至少 1 次失败修复重测记录 (failure_fix_retests)")

        competition = evidence.get("competition_validation_records")
        if (stable_reqs.get("requires_patch_level_competition_record") or rules.get("requires_competition_verified")) and (not isinstance(competition, list) or not competition):
            gaps.append("需要至少 1 条 Patch 级比赛验证记录 (competition_validation_records)")

        approval = evidence.get("human_approval_record")
        if stable_reqs.get("requires_digest_bound_human_approval") or rules.get("requires_human_approval"):
            details["human_approval_required"] = True
            if not isinstance(approval, dict):
                gaps.append("需要与证据摘要绑定的 human_approval_record 人工批准记录")
            else:
                policy_version = policy.get("policy_version")
                if not isinstance(policy_version, str) or not policy_version.strip():
                    gaps.append("promotion policy 缺少用于 stable evidence 的 policy_version")
                    policy_version = "<missing>"
                expected_digest = stable_evidence_digest(
                    patch,
                    evidence,
                    patch.get("_resolved_patch_sha256", ""),
                    patch.get("_resolved_inner_sha256s", {}),
                    policy_version=policy_version,
                )
                reviewer = approval.get("reviewer", approval.get("approved_by", ""))
                if approval.get("patch_id") not in (None, pid):
                    gaps.append("人工批准记录 patch_id 与当前 Patch 不一致")
                if approval.get("target_status") not in (None, "stable"):
                    gaps.append("人工批准记录 target_status 必须为 stable")
                if approval.get("policy_version") != policy_version:
                    gaps.append(
                        f"人工批准记录 policy_version 必须与当前策略一致（当前为 {policy_version}）"
                    )
                if approval.get("decision") not in (None, "approved"):
                    gaps.append("人工批准记录 decision 必须为 approved")
                if not isinstance(reviewer, str) or not reviewer.strip():
                    gaps.append("人工批准记录 reviewer/approved_by 不能为空")
                if approval.get("evidence_digest") != expected_digest:
                    gaps.append(f"人工批准记录的 evidence_digest 不匹配（期望 {expected_digest}）")
        details["stable_evidence_required"] = True

    # 10) diagnosis schema 版本要求
    diag_req = policy.get("diagnosis_schema_requirements", {})
    min_version = diag_req.get("minimum_schema_version", "1.0.0")
    details["minimum_diagnosis_schema_version"] = min_version
    details["legacy_evidence_cutoff"] = diag_req.get("legacy_evidence_cutoff")

    eligible = len(gaps) == 0
    return EligibilityReport(
        patch_id=pid,
        current_status=patch.get("status", "draft"),
        target_status=target_status,
        eligible=eligible,
        gaps=gaps,
        details=details,
    )


def evaluate_full(
    patch: dict[str, Any],
    matrix_entry: dict[str, Any],
    policy: dict[str, Any],
    *,
    all_matrix_entries: dict[str, dict[str, Any]] | None = None,
) -> FullEligibilityReport:
    """评估当前状态有效性 + 下一级状态差距。"""
    current_status = patch.get("status", "draft")

    # 当前状态验证
    current_report = evaluate_status_eligibility(
        patch, matrix_entry, policy, current_status,
        all_matrix_entries=all_matrix_entries,
    )

    # 下一级状态差距
    next_s = _next_status(current_status)
    if next_s:
        next_report = evaluate_status_eligibility(
            patch, matrix_entry, policy, next_s,
            all_matrix_entries=all_matrix_entries,
        )
    else:
        next_report = None

    return FullEligibilityReport(
        patch_id=patch.get("patch_id", "<unknown>"),
        current_status=current_status,
        current_status_valid=current_report.eligible,
        current_gaps=current_report.gaps,
        next_status=next_s,
        next_status_eligible=next_report.eligible if next_report else None,
        gaps_to_next_status=next_report.gaps if next_report else [],
        details={
            "current": current_report.details,
            "next": next_report.details if next_report else None,
        },
    )
