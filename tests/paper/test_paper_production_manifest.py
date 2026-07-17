from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from external_precheck import run_external_precheck  # noqa: E402
from paper_production_manifest import build_paper_production_manifest  # noqa: E402
from template_registry import DEFAULT_MANIFEST_PATH, select_template  # noqa: E402


SHA = "1" * 64
BINDING = {
    "run_id": "paper-production-fixture",
    "problem_id": "2024-C",
    "profile": "engineering_optimization",
    "runtime_version": "1.0.0",
    "runtime_pack_sha256": "2" * 64,
}


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_artifacts(tmp_path: Path, *, dirty_precheck: bool = False) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    paper = tmp_path / "paper"
    paper.mkdir()
    paper_text = "= 论文\nTODO 待修复。\n" if dirty_precheck else "= 论文\n完整且已验证的正文。\n"
    (paper / "main.typ").write_text(paper_text, encoding="utf-8")
    run_external_precheck(
        paper_root=paper,
        report_path=artifacts / "paper_external_precheck_report.json",
        suggestions_path=artifacts / "suggested_repairs.json",
    )

    registry = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    selection = select_template(registry, language="zh", competition_family="cumcm")
    _write(artifacts / "template_selection.json", selection)
    profile = json.loads(
        (ROOT / "paper_profiles" / "cumcm_academic_v1.json").read_text(encoding="utf-8")
    )
    _write(artifacts / "paper_profile.snapshot.json", profile)
    _write(
        artifacts / "paper_claim_map.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "paper_claim_map",
            **BINDING,
            "claims": [
                {
                    "claim_id": "C001",
                    "claim": "当前运行的主要数值结论已绑定正式结果证据。",
                    "result_refs": ["result_report.json#/metrics/0"],
                    "evidence_refs": ["formal_result.json"],
                }
            ],
        },
    )

    check = {"status": "passed", "evidence": ["fixture"], "issues": []}
    consistency = {
        "schema_version": "1.0.0",
        "paper_source_sha256": SHA,
        "model_route": "model_route.json",
        "model_route_sha256": SHA,
        "result_report": "result_report.json",
        "result_report_sha256": SHA,
        "checks": {
            key: dict(check)
            for key in (
                "objective_directions",
                "lexicographic_order",
                "variables",
                "formulas",
                "constraints",
                "claim_scope",
            )
        },
        "status": "passed",
    }
    _write(artifacts / "model_text_consistency_report.json", consistency)
    precheck = json.loads(
        (artifacts / "paper_external_precheck_report.json").read_text(encoding="utf-8")
    )
    narrative_check = {"status": "passed", "issues": []}
    narrative_item = {
        "text": "当前运行的论文叙事已绑定正式结果证据。",
        "evidence_refs": ["C001"],
        "locations": [{"path": "main.typ", "line": 2}],
        "present": True,
        "evidence_bound": True,
    }
    narrative = {
        "schema_version": "paper_narrative_report_v1",
        **BINDING,
        "contract_sha256": SHA,
        "paper_body_sha256": precheck["body_before"]["sha256"],
        "claim_map_sha256": _sha(artifacts / "paper_claim_map.json"),
        "elements": {
            "thesis": [dict(narrative_item)],
            "core_contributions": [dict(narrative_item)],
            "model_choice_reason": [dict(narrative_item)],
            "result_insights": [dict(narrative_item)],
            "action_recommendations": [dict(narrative_item)],
            "limitations": [dict(narrative_item)],
        },
        "forbidden_scan": {"status": "passed", "hits": []},
        "checks": {
            name: dict(narrative_check)
            for name in (
                "contract_complete",
                "text_presence",
                "claim_binding",
                "forbidden_terms",
            )
        },
        "status": "passed",
        "submission_allowed": True,
        "technical_report_allowed": True,
    }
    _write(artifacts / "paper_narrative_report.json", narrative)

    template = {
        "manifest_version": "1.0.0",
        "template_id": selection["template_id"],
        "renderer_id": "typst",
        "files": [{"path": "main.typ", "sha256": SHA, "size_bytes": 1}],
    }
    _write(artifacts / "paper_template_manifest.json", template)
    pdf = artifacts / "submission.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    pdf_sha = _sha(pdf)
    render = {
        "schema_version": "1.0.0",
        "paper_kind": "submission_paper",
        "profile_id": "cumcm_academic_v1",
        "template_id": selection["template_id"],
        "renderer_id": "typst",
        "renderer_version": "0.15.0",
        "source_manifest": "paper_source_manifest.json",
        "source_manifest_sha256": SHA,
        "profile_snapshot": "paper_profile.snapshot.json",
        "profile_snapshot_sha256": SHA,
        "template_manifest": "paper_template_manifest.json",
        "template_manifest_sha256": SHA,
        "output_pdf": "submission.pdf",
        "output_pdf_sha256": pdf_sha,
        "compiled": True,
    }
    _write(artifacts / "paper_render_attestation.json", render)

    verify_names = (
        "profile_binding",
        "render_attestation",
        "humanization_diff",
        "section_structure",
        "formula_environment",
        "claim_binding",
        "model_text_consistency",
        "internal_term_leakage",
        "references",
        "compile_result",
        "pdf_metadata",
        "pdf_rasterization",
        "visual_review_record",
    )
    verify = {
        "schema_version": "1.0.0",
        "paper_kind": "submission_paper",
        "profile_id": "cumcm_academic_v1",
        "template_id": selection["template_id"],
        "renderer_id": "typst",
        "status": "passed",
        "checks": {name: {"status": "passed", "issues": []} for name in verify_names},
        "artifacts": [{"role": "submission_pdf", "path": "submission.pdf", "sha256": pdf_sha}],
        "summary": {"passed": len(verify_names), "failed": 0, "warnings": 0},
    }
    _write(artifacts / "paper_verify_report.json", verify)
    visual = {
        "schema_version": "1.0.0",
        "pdf_sha256": pdf_sha,
        "page_count": 1,
        "reviewed_pages": [1],
        "reviewer": "independent fixture reviewer",
        "issues": [],
        "status": "passed",
    }
    _write(artifacts / "paper_visual_review.json", visual)
    return artifacts


def test_production_manifest_binds_ordered_stages_without_granting_gate4(tmp_path: Path) -> None:
    artifacts = _prepare_artifacts(tmp_path)

    manifest = build_paper_production_manifest(artifacts, BINDING)

    assert manifest["submission_eligible"] is True
    assert manifest["status"] == "submission_candidate"
    assert [stage["stage"] for stage in manifest["stages"]] == [
        "upstream_compatible_precheck",
        "local_evidence_validation",
        "template_render_visual",
    ]
    assert [stage["sequence"] for stage in manifest["stages"]] == [1, 2, 3]
    assert manifest["authority"] == {
        "external_precheck_can_decide_gate4_pass": False,
        "manifest_grants_gate4_pass": False,
    }
    schema = json.loads(
        (ROOT / "schemas" / "paper_production_manifest_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert not list(Draft202012Validator(schema).iter_errors(manifest))


def test_precheck_findings_downgrade_to_technical_report(tmp_path: Path) -> None:
    artifacts = _prepare_artifacts(tmp_path, dirty_precheck=True)

    manifest = build_paper_production_manifest(artifacts, BINDING)

    assert manifest["stages"][0]["status"] == "failed"
    assert manifest["submission_eligible"] is False
    assert manifest["paper_kind"] == "technical_report"
    assert manifest["status"] == "technical_report_only"


def test_render_hash_mismatch_downgrades_without_rewriting_evidence(tmp_path: Path) -> None:
    artifacts = _prepare_artifacts(tmp_path)
    render_path = artifacts / "paper_render_attestation.json"
    render = json.loads(render_path.read_text(encoding="utf-8"))
    render["output_pdf_sha256"] = "3" * 64
    _write(render_path, render)
    before = render_path.read_bytes()

    manifest = build_paper_production_manifest(artifacts, BINDING)

    assert manifest["stages"][2]["status"] == "failed"
    assert manifest["submission_eligible"] is False
    assert render_path.read_bytes() == before


def test_failed_narrative_downgrades_to_technical_report(tmp_path: Path) -> None:
    artifacts = _prepare_artifacts(tmp_path)
    narrative_path = artifacts / "paper_narrative_report.json"
    narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
    narrative["status"] = "failed"
    narrative["submission_allowed"] = False
    narrative["checks"]["contract_complete"] = {
        "status": "failed",
        "issues": ["缺少局限性"],
    }
    _write(narrative_path, narrative)

    manifest = build_paper_production_manifest(artifacts, BINDING)

    assert manifest["stages"][1]["status"] == "failed"
    assert manifest["submission_eligible"] is False
    assert manifest["paper_kind"] == "technical_report"
