from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

import render_submission as renderer  # noqa: E402
from check_humanization_diff import check_humanization_diff  # noqa: E402
from check_paper_source import sha256_file  # noqa: E402
from verify_submission import check_references, verify_submission  # noqa: E402


PROFILE = ROOT / "paper_profiles" / "cumcm_academic_v1.json"
TEMPLATE = ROOT / "paper_templates" / "cumcm_typst"


SOURCE_TEXT = """= 摘要
本文建立离散事件模型并比较候选策略，正式结果完成 120 件产品。

= 问题重述
研究设备调度与加工任务分配问题。

= 问题分析
任务包含资源冲突、时间约束与策略比较。

= 模型假设
设备参数在单次仿真中保持不变。

= 符号说明
变量 $N$ 表示完成件数。

= 模型建立
目标函数为 $ max N $ <eq-objective>，正文引用 @eq-objective。

= 算法设计
使用确定性事件推进求解候选策略。

= 结果与机理分析
C001：正式结果完成 120 件产品。

= 模型检验
使用约束残差和独立复算检查模型。

= 模型评价
结论只适用于给定配置和候选范围。

= 结论
策略在给定条件下完成 120 件产品。

= 参考文献
离散事件定义见文献 [1]。
#reference-entry(1, [测试参考文献条目。])
"""


def test_reference_check_accepts_typst_escaped_citation() -> None:
    text = """= 参考文献
正文引用写作 \\[1\\]。
#reference-entry(1, [测试参考文献条目。])
"""

    assert check_references(text) == []


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_pdf_compile(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    fitz = pytest.importorskip("fitz")
    output_pdf = Path(command[-1])
    document = fitz.open()
    page = document.new_page(width=595.276, height=841.89)
    page.insert_text((72, 72), "submission verification fixture")
    document.save(output_pdf)
    document.close()
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def build_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    main = source_dir / "main.typ"
    main.write_text(SOURCE_TEXT, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    output_pdf = artifacts / "submission.pdf"
    attestation = artifacts / "paper_render_attestation.json"
    monkeypatch.setattr(renderer, "renderer_version", lambda _: "typst 0.13.1")
    monkeypatch.setattr(renderer.subprocess, "run", make_pdf_compile)
    renderer.render_submission(
        profile_path=PROFILE,
        template_dir=TEMPLATE,
        source_dir=source_dir,
        source_entry=Path("main.typ"),
        output_pdf=output_pdf,
        attestation_path=attestation,
    )

    humanization_path = artifacts / "paper_humanization_report.json"
    write_json(humanization_path, check_humanization_diff(main, main))

    project_root = tmp_path / "project"
    result_data = project_root / "results/data.json"
    write_json(result_data, {"completed": 120})
    claim_bindings = artifacts / "claim_bindings.json"
    write_json(
        claim_bindings,
        {
            "claims": [
                {
                    "claim_id": "C001",
                    "source_file": "results/data.json",
                    "json_pointer": "/completed",
                    "raw_value": 120,
                    "display_value": "120",
                    "unit": "件",
                    "rounding_rule": "integer",
                    "conclusion_tokens": ["完成"],
                }
            ]
        },
    )

    model_route = artifacts / "model_route.json"
    result_report = artifacts / "result_report.json"
    write_json(model_route, {"objective": "maximize N"})
    write_json(result_report, {"completed": 120})
    passed_check = {"status": "passed", "evidence": ["fixture"], "issues": []}
    model_consistency = artifacts / "model_text_consistency_report.json"
    write_json(
        model_consistency,
        {
            "schema_version": "1.0.0",
            "paper_source_sha256": sha256_file(main),
            "model_route": "model_route.json",
            "model_route_sha256": sha256_file(model_route),
            "result_report": "result_report.json",
            "result_report_sha256": sha256_file(result_report),
            "checks": {
                "objective_directions": passed_check,
                "lexicographic_order": passed_check,
                "variables": passed_check,
                "formulas": passed_check,
                "constraints": passed_check,
                "claim_scope": passed_check,
            },
            "status": "passed",
        },
    )
    visual_review = artifacts / "visual_review.json"
    write_json(
        visual_review,
        {
            "schema_version": "1.0.0",
            "pdf_sha256": sha256_file(output_pdf),
            "page_count": 1,
            "reviewed_pages": [1],
            "reviewer": "fixture-visual-reviewer",
            "issues": [],
            "status": "passed",
        },
    )
    return {
        "main_path": main,
        "profile_path": PROFILE,
        "template_dir": TEMPLATE,
        "render_attestation_path": attestation,
        "humanization_report_path": humanization_path,
        "claim_bindings_path": claim_bindings,
        "claims_project_root": project_root,
        "model_consistency_path": model_consistency,
        "visual_review_path": visual_review,
        "reports_dir": tmp_path / "reports",
        "output_pdf": output_pdf,
    }


def test_verify_submission_passes_complete_bound_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = build_fixture(tmp_path, monkeypatch)
    output_pdf = paths.pop("output_pdf")

    report = verify_submission(**paths)

    assert output_pdf.is_file()
    assert report["status"] == "passed"
    assert report["summary"]["failed"] == 0
    assert (paths["reports_dir"] / "VERIFY_REPORT.md").is_file()
    assert (paths["reports_dir"] / "pages/page-001.png").is_file()


def test_incomplete_visual_review_blocks_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = build_fixture(tmp_path, monkeypatch)
    paths.pop("output_pdf")
    review = json.loads(paths["visual_review_path"].read_text(encoding="utf-8"))
    review["reviewed_pages"] = [2]
    write_json(paths["visual_review_path"], review)

    report = verify_submission(**paths)

    assert report["status"] == "failed"
    assert report["checks"]["visual_review_record"]["status"] == "failed"


def test_pdf_hash_drift_blocks_render_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = build_fixture(tmp_path, monkeypatch)
    output_pdf = paths.pop("output_pdf")
    output_pdf.write_bytes(output_pdf.read_bytes() + b"drift")

    report = verify_submission(**paths)

    assert report["status"] == "failed"
    assert report["checks"]["render_attestation"]["status"] == "failed"
