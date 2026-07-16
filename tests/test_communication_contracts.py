"""Gate 0-2 模型沟通合同的回归测试。"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from communication_contracts import validate_gate_communication  # noqa: E402


def test_gate_zero_role_is_proposal_and_tags_remain_advisory() -> None:
    """Gate 0 允许空标签集，但结果角色必须来自受控枚举。"""
    artifact = {
        "ambiguities": [],
        "capability_tags": [],
        "proposed_result_role": "candidate_filter",
    }
    assert validate_gate_communication(0, artifact) == []


def test_gate_one_cannot_silently_change_gate_zero_role() -> None:
    """Gate 1 只确认 Gate 0 提议，改变角色必须走 revision fork。"""
    artifact = {
        "result_role_binding": {
            "diagnosis_sha256": "a" * 64,
            "subproblem_id": "Q1",
            "proposed_role": "final_decision",
            "confirmation": "revision_required",
        },
        "communication": {
            "model_id": "q1_weighted_score",
            "reader_model_name": "业务加权综合评价模型",
            "purpose": "对候选对象进行排序",
            "mechanism_chain": ["读取数据", "计算指标", "输出排名"],
            "parameters_or_weights_source": [
                {"name": "权重", "source_type": "business_preference", "source": "人工确认", "uncertainty": "需要敏感性分析"}
            ],
            "relationship_to_next_subproblem": "只提供候选分析",
            "reader_summary": "以给定偏好形成可解释排名。",
            "likely_reader_confusions": ["排名不是最终决策"],
            "claim_scope": "仅对历史样本和给定权重成立",
        },
    }
    errors = validate_gate_communication(
        1,
        artifact,
        diagnosis_sha256="a" * 64,
        proposed_result_role="candidate_filter",
    )
    assert any("不得自由改写" in error for error in errors)


def test_gate_two_data_figure_requires_question_and_source() -> None:
    """数据图必须声明回答的问题和来源，不限制论文页数。"""
    artifact = {
        "communication_plan": {
            "subproblems": [
                {
                    "subproblem_id": "Q1",
                    "expected_reader_takeaway": "排名只用于筛选候选对象。",
                    "essential_equations": [],
                    "essential_tables": [],
                    "figures": [{"figure_kind": "data", "question_answered": "", "source_artifact": None, "required": True}],
                    "main_text_details": ["说明排名边界"],
                    "appendix_only_details": [],
                    "technical_report_only_details": [],
                }
            ]
        }
    }
    errors = validate_gate_communication(2, artifact)
    assert any("图表职责" in error for error in errors)

    artifact["communication_plan"]["subproblems"][0]["figures"] = [
        {"figure_kind": "data", "question_answered": "哪些对象进入候选集？", "source_artifact": "results/q1.csv", "required": True}
    ]
    assert validate_gate_communication(2, artifact) == []
