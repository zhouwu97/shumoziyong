from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

import external_precheck as precheck_module  # noqa: E402
from external_precheck import run_external_precheck, sha256_file  # noqa: E402


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _run(paper: Path, artifacts: Path) -> dict[str, object]:
    return run_external_precheck(
        paper_root=paper,
        report_path=artifacts / "paper_external_precheck_report.json",
        suggestions_path=artifacts / "suggested_repairs.json",
    )


def test_clean_paper_passes_without_mutation_or_upstream_execution(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    artifacts = tmp_path / "artifacts"
    paper.mkdir()
    source = paper / "main.typ"
    source.write_text("= 模型与结果\n本文只陈述当前运行已验证的结论。\n", encoding="utf-8")
    before = sha256_file(source)

    report = _run(paper, artifacts)

    assert report["status"] == "passed"
    assert report["mutation_detected"] is False
    assert report["body_before"] == report["body_after"]
    assert report["upstream_source"]["executed"] is False
    assert report["authority"] == {
        "modify_paper": False,
        "rerun_results": False,
        "decide_gate4_pass": False,
    }
    assert sha256_file(source) == before
    suggestions = _load(artifacts / "suggested_repairs.json")
    assert suggestions["automatic_apply"] is False
    assert suggestions["repairs"] == []


def test_findings_only_create_suggested_repairs(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    artifacts = tmp_path / "artifacts"
    paper.mkdir()
    source = paper / "main.typ"
    source.write_text(
        '= 结果\nTODO：引用 RESULTS_REPORT。\n#figure(image("missing.pdf"))\n',
        encoding="utf-8",
    )
    before = source.read_bytes()

    report = _run(paper, artifacts)

    assert report["status"] == "issues_found"
    assert report["mutation_detected"] is False
    assert {item["code"] for item in report["findings"]} == {
        "placeholder_text",
        "internal_term_leak",
        "missing_image",
        "missing_figure_caption",
    }
    assert source.read_bytes() == before
    assert {path.name for path in artifacts.iterdir()} == {
        "paper_external_precheck_report.json",
        "suggested_repairs.json",
    }
    suggestions = _load(artifacts / "suggested_repairs.json")
    assert len(suggestions["repairs"]) == 4
    assert suggestions["automatic_apply"] is False


def test_latex_image_and_caption_checks_are_read_only(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    source = paper / "main.tex"
    source.write_text(
        "\\section{Results}\n"
        "\\begin{figure}\\includegraphics{absent.pdf}\\end{figure}\n",
        encoding="utf-8",
    )
    before = source.read_bytes()

    report = _run(paper, tmp_path / "artifacts")

    assert {item["code"] for item in report["findings"]} == {
        "missing_image",
        "missing_figure_caption",
    }
    assert source.read_bytes() == before


def test_concurrent_body_change_is_detected_and_blocks(tmp_path: Path, monkeypatch) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    source = paper / "main.typ"
    source.write_text("= 初始正文\n完整内容。\n", encoding="utf-8")
    real_snapshot = precheck_module.snapshot_body
    calls = 0

    def mutating_snapshot(root: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            source.write_text("= 被并发修改\n内容已变化。\n", encoding="utf-8")
        return real_snapshot(root)

    monkeypatch.setattr(precheck_module, "snapshot_body", mutating_snapshot)

    report = _run(paper, tmp_path / "artifacts")

    assert report["status"] == "mutation_detected"
    assert report["mutation_detected"] is True
    assert report["body_before"]["sha256"] != report["body_after"]["sha256"]
    assert any(item["code"] == "paper_body_mutated" for item in report["findings"])


def test_precheck_outputs_match_contract_schemas(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.typ").write_text("= 完整正文\n验证内容。\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    _run(paper, artifacts)
    report = _load(artifacts / "paper_external_precheck_report.json")
    suggestions = _load(artifacts / "suggested_repairs.json")
    report_schema = _load(ROOT / "schemas" / "paper_external_precheck_report.schema.json")
    suggestions_schema = _load(ROOT / "schemas" / "suggested_repairs.schema.json")
    assert not list(Draft202012Validator(report_schema).iter_errors(report))
    assert not list(Draft202012Validator(suggestions_schema).iter_errors(suggestions))
