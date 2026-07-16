from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from check_profile_binding import check_profile_binding  # noqa: E402


PROFILE = ROOT / "paper_profiles" / "cumcm_academic_v1.json"
TEMPLATE = ROOT / "paper_templates" / "cumcm_typst"


def test_submission_requires_explicit_profile_renderer_version_and_template() -> None:
    report = check_profile_binding(paper_kind="submission_paper")

    assert report["passed"] is False
    assert {issue["code"] for issue in report["issues"]} >= {
        "profile_not_declared",
        "profile_id_not_declared",
        "renderer_not_declared",
        "renderer_version_not_declared",
        "template_not_declared",
        "approved_template_missing",
    }


def test_cumcm_approved_typst_binding_passes() -> None:
    report = check_profile_binding(
        paper_kind="submission_paper",
        profile_path=PROFILE,
        declared_profile_id="cumcm_academic_v1",
        renderer_id="typst",
        renderer_version="typst 0.13.1",
        template_id="cumcm_typst_academic_v1",
        template_dir=TEMPLATE,
    )

    assert report["passed"] is True
    assert report["issues"] == []


def test_incompatible_renderer_template_pair_fails() -> None:
    report = check_profile_binding(
        paper_kind="submission_paper",
        profile_path=PROFILE,
        declared_profile_id="cumcm_academic_v1",
        renderer_id="reportlab",
        renderer_version="reportlab 4.0",
        template_id="cumcm_typst_academic_v1",
        template_dir=TEMPLATE,
    )

    assert report["passed"] is False
    assert "renderer_template_not_approved" in {issue["code"] for issue in report["issues"]}


def test_renderer_is_not_rejected_by_global_technology_blacklist(tmp_path: Path) -> None:
    profile = copy.deepcopy(json.loads(PROFILE.read_text(encoding="utf-8")))
    profile["approved_renderers"] = [
        {"id": "reportlab", "template_id": "cumcm_reportlab_academic_v1"}
    ]
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    template_dir = tmp_path / "template"
    template_dir.mkdir()
    (template_dir / "template.json").write_text(
        json.dumps(
            {
                "template_id": "cumcm_reportlab_academic_v1",
                "renderer_id": "reportlab",
                "entry": "render.py",
                "protected_files": [],
            }
        ),
        encoding="utf-8",
    )

    report = check_profile_binding(
        paper_kind="submission_paper",
        profile_path=profile_path,
        declared_profile_id="cumcm_academic_v1",
        renderer_id="reportlab",
        renderer_version="reportlab 4.0",
        template_id="cumcm_reportlab_academic_v1",
        template_dir=template_dir,
    )

    assert report["passed"] is True


def test_technical_report_is_not_blocked_by_submission_contract() -> None:
    report = check_profile_binding(paper_kind="technical_report")

    assert report == {
        "schema_version": "1.0.0",
        "paper_kind": "technical_report",
        "constraints_applied": False,
        "passed": True,
        "issues": [],
    }
