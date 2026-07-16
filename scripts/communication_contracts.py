"""Gate 0-2 面向读者的模型沟通合同。"""

from __future__ import annotations

import re
from typing import Any, Mapping


RESULT_ROLES = {
    "final_decision",
    "candidate_filter",
    "parameter_input",
    "constraint_input",
    "diagnostic_only",
    "explanation_only",
}


def _non_empty_strings(value: object, label: str, errors: list[str], *, required: bool = True) -> None:
    if not required and value is None:
        return
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{label} 必须是非空字符串数组")


def validate_gate_communication(
    gate: int,
    artifact: Mapping[str, Any],
    *,
    diagnosis_sha256: str | None = None,
    proposed_result_role: str | None = None,
) -> list[str]:
    """验证冻结沟通合同要求，保持数值和论文验证职责分离。"""
    errors: list[str] = []
    if gate == 0:
        ambiguities = artifact.get("ambiguities")
        if not isinstance(ambiguities, list):
            errors.append("Gate 0 缺少 ambiguities")
        elif any(
            not isinstance(item, Mapping)
            or not all(isinstance(item.get(field), str) and item[field].strip() for field in ("ambiguity_id", "question", "impact", "resolution"))
            for item in ambiguities
        ):
            errors.append("Gate 0 ambiguities 每项必须具备 ambiguity_id、question、impact、resolution")
        tags = artifact.get("capability_tags")
        if not isinstance(tags, list) or any(not isinstance(item, str) or not item.strip() for item in tags):
            errors.append("Gate 0 capability_tags 必须是字符串数组，且仅为 Advisory 标签")
        if artifact.get("proposed_result_role") not in RESULT_ROLES:
            errors.append("Gate 0 proposed_result_role 非法")
    elif gate == 1:
        binding = artifact.get("result_role_binding")
        if not isinstance(binding, Mapping):
            errors.append("Gate 1 缺少 result_role_binding")
        else:
            if not isinstance(binding.get("diagnosis_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", binding["diagnosis_sha256"]):
                errors.append("Gate 1 result_role_binding.diagnosis_sha256 非法")
            elif diagnosis_sha256 is not None and binding["diagnosis_sha256"] != diagnosis_sha256:
                errors.append("Gate 1 result_role_binding.diagnosis_sha256 与 Gate 0 诊断不一致")
            if not isinstance(binding.get("subproblem_id"), str) or not binding["subproblem_id"].strip():
                errors.append("Gate 1 result_role_binding.subproblem_id 不能为空")
            role = binding.get("proposed_role")
            if role not in RESULT_ROLES:
                errors.append("Gate 1 result_role_binding.proposed_role 非法")
            elif proposed_result_role is not None and role != proposed_result_role:
                errors.append("Gate 1 不得自由改写 Gate 0 proposed_result_role")
            if binding.get("confirmation") not in {"confirmed", "revision_required"}:
                errors.append("Gate 1 result_role_binding.confirmation 非法")
        communication = artifact.get("communication")
        if not isinstance(communication, Mapping):
            errors.append("Gate 1 缺少 communication")
        else:
            for field in ("model_id", "reader_model_name", "purpose", "relationship_to_next_subproblem", "reader_summary", "claim_scope"):
                if not isinstance(communication.get(field), str) or not communication[field].strip():
                    errors.append(f"Gate 1 communication.{field} 不能为空")
            _non_empty_strings(communication.get("mechanism_chain"), "Gate 1 communication.mechanism_chain", errors)
            sources = communication.get("parameters_or_weights_source")
            if not isinstance(sources, list) or not sources or any(
                not isinstance(item, Mapping)
                or not all(isinstance(item.get(field), str) and item[field].strip() for field in ("name", "source_type", "source", "uncertainty"))
                for item in sources
            ):
                errors.append("Gate 1 communication.parameters_or_weights_source 必须说明参数或权重来源")
            confusions = communication.get("likely_reader_confusions")
            if not isinstance(confusions, list) or any(not isinstance(item, str) or not item.strip() for item in confusions):
                errors.append("Gate 1 communication.likely_reader_confusions 必须是字符串数组")
    elif gate == 2:
        plan = artifact.get("communication_plan")
        if not isinstance(plan, Mapping):
            errors.append("Gate 2 缺少 communication_plan")
        else:
            subproblems = plan.get("subproblems")
            if not isinstance(subproblems, list) or not subproblems:
                errors.append("Gate 2 communication_plan.subproblems 必须是非空数组")
            else:
                for index, item in enumerate(subproblems, start=1):
                    if not isinstance(item, Mapping):
                        errors.append(f"Gate 2 communication_plan.subproblems[{index}] 必须是对象")
                        continue
                    for field in ("subproblem_id", "expected_reader_takeaway"):
                        if not isinstance(item.get(field), str) or not item[field].strip():
                            errors.append(f"Gate 2 communication_plan.subproblems[{index}].{field} 不能为空")
                    for field in ("essential_equations", "essential_tables", "main_text_details", "appendix_only_details", "technical_report_only_details"):
                        value = item.get(field)
                        if not isinstance(value, list) or any(not isinstance(part, str) or not part.strip() for part in value):
                            errors.append(f"Gate 2 communication_plan.subproblems[{index}].{field} 必须是字符串数组")
                    figures = item.get("figures")
                    if not isinstance(figures, list):
                        errors.append(f"Gate 2 communication_plan.subproblems[{index}].figures 必须是数组")
                    elif any(
                        not isinstance(figure, Mapping)
                        or figure.get("figure_kind") not in {"data", "concept"}
                        or not isinstance(figure.get("question_answered"), str)
                        or not figure["question_answered"].strip()
                        or not isinstance(figure.get("required"), bool)
                        or (figure.get("figure_kind") == "data" and not isinstance(figure.get("source_artifact"), str))
                        for figure in figures
                    ):
                        errors.append(f"Gate 2 communication_plan.subproblems[{index}].figures 缺少图表职责或数据来源")
    return errors
