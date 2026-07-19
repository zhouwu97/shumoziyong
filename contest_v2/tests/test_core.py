from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from contest_v2.result_ledger import (
    ResultEntry,
    ResultLedger,
    build_ledger,
    load_json,
    result_digest,
    stable_json_bytes,
    validate_result,
    verification_status,
)
from contest_v2.status import derive_status
from contest_v2.typst_values import _escape, render_typst
from contest_v2.verify_package import package, verify


def metric(value=100.0, unit="元", *, scale=1, decimals=2, suffix="元"):
    return {"value": value, "unit": unit, "format": {"scale": scale, "decimals": decimals, "suffix": suffix}}


def result(question_id="q1", value=100.0):
    return {
        "question_id": question_id,
        "status": "complete",
        "metrics": {"total_profit": metric(value)},
        "check_requests": [{"id": "hard_constraints", "kind": "constraint_recalculation"}],
        "tables": [],
        "figures": [],
        "attachments": [],
        "warnings": [],
    }


def make_run(root: Path, *, standard: bool = False) -> Path:
    run = root / "run"
    qdir = run / "questions" / "q1"
    (qdir / "results").mkdir(parents=True)
    (run / "paper" / "generated").mkdir(parents=True)
    question = {
        "id": "q1",
        "title": "测试问题",
        "required": True,
        "checker": "questions/q1/checker.py",
        "required_checks": ["held_out_evaluation"] if standard else [],
        "recommended_checks": ["risk_sensitivity"] if standard else [],
    }
    contest = {
        "version": "2.0",
        "contest_id": "fixture",
        "mode": "contest_standard" if standard else "contest_fast",
        "question_ids": ["q1"],
        "required_materials": [],
        "required_attachments": [],
    }
    (run / "contest.json").write_bytes(stable_json_bytes(contest))
    (qdir / "question.json").write_bytes(stable_json_bytes(question))
    (qdir / "model.md").write_text("# 模型\n\n目标函数与约束。\n", encoding="utf-8")
    (qdir / "run.py").write_text("# fixture\n", encoding="utf-8")
    (qdir / "check.md").write_text("# 检查\n\n完成。\n", encoding="utf-8")
    (qdir / "paper.typ").write_text('#import "../../paper/generated/results.typ": *\n= 问题一\n利润为 #q1-total-profit。\n', encoding="utf-8")
    (qdir / "results" / "result.json").write_bytes(stable_json_bytes(result()))
    checks = {"hard_constraints": {"status": "passed", "summary": "约束违规数为 0"}}
    if standard:
        checks["held_out_evaluation"] = {"status": "passed", "summary": "留出集完成"}
    checker = """import argparse, json\nparser=argparse.ArgumentParser(); parser.add_argument('--run-dir'); parser.add_argument('--question-dir'); parser.parse_args()\nprint(json.dumps({'checks': %s}, ensure_ascii=False))\n""" % repr(checks)
    (qdir / "checker.py").write_text(checker, encoding="utf-8")
    (run / "paper" / "main.typ").write_text(
        '#include "generated/results.typ"\n#set page(paper: "a4")\n#set text(font: ("Microsoft YaHei", "SimSun"), lang: "zh")\n= 测试论文\n#include "../questions/q1/paper.typ"\n',
        encoding="utf-8",
    )
    return run


def test_valid_result_supports_integer_float_unit_and_scale():
    value = result(value=123456)
    value["metrics"]["count"] = metric(3, "个", scale=1, decimals=0, suffix="个")
    assert validate_result(value)["metrics"]["count"]["value"] == 3


@pytest.mark.parametrize("name", ["TotalProfit", "total-profit", "1profit", "利润"])
def test_invalid_metric_name(name):
    value = result()
    value["metrics"] = {name: metric()}
    with pytest.raises(ValueError, match="非法指标名"):
        validate_result(value)


def test_duplicate_json_key_is_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"question_id":"q1","question_id":"q2"}', encoding="utf-8")
    with pytest.raises(ValueError, match="重复键"):
        load_json(path)


def test_result_cannot_self_verify():
    value = result()
    value["verified"] = True
    with pytest.raises(ValueError, match="禁止自行声明"):
        validate_result(value)


def test_digest_and_stale_detection(tmp_path):
    value = result()
    verification = tmp_path / "verification.json"
    verification.write_bytes(stable_json_bytes({"checked_result_digest": result_digest(value), "checks": {"hard_constraints": {"status": "passed"}, "result_integrity": {"status": "passed"}, "declared_resources": {"status": "passed"}}}))
    assert verification_status(value, verification) == "verified"
    changed = result(value=101.0)
    assert verification_status(changed, verification) == "stale"


def test_any_executed_check_failure_makes_verification_failed(tmp_path):
    value = result()
    verification = tmp_path / "verification.json"
    verification.write_bytes(
        stable_json_bytes(
            {
                "checked_result_digest": result_digest(value),
                "checks": {
                    "hard_constraints": {"status": "passed"},
                    "declared_resources": {"status": "failed"},
                },
            }
        )
    )
    assert verification_status(value, verification) == "failed"


def test_empty_verification_snapshot_cannot_pass(tmp_path):
    value = result()
    value["check_requests"] = []
    verification = tmp_path / "verification.json"
    verification.write_bytes(stable_json_bytes({"checked_result_digest": result_digest(value), "checks": {}}))
    assert verification_status(value, verification) == "failed"


@pytest.mark.parametrize(
    ("verification", "expected"),
    [
        (None, "unchecked"),
        ({"checked_result_digest": "sha256:bad", "checks": {}}, "stale"),
        ({"checked_result_digest": None, "checks": {"hard_constraints": {"status": "failed"}}}, "failed"),
    ],
)
def test_verification_states(tmp_path, verification, expected):
    value = result()
    path = tmp_path / "verification.json"
    if verification is not None:
        if verification["checked_result_digest"] is None:
            verification["checked_result_digest"] = result_digest(value)
        path.write_bytes(stable_json_bytes(verification))
    assert verification_status(value, path) == expected


def test_typst_escape_and_deterministic_output():
    ledger = ResultLedger("x", [ResultEntry("q1", "note", 'a"b\\c\n', "", {}, 'a"b\\c\n', "verified")])
    first = render_typst(ledger)
    second = render_typst(ledger)
    assert first == second
    assert first.startswith("// AUTO-GENERATED. DO NOT EDIT.")
    assert '\\"' in _escape('"')


def test_typst_name_collision_is_rejected():
    ledger = ResultLedger(
        "x",
        [
            ResultEntry("q1", "a_b", 1, "", {}, "1", "verified"),
            ResultEntry("q1", "a__b", 2, "", {}, "2", "verified"),
        ],
    )
    with pytest.raises(ValueError, match="名称冲突"):
        render_typst(ledger)


def test_ledger_is_full_rebuild_and_byte_deterministic(tmp_path):
    run = make_run(tmp_path)
    value = result()
    verification = {"checked_result_digest": result_digest(value), "checks": {"hard_constraints": {"status": "passed"}}}
    (run / "questions/q1/results/verification.json").write_bytes(stable_json_bytes(verification))
    first = build_ledger(run)
    second = build_ledger(run)
    assert stable_json_bytes(first.to_dict()) == stable_json_bytes(second.to_dict())
    assert "append_only" not in first.to_dict()


def test_fast_and_standard_difference(tmp_path):
    fast = make_run(tmp_path / "fast", standard=False)
    fast_report = verify(fast, "contest_fast", compile_pdf=False)
    assert fast_report["status"] == "passed"
    standard = make_run(tmp_path / "standard", standard=True)
    standard_report = verify(standard, "contest_standard", compile_pdf=False)
    assert standard_report["status"] == "passed"
    assert standard_report["summary"]["warnings"] == 1


def test_question_json_is_the_only_question_config_source(tmp_path):
    run = make_run(tmp_path, standard=False)
    question_path = run / "questions/q1/question.json"
    question = load_json(question_path)
    question["required_checks"] = ["held_out_evaluation"]
    question_path.write_bytes(stable_json_bytes(question))
    report = verify(run, "contest_standard", compile_pdf=False)
    assert report["status"] == "failed"
    verification = load_json(run / "questions/q1/results/verification.json")
    assert verification["checks"]["held_out_evaluation"]["status"] == "failed"


def test_embedded_question_config_is_rejected(tmp_path):
    run = make_run(tmp_path)
    contest_path = run / "contest.json"
    contest = load_json(contest_path)
    contest["questions"] = [load_json(run / "questions/q1/question.json")]
    contest_path.write_bytes(stable_json_bytes(contest))
    report = verify(run, "contest_fast", compile_pdf=False)
    assert report["status"] == "failed"
    assert any(item["code"] == "questions_invalid" for item in report["issues"])


def test_status_is_dynamic_and_detects_stale(tmp_path):
    run = make_run(tmp_path)
    assert derive_status(run)["questions"]["q1"]["verification"] == "unchecked"
    assert verify(run, "contest_fast", compile_pdf=False)["status"] == "passed"
    assert derive_status(run)["ledger"] == "ready"
    changed = result(value=999)
    (run / "questions/q1/results/result.json").write_bytes(stable_json_bytes(changed))
    status = derive_status(run)
    assert status["questions"]["q1"]["verification"] == "stale"
    assert status["ledger"] == "stale"


def test_pdf_and_package_exclusions(tmp_path):
    run = make_run(tmp_path)
    report = verify(run, "contest_fast", compile_pdf=True)
    assert report["status"] == "passed", report["issues"]
    (run / ".env").write_text("SECRET=x", encoding="utf-8")
    (run / "cache").mkdir()
    (run / "cache/tmp.txt").write_text("tmp", encoding="utf-8")
    (run / "questions/q1/__pycache__").mkdir()
    (run / "questions/q1/__pycache__/x.pyc").write_bytes(b"x")
    (run / "review_handoff_round2").mkdir()
    (run / "review_handoff_round2/prompt.md").write_text("internal", encoding="utf-8")
    packaged = package(run)
    with zipfile.ZipFile(run / packaged["support_zip"]) as archive:
        names = archive.namelist()
    assert ".env" not in names
    assert not any("cache" in name or "__pycache__" in name for name in names)
    assert not any("review_handoff" in name for name in names)
    assert (run / packaged["submission_pdf"]).is_file()
