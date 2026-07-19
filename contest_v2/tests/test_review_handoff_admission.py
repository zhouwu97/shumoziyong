from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from contest_v2.paper_admission import (
    ADMISSION_ITEM_IDS,
    COVERAGE_ITEM_IDS,
    require_current_paper_admission,
)


def valid_registry() -> dict:
    return {
        "artifact_type": "excellent_paper_review_standard_registry",
        "version": "1.2.0",
        "sources": [
            {
                "paper_id": "2023_A092",
                "claim_verification_status": "verified",
                "allowed_use": ["cross_problem_method_pattern"],
            }
        ],
        "verified_cross_problem_patterns": [
            {
                "pattern_id": "A092_baseline",
                "source": "2023_A092",
                "status": "verified",
            }
        ],
        "review_rules": [],
    }


def valid_context() -> dict:
    return {
        "artifact_type": "contest_v2_learning_context",
        "registry_version": "1.2.0",
        "problem_types": ["optimization"],
        "selected_rules": [],
        "selected_patterns": [
            {
                "source": "2023_A092",
                "pattern_id": "A092_baseline",
                "pattern": "冻结统一评价口径后比较基线与候选",
                "reason": "本题需要判断优化是否真正改善基线",
                "planned_use": "Q1 基线与候选比较",
            }
        ],
        "excluded": [
            {
                "exclusion_type": "same_problem_material",
                "source": "同题优秀论文、题解和答案",
                "reason": "防止同题泄漏",
            }
        ],
        "section_coverage_plan": {
            "q1": {
                item_id: {"status": "READY", "prepared_material": [f"q1/{item_id}.md"]}
                for item_id in COVERAGE_ITEM_IDS
            }
        },
        "application_record": [
            {
                "asset_key": "pattern:2023_A092:A092_baseline",
                "adopted": True,
                "actual_locations": ["Q1 结果比较表"],
                "reason": "已形成统一口径对照",
            }
        ],
    }


def valid_admission() -> dict:
    items = {
        item_id: {
            "status": "PASS",
            "evidence": [f"p.3 {item_id}"],
            **({"required": True} if item_id == "baseline_or_comparison" else {}),
        }
        for item_id in ADMISSION_ITEM_IDS
    }
    return {
        "artifact_type": "contest_v2_paper_admission",
        "engineering_verification": "pass",
        "paper_admission": "pass",
        "paper_type": "submission_candidate",
        "learning_context_path": "reports/learning_context.json",
        "direct_blockers": [],
        "questions": {"q1": {"items": items}},
    }


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def make_run(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    paper = tmp_path / "paper" / "submission.pdf"
    paper.parent.mkdir(parents=True)
    paper.write_bytes(b"current pdf")
    write_json(tmp_path / "contest.json", {"question_ids": ["q1"]})
    context = valid_context()
    context_path = tmp_path / "reports" / "learning_context.json"
    write_json(context_path, context)
    registry = valid_registry()
    registry_path = tmp_path / "registry.json"
    write_json(registry_path, registry)
    admission = valid_admission()
    write_json(tmp_path / "review" / "paper_admission.json", admission)
    return paper, registry_path, admission, context


def rewrite_admission(tmp_path: Path, admission: dict) -> None:
    write_json(tmp_path / "review" / "paper_admission.json", admission)


def rewrite_context(tmp_path: Path, admission: dict, context: dict) -> None:
    context_path = tmp_path / "reports" / "learning_context.json"
    write_json(context_path, context)
    rewrite_admission(tmp_path, admission)


def test_accepts_complete_current_admission(tmp_path: Path) -> None:
    paper, registry_path, _, _ = make_run(tmp_path)

    admission = require_current_paper_admission(tmp_path, paper, registry_path)

    assert admission["paper_admission"] == "pass"


def test_rejects_failed_admission(tmp_path: Path) -> None:
    paper, registry_path, admission, _ = make_run(tmp_path)
    admission["paper_admission"] = "fail"
    admission["paper_type"] = "technical_report"
    rewrite_admission(tmp_path, admission)

    with pytest.raises(ValueError, match="Paper Admission 未通过"):
        require_current_paper_admission(tmp_path, paper, registry_path)


def test_pdf_changes_do_not_block_content_admission(tmp_path: Path) -> None:
    paper, registry_path, admission, _ = make_run(tmp_path)
    paper.write_bytes(b"updated pdf")
    rewrite_admission(tmp_path, admission)

    assert require_current_paper_admission(tmp_path, paper, registry_path)["paper_admission"] == "pass"


def test_learning_context_changes_do_not_block_content_admission(tmp_path: Path) -> None:
    paper, registry_path, admission, context = make_run(tmp_path)
    context["application_record"][0]["actual_locations"] = ["Q1 结果比较表", "Q1 敏感性分析"]
    rewrite_context(tmp_path, admission, context)

    assert require_current_paper_admission(tmp_path, paper, registry_path)["paper_admission"] == "pass"


@pytest.mark.parametrize("status", ["PARTIAL", "MISSING"])
def test_rejects_incomplete_required_item(tmp_path: Path, status: str) -> None:
    paper, registry_path, admission, _ = make_run(tmp_path)
    admission["questions"]["q1"]["items"]["mathematical_expression"]["status"] = status
    rewrite_admission(tmp_path, admission)

    with pytest.raises(ValueError, match=status):
        require_current_paper_admission(tmp_path, paper, registry_path)


def test_rejects_item_without_evidence(tmp_path: Path) -> None:
    paper, registry_path, admission, _ = make_run(tmp_path)
    admission["questions"]["q1"]["items"]["result_interpretation"]["evidence"] = []
    rewrite_admission(tmp_path, admission)

    with pytest.raises(ValueError, match="缺少可定位证据"):
        require_current_paper_admission(tmp_path, paper, registry_path)


def test_rejects_not_applicable_without_reason(tmp_path: Path) -> None:
    paper, registry_path, admission, _ = make_run(tmp_path)
    baseline = admission["questions"]["q1"]["items"]["baseline_or_comparison"]
    baseline.update({"status": "NOT_APPLICABLE", "required": False})
    rewrite_admission(tmp_path, admission)

    with pytest.raises(ValueError, match="NOT_APPLICABLE 缺少理由"):
        require_current_paper_admission(tmp_path, paper, registry_path)


def test_rejects_direct_blocker(tmp_path: Path) -> None:
    paper, registry_path, admission, _ = make_run(tmp_path)
    admission["direct_blockers"] = ["核心模型未闭合"]
    rewrite_admission(tmp_path, admission)

    with pytest.raises(ValueError, match="直接阻断项"):
        require_current_paper_admission(tmp_path, paper, registry_path)


def test_rejects_non_global_author_rule(tmp_path: Path) -> None:
    paper, registry_path, admission, context = make_run(tmp_path)
    registry = valid_registry()
    registry["review_rules"] = [{"rule_id": "R001", "status": "cross_paper_candidate"}]
    write_json(registry_path, registry)
    context["selected_rules"] = [
        {"rule_id": "R001", "reason": "候选", "planned_use": "Q1"}
    ]
    context["application_record"].append(
        {"asset_key": "rule:R001", "adopted": False, "actual_locations": [], "reason": "证据不足"}
    )
    rewrite_context(tmp_path, admission, context)

    with pytest.raises(ValueError, match="非 global_active"):
        require_current_paper_admission(tmp_path, paper, registry_path)


def test_rejects_incomplete_section_coverage_plan(tmp_path: Path) -> None:
    paper, registry_path, admission, context = make_run(tmp_path)
    broken = deepcopy(context)
    broken["section_coverage_plan"]["q1"]["model_formula_group"]["status"] = "MISSING"
    rewrite_context(tmp_path, admission, broken)

    with pytest.raises(ValueError, match="章节材料未准备完成"):
        require_current_paper_admission(tmp_path, paper, registry_path)
