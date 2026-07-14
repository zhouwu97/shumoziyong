from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from check_claim_bindings import check_bindings, resolve_json_pointer  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_json_pointer_supports_escaped_tokens() -> None:
    payload = {"a/b": {"m~n": [10]}}
    assert resolve_json_pointer(payload, "/a~1b/m~0n/0") == 10


def test_claim_check_accepts_locked_value_unit_and_conclusion(tmp_path: Path) -> None:
    write_json(tmp_path / "results" / "formal_result.json", {"capacity": 33335.925462})
    bindings = tmp_path / "claim_bindings.json"
    write_json(
        bindings,
        {
            "claims": [
                {
                    "claim_id": "q4_capacity",
                    "source_file": "results/formal_result.json",
                    "json_pointer": "/capacity",
                    "raw_value": 33335.925462,
                    "display_value": "33,335.925",
                    "unit": "m³/周",
                    "rounding_rule": "3_decimal",
                    "conclusion_tokens": ["最大产能"],
                }
            ]
        },
    )
    paper = tmp_path / "main.typ"
    paper.write_text(
        "最大产能为 33,335.925 m³/周。<q4_capacity> q4_capacity",
        encoding="utf-8",
    )

    report = check_bindings(bindings, paper, tmp_path)

    assert report["passed"] is True
    assert report["summary"]["claims_checked"] == 1
    assert report["issues"] == []


def test_claim_check_detects_source_tampering_and_paper_drift(tmp_path: Path) -> None:
    write_json(tmp_path / "results.json", {"ratio": 0.126})
    bindings = tmp_path / "claim_bindings.json"
    write_json(
        bindings,
        {
            "claims": [
                {
                    "claim_id": "loss_ratio",
                    "source_file": "results.json",
                    "json_pointer": "/ratio",
                    "raw_value": 0.125,
                    "display_value": "12.50%",
                    "unit": "%",
                    "rounding_rule": "percent_2_decimal",
                }
            ]
        },
    )
    paper = tmp_path / "main.typ"
    paper.write_text("损耗率为 13.00%。loss_ratio", encoding="utf-8")

    report = check_bindings(bindings, paper, tmp_path)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["passed"] is False
    assert "raw_value_mismatch" in codes
    assert "display_value_not_locked" in codes


def test_claim_check_rejects_conflicting_values_for_same_claim(tmp_path: Path) -> None:
    write_json(tmp_path / "results.json", {"value": 10})
    base = {
        "claim_id": "rank_one",
        "source_file": "results.json",
        "json_pointer": "/value",
        "raw_value": 10,
        "display_value": "10",
        "unit": "家",
        "rounding_rule": "integer",
    }
    bindings = tmp_path / "claim_bindings.json"
    write_json(bindings, {"claims": [base, {**base, "display_value": "11"}]})
    paper = tmp_path / "main.typ"
    paper.write_text("rank_one 的结果为 10 家。", encoding="utf-8")

    report = check_bindings(bindings, paper, tmp_path)

    assert any(issue["code"] == "conflicting_claim_values" for issue in report["issues"])


def test_claim_check_can_use_later_claim_occurrence(tmp_path: Path) -> None:
    write_json(tmp_path / "results.json", {"value": 26})
    bindings = tmp_path / "claim_bindings.json"
    write_json(
        bindings,
        {
            "claims": [
                {
                    "claim_id": "supplier_minimum",
                    "source_file": "results.json",
                    "json_pointer": "/value",
                    "raw_value": 26,
                    "display_value": "26",
                    "unit": "家",
                    "rounding_rule": "integer",
                }
            ]
        },
    )
    paper = tmp_path / "main.typ"
    paper.write_text(
        "索引 supplier_minimum。" + "无关内容" * 500 + "最少需要 26 家。supplier_minimum",
        encoding="utf-8",
    )

    assert check_bindings(bindings, paper, tmp_path)["passed"] is True
