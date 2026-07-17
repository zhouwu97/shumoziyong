from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paper.check_narrative import build_narrative_report
from paper.external_precheck import run_external_precheck
from paper.gate4_candidate import build_candidate_manifest
from paper.paper_production_manifest import build_paper_production_manifest
from paper.template_registry import DEFAULT_MANIFEST_PATH, select_template


ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_valid_paper_candidate(run_dir: Path) -> None:
    """为项目测试构造哈希闭合的最小 Gate 4 论文候选证据。"""
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    runtime_manifest = json.loads(
        (run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8")
    )
    binding = {
        "run_id": run_manifest["run_id"],
        "problem_id": run_manifest["problem_id"],
        "profile": run_manifest["profile"],
        "runtime_version": run_manifest["runtime_version"],
        "runtime_pack_sha256": runtime_manifest["runtime_pack_sha256"],
    }

    profile = json.loads(
        (ROOT / "paper_profiles/cumcm_academic_v1.json").read_text(encoding="utf-8")
    )
    _write(run_dir / "paper_profile.snapshot.json", profile)

    registry = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    selection = select_template(registry, language="zh", competition_family="cumcm")
    _write(run_dir / "template_selection.json", selection)

    template_bytes = b"template"
    template_sha = hashlib.sha256(template_bytes).hexdigest()
    template_manifest = {
        "manifest_version": "1.0.0",
        "template_id": selection["template_id"],
        "renderer_id": "typst",
        "files": [{"path": "main.typ", "sha256": template_sha, "size_bytes": len(template_bytes)}],
    }
    _write(run_dir / "paper_template_manifest.json", template_manifest)

    narrative_texts = {
        "thesis": "本文建立受约束优化模型，并获得稳定且可执行的决策方案。",
        "core_contributions": "核心贡献是把业务规则统一转化为可验证的数学约束。",
        "model_choice_reason": "选择混合整数规划是因为离散决策与容量约束都可精确表达。",
        "result_insights": "结果表明主要资源瓶颈集中在高负荷生产环节。",
        "action_recommendations": "建议优先调整瓶颈环节配置并保留需求扰动余量。",
        "limitations": "模型局限在于需求依据历史样本，极端冲击仍需重新计算。",
    }
    source_bytes = ("= Test\n\n" + "\n\n".join(narrative_texts.values()) + "\n").encode(
        "utf-8"
    )
    (run_dir / "main.typ").write_bytes(source_bytes)
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    source_manifest = {
        "manifest_version": "1.0.0",
        "entry": "main.typ",
        "files": [{"path": "main.typ", "sha256": source_sha, "size_bytes": len(source_bytes)}],
    }
    _write(run_dir / "paper_source_manifest.json", source_manifest)

    pdf_path = run_dir / "submission.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n")
    pdf_sha = _sha(pdf_path)
    attestation = {
        "schema_version": "1.0.0",
        "paper_kind": "submission_paper",
        "profile_id": profile["profile_id"],
        "template_id": template_manifest["template_id"],
        "renderer_id": template_manifest["renderer_id"],
        "renderer_version": "0.13.1",
        "source_manifest": "paper_source_manifest.json",
        "source_manifest_sha256": _sha(run_dir / "paper_source_manifest.json"),
        "profile_snapshot": "paper_profile.snapshot.json",
        "profile_snapshot_sha256": _sha(run_dir / "paper_profile.snapshot.json"),
        "template_manifest": "paper_template_manifest.json",
        "template_manifest_sha256": _sha(run_dir / "paper_template_manifest.json"),
        "output_pdf": "../submission.pdf",
        "output_pdf_sha256": pdf_sha,
        "compiled": True,
    }
    _write(run_dir / "paper_render_attestation.json", attestation)

    humanization = {
        "schema_version": "1.0.0",
        "source_sha256": "0" * 64,
        "output_sha256": source_sha,
        "protected_numbers_changed": [],
        "protected_formulas_changed": [],
        "protected_units_changed": [],
        "protected_symbols_changed": [],
        "citations_changed": [],
        "figure_table_refs_changed": [],
        "table_cells_changed": [],
        "direction_phrases_changed": [],
        "scope_phrases_changed": [],
        "rewritten_paragraph_count": 1,
        "stock_phrases_removed": 1,
        "status": "passed",
    }
    _write(run_dir / "paper_humanization_report.json", humanization)

    consistency_check = {"status": "passed", "evidence": ["fixture"], "issues": []}
    consistency = {
        "schema_version": "1.0.0",
        "paper_source_sha256": source_sha,
        "model_route": "model_route.json",
        "model_route_sha256": _sha(run_dir / "model_route.json"),
        "result_report": "result_report.json",
        "result_report_sha256": _sha(run_dir / "result_report.json"),
        "checks": {
            key: dict(consistency_check)
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
    _write(run_dir / "model_text_consistency_report.json", consistency)

    run_external_precheck(
        paper_root=run_dir,
        report_path=run_dir / "paper_external_precheck_report.json",
        suggestions_path=run_dir / "suggested_repairs.json",
    )
    claim_map_path = run_dir / "paper_claim_map.json"
    claim_map = json.loads(claim_map_path.read_text(encoding="utf-8"))
    narrative_input = {
        "schema_version": "paper_narrative_input_v1",
        **{
            name: [{"text": text, "evidence_refs": ["C001"]}]
            for name, text in narrative_texts.items()
        },
    }
    narrative_report = build_narrative_report(
        paper_root=run_dir,
        narrative_input=narrative_input,
        claim_map=claim_map,
        claim_map_path=claim_map_path,
        binding=binding,
    )
    _write(run_dir / "paper_narrative_report.json", narrative_report)

    visual = {
        "schema_version": "1.0.0",
        "pdf_sha256": pdf_sha,
        "page_count": 1,
        "reviewed_pages": [1],
        "reviewer": "independent visual fixture reviewer",
        "issues": [],
        "status": "passed",
    }
    _write(run_dir / "paper_visual_review.json", visual)

    verify_checks = {
        name: {"status": "passed", "issues": []}
        for name in (
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
    }
    artifact_hashes = {
        "paper_source": source_sha,
        "render_attestation": _sha(run_dir / "paper_render_attestation.json"),
        "humanization_report": _sha(run_dir / "paper_humanization_report.json"),
        "claim_bindings": _sha(run_dir / "paper_claim_map.json"),
        "model_text_consistency": _sha(run_dir / "model_text_consistency_report.json"),
        "visual_review": _sha(run_dir / "paper_visual_review.json"),
        "submission_pdf": pdf_sha,
    }
    verify_report = {
        "schema_version": "1.0.0",
        "paper_kind": "submission_paper",
        "profile_id": profile["profile_id"],
        "template_id": template_manifest["template_id"],
        "renderer_id": template_manifest["renderer_id"],
        "status": "passed",
        "checks": verify_checks,
        "artifacts": [
            {"role": role, "path": f"fixture/{role}", "sha256": digest}
            for role, digest in artifact_hashes.items()
        ],
        "summary": {"passed": len(verify_checks), "failed": 0, "warnings": 0},
    }
    _write(run_dir / "paper_verify_report.json", verify_report)

    production_manifest = build_paper_production_manifest(run_dir, binding)
    _write(run_dir / "paper_production_manifest_v2.json", production_manifest)

    candidate = build_candidate_manifest(run_dir, binding)
    _write(run_dir / "paper_candidate_manifest.json", candidate)
