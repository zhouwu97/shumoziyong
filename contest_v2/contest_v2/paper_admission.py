"""Paper Admission 与作者侧学习上下文的轻量机器校验。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ADMISSION_ITEM_IDS = (
    "problem_requirement",
    "final_answer",
    "variables_and_parameters",
    "mathematical_expression",
    "solution_or_derivation",
    "core_results",
    "baseline_or_comparison",
    "validity_checks",
    "figure_or_table_evidence",
    "result_interpretation",
    "scope_and_limitations",
)

CONDITIONAL_ITEM_IDS = {"baseline_or_comparison"}

COVERAGE_ITEM_IDS = (
    "problem_response",
    "model_formula_group",
    "solution_algorithm",
    "result_evidence",
    "validation",
    "interpretation_and_scope",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少{label}：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是 JSON 对象")
    return value


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_text_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonempty_text(item) for item in value)


def _registry_rules(registry: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rules = registry.get("review_rules")
    if not isinstance(rules, list):
        raise ValueError("优秀论文评审注册表缺少 review_rules")
    indexed: dict[str, Mapping[str, Any]] = {}
    for rule in rules:
        if not isinstance(rule, dict) or not _nonempty_text(rule.get("rule_id")):
            raise ValueError("优秀论文评审注册表包含无效规则")
        indexed[str(rule["rule_id"])] = rule
    return indexed


def _registry_sources(registry: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    sources = registry.get("sources")
    if not isinstance(sources, list):
        raise ValueError("优秀论文评审注册表缺少 sources")
    indexed: dict[str, Mapping[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict) or not _nonempty_text(source.get("paper_id")):
            raise ValueError("优秀论文评审注册表包含无效来源")
        indexed[str(source["paper_id"])] = source
    return indexed


def _registry_patterns(registry: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    patterns = registry.get("verified_cross_problem_patterns")
    if not isinstance(patterns, list):
        raise ValueError("优秀论文评审注册表缺少 verified_cross_problem_patterns")
    indexed: dict[str, Mapping[str, Any]] = {}
    for pattern in patterns:
        if not isinstance(pattern, dict) or not _nonempty_text(pattern.get("pattern_id")):
            raise ValueError("优秀论文评审注册表包含无效跨题模式")
        indexed[str(pattern["pattern_id"])] = pattern
    return indexed


def validate_learning_context(
    context: Mapping[str, Any],
    registry: Mapping[str, Any],
    question_ids: list[str],
) -> None:
    """验证学习资产只以允许方式进入作者建模和写作。"""

    if context.get("artifact_type") != "contest_v2_learning_context":
        raise ValueError("learning_context artifact_type 无效")
    if context.get("registry_version") != registry.get("version"):
        raise ValueError("learning_context 使用的评审注册表版本已过期")
    if not _nonempty_text_list(context.get("problem_types")):
        raise ValueError("learning_context 必须声明至少一个题型")

    rules = _registry_rules(registry)
    sources = _registry_sources(registry)
    patterns = _registry_patterns(registry)
    selected_keys: set[str] = set()

    selected_rules = context.get("selected_rules")
    if not isinstance(selected_rules, list):
        raise ValueError("learning_context.selected_rules 必须是列表")
    for selected in selected_rules:
        if not isinstance(selected, dict):
            raise ValueError("selected_rules 包含无效条目")
        rule_id = str(selected.get("rule_id", ""))
        rule = rules.get(rule_id)
        if rule is None:
            raise ValueError(f"learning_context 引用了未知规则：{rule_id}")
        if rule.get("status") != "global_active":
            raise ValueError(f"作者侧不得加载非 global_active 规则：{rule_id}")
        if not _nonempty_text(selected.get("reason")) or not _nonempty_text(selected.get("planned_use")):
            raise ValueError(f"学习规则缺少选择理由或计划用途：{rule_id}")
        selected_keys.add(f"rule:{rule_id}")

    selected_patterns = context.get("selected_patterns")
    if not isinstance(selected_patterns, list):
        raise ValueError("learning_context.selected_patterns 必须是列表")
    for selected in selected_patterns:
        if not isinstance(selected, dict):
            raise ValueError("selected_patterns 包含无效条目")
        source_id = str(selected.get("source", ""))
        pattern_id = str(selected.get("pattern_id", ""))
        source = sources.get(source_id)
        if source is None:
            raise ValueError(f"learning_context 引用了未知论文来源：{source_id}")
        allowed = source.get("allowed_use")
        if source.get("claim_verification_status") != "verified" or not isinstance(allowed, list) or "cross_problem_method_pattern" not in allowed:
            raise ValueError(f"作者侧不得加载未核验或未授权的跨题模式：{source_id}")
        registered_pattern = patterns.get(pattern_id)
        if registered_pattern is None or registered_pattern.get("source") != source_id or registered_pattern.get("status") != "verified":
            raise ValueError(f"作者侧不得加载未登记或未核验的跨题模式：{pattern_id}")
        if not _nonempty_text(selected.get("pattern")) or not _nonempty_text(selected.get("reason")) or not _nonempty_text(selected.get("planned_use")):
            raise ValueError(f"跨题模式缺少模式、理由或计划用途：{source_id}")
        selected_keys.add(f"pattern:{source_id}:{pattern_id}")

    if not selected_keys:
        raise ValueError("learning_context 必须选择至少一个 global_active 规则或已核验跨题模式")

    excluded = context.get("excluded")
    if not isinstance(excluded, list) or not any(
        isinstance(item, dict)
        and item.get("exclusion_type") == "same_problem_material"
        and _nonempty_text(item.get("reason"))
        for item in excluded
    ):
        raise ValueError("learning_context 必须显式排除同题答案、题解和优秀论文")

    coverage_plan = context.get("section_coverage_plan")
    if not isinstance(coverage_plan, dict):
        raise ValueError("learning_context 缺少 section_coverage_plan")
    for qid in question_ids:
        question = coverage_plan.get(qid)
        if not isinstance(question, dict):
            raise ValueError(f"章节覆盖计划缺少必答问题：{qid}")
        for item_id in COVERAGE_ITEM_IDS:
            item = question.get(item_id)
            if not isinstance(item, dict):
                raise ValueError(f"{qid} 章节覆盖计划缺少：{item_id}")
            if item.get("status") != "READY" or not _nonempty_text_list(item.get("prepared_material")):
                raise ValueError(f"{qid} 章节材料未准备完成：{item_id}")

    application_record = context.get("application_record")
    if not isinstance(application_record, list):
        raise ValueError("learning_context.application_record 必须是列表")
    applied_keys: set[str] = set()
    for record in application_record:
        if not isinstance(record, dict) or not _nonempty_text(record.get("asset_key")):
            raise ValueError("学习资产应用记录包含无效条目")
        asset_key = str(record["asset_key"])
        adopted = record.get("adopted")
        if adopted is True:
            if not _nonempty_text_list(record.get("actual_locations")):
                raise ValueError(f"已采用学习资产缺少论文落点：{asset_key}")
        elif adopted is False:
            if not _nonempty_text(record.get("reason")):
                raise ValueError(f"未采用学习资产缺少拒绝理由：{asset_key}")
        else:
            raise ValueError(f"学习资产应用记录 adopted 必须是布尔值：{asset_key}")
        applied_keys.add(asset_key)
    if applied_keys != selected_keys:
        missing = sorted(selected_keys - applied_keys)
        extra = sorted(applied_keys - selected_keys)
        raise ValueError(f"学习资产应用记录与选择结果不一致：missing={missing}, extra={extra}")


def validate_paper_admission(
    admission: Mapping[str, Any],
    *,
    actual_pdf_digest: str,
    question_ids: list[str],
    learning_context: Mapping[str, Any],
    learning_context_digest: str,
    registry: Mapping[str, Any],
) -> None:
    """验证准入状态、逐问矩阵、学习上下文和摘要绑定。"""

    if admission.get("artifact_type") != "contest_v2_paper_admission":
        raise ValueError("Paper Admission artifact_type 无效")
    if admission.get("engineering_verification") != "pass":
        raise ValueError("工程验收未通过，禁止进入论文评审")
    if admission.get("paper_admission") != "pass":
        raise ValueError("Paper Admission 未通过，当前论文只能继续作者侧大修")
    if admission.get("paper_type") != "submission_candidate":
        raise ValueError("paper_type 不是 submission_candidate，禁止构建 Reviewer 交接包")

    expected_pdf_digest = str(admission.get("pdf_sha256", "")).removeprefix("sha256:")
    if expected_pdf_digest != actual_pdf_digest:
        raise ValueError("Paper Admission 已过期：记录的 PDF 摘要与当前论文不一致")
    expected_context_digest = str(admission.get("learning_context_sha256", "")).removeprefix("sha256:")
    if expected_context_digest != learning_context_digest:
        raise ValueError("Paper Admission 已过期：学习上下文摘要与当前文件不一致")

    blockers = admission.get("direct_blockers")
    if not isinstance(blockers, list):
        raise ValueError("Paper Admission.direct_blockers 必须是列表")
    if blockers:
        raise ValueError("Paper Admission 存在直接阻断项")

    questions = admission.get("questions")
    if not isinstance(questions, dict):
        raise ValueError("Paper Admission 缺少 questions 准入矩阵")
    for qid in question_ids:
        question = questions.get(qid)
        if not isinstance(question, dict):
            raise ValueError(f"Paper Admission 缺少必答问题：{qid}")
        items = question.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"Paper Admission 缺少 {qid}.items")
        missing_items = [item_id for item_id in ADMISSION_ITEM_IDS if item_id not in items]
        if missing_items:
            raise ValueError(f"{qid} 准入矩阵缺少检查项：{missing_items}")
        for item_id in ADMISSION_ITEM_IDS:
            item = items[item_id]
            if not isinstance(item, dict):
                raise ValueError(f"{qid}.{item_id} 必须是对象")
            status = item.get("status")
            if status in {"PARTIAL", "MISSING"}:
                raise ValueError(f"{qid}.{item_id} 仍为 {status}")
            if not _nonempty_text_list(item.get("evidence")):
                raise ValueError(f"{qid}.{item_id} 缺少可定位证据")
            if item_id in CONDITIONAL_ITEM_IDS:
                required = item.get("required")
                if required is True and status != "PASS":
                    raise ValueError(f"{qid}.{item_id} 为条件必需项但未 PASS")
                if required is False and status == "NOT_APPLICABLE":
                    if not _nonempty_text(item.get("not_applicable_reason")):
                        raise ValueError(f"{qid}.{item_id} NOT_APPLICABLE 缺少理由")
                elif status != "PASS":
                    raise ValueError(f"{qid}.{item_id} 状态无效")
                if not isinstance(required, bool):
                    raise ValueError(f"{qid}.{item_id}.required 必须是布尔值")
            elif status != "PASS":
                raise ValueError(f"{qid}.{item_id} 是必需项，状态必须为 PASS")

    validate_learning_context(learning_context, registry, question_ids)


def require_current_paper_admission(
    run_dir: Path,
    paper_path: Path,
    registry_path: Path,
) -> dict[str, Any]:
    """读取并验证当前 PDF 对应的完整 Paper Admission。"""

    admission = _load_object(run_dir / "review/paper_admission.json", " Paper Admission")
    if admission.get("paper_admission") != "pass":
        raise ValueError("Paper Admission 未通过，当前论文只能继续作者侧大修")
    if admission.get("paper_type") != "submission_candidate":
        raise ValueError("paper_type 不是 submission_candidate，禁止构建 Reviewer 交接包")
    contest = _load_object(run_dir / "contest.json", "比赛配置")
    question_ids = contest.get("question_ids")
    if not isinstance(question_ids, list) or not question_ids or not all(_nonempty_text(qid) for qid in question_ids):
        raise ValueError("contest.json.question_ids 无效")

    context_relative = admission.get("learning_context_path")
    if not _nonempty_text(context_relative):
        raise ValueError("Paper Admission 缺少 learning_context_path")
    context_path = (run_dir / str(context_relative)).resolve()
    if run_dir.resolve() not in context_path.parents:
        raise ValueError("learning_context_path 必须位于当前运行目录内")
    learning_context = _load_object(context_path, "学习上下文")
    registry = _load_object(registry_path, "优秀论文评审注册表")

    validate_paper_admission(
        admission,
        actual_pdf_digest=sha256(paper_path),
        question_ids=[str(qid) for qid in question_ids],
        learning_context=learning_context,
        learning_context_digest=sha256(context_path),
        registry=registry,
    )
    return admission
