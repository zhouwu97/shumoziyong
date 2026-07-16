from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def load_json(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_paper_contract_schemas_are_valid_draft_2020_12() -> None:
    for relative in (
        "schemas/paper_profile.schema.json",
        "schemas/paper_verify_report.schema.json",
    ):
        Draft202012Validator.check_schema(load_json(relative))


def test_cumcm_profile_satisfies_profile_schema() -> None:
    schema = load_json("schemas/paper_profile.schema.json")
    profile = load_json("paper_profiles/cumcm_academic_v1.json")

    Draft202012Validator(schema).validate(profile)
    assert profile["approved_renderers"] == [
        {"id": "typst", "template_id": "cumcm_typst_academic_v1"}
    ]


def test_contract_keeps_submission_and_technical_report_separate() -> None:
    contract = (ROOT / "docs/paper/PAPER_RENDERING_CONTRACT.md").read_text(encoding="utf-8")

    assert "submission_paper" in contract
    assert "technical_report" in contract
    assert "ReportLab" in contract
    assert "不得静默退回" in contract
