from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from paper import build_gate4_pipeline as pipeline  # noqa: E402
from run_workflow import _require_gate_f_ready_for_handoff  # noqa: E402


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_active_formal_result_requires_exactly_one_envelope(tmp_path: Path) -> None:
    _write(tmp_path / "run_manifest.json", {"formal_result_policy": "required_v1"})

    with pytest.raises(ValueError, match="必须且只能有一个 Formal Result"):
        pipeline.require_active_formal_result(tmp_path)


def test_active_formal_result_rejects_ineligible_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "run_manifest.json", {"formal_result_policy": "required_v1"})
    envelope = tmp_path / "formal_results" / "fr-1" / "formal_result_envelope.json"
    _write(envelope, {})
    monkeypatch.setattr(
        pipeline,
        "verify_formal_result_bundle",
        lambda _run, _envelope: {
            "formal_result_activation_status": "run_execution_verified",
            "formal_result_eligible": False,
        },
    )

    with pytest.raises(ValueError, match="不具备论文生产资格"):
        pipeline.require_active_formal_result(tmp_path)


def test_claim_map_must_bind_primary_formal_result(tmp_path: Path) -> None:
    formal = tmp_path / "formal_results" / "fr-1"
    _write(formal / "domain_manifest.json", {"output_file_set": ["prediction_result.json"]})
    _write(formal / "formal_result_envelope.json", {})
    _write(formal / "prediction_result.json", {"payload": {"score": 0.5}})
    summary = {
        "domain_manifest_path": str(formal / "domain_manifest.json"),
        "envelope_path": str(formal / "formal_result_envelope.json"),
    }
    invalid = {
        "claims": [
            {
                "claim_id": "C001",
                "source_file": "result_report.json",
                "json_pointer": "/metrics/0/value",
                "raw_value": 0.5,
                "display_value": "0.500",
                "rounding_rule": "3_decimal",
            }
        ]
    }

    with pytest.raises(ValueError, match="未直接绑定 eligible Formal Result"):
        pipeline._require_claims_from_formal_result(tmp_path, invalid, summary)


def test_visual_review_requires_real_full_page_record(tmp_path: Path) -> None:
    review = tmp_path / "paper_visual_review.json"
    _write(
        review,
        {
            "schema_version": "1.0.0",
            "pdf_sha256": "1" * 64,
            "page_count": 2,
            "reviewed_pages": [1],
            "reviewer": "external visual reviewer",
            "issues": [],
            "status": "passed",
        },
    )

    with pytest.raises(ValueError, match="未覆盖全部页面"):
        pipeline._validate_visual_review(review, pdf_sha256="1" * 64, page_count=2)


def test_prepare_stops_before_visual_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    source = run / "paper_source"
    source.mkdir(parents=True)
    main = source / "main.typ"
    main.write_text("= 正文\n\n结论 0.500。 // C001\n", encoding="utf-8")
    runtime_sha = "2" * 64
    _write(
        run / "run_manifest.json",
        {
            "run_id": "run-1",
            "problem_id": "2025-C",
            "profile": "prediction",
            "runtime_version": "0.1.0",
            "runtime_pack_sha256": runtime_sha,
            "formal_result_policy": "required_v1",
            "paper_pipeline_contract_version": "1.0.0",
        },
    )
    _write(run / "runtime_pack.manifest.json", {"runtime_pack_sha256": runtime_sha})
    formal = run / "formal_results" / "fr-1"
    _write(formal / "formal_result_envelope.json", {})
    _write(formal / "domain_manifest.json", {"output_file_set": ["prediction_result.json"]})
    _write(formal / "prediction_result.json", {"payload": {"score": 0.5}})
    binding = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_claim_map",
        "run_id": "run-1",
        "problem_id": "2025-C",
        "profile": "prediction",
        "runtime_version": "0.1.0",
        "runtime_pack_sha256": runtime_sha,
        "claims": [
            {
                "claim_id": "C001",
                "claim": "测试结论绑定正式结果 0.500。",
                "result_refs": ["formal result"],
                "evidence_refs": ["formal result"],
                "source_file": "formal_results/fr-1/prediction_result.json",
                "json_pointer": "/payload/score",
                "raw_value": 0.5,
                "display_value": "0.500",
                "unit": "",
                "rounding_rule": "3_decimal",
                "conclusion_tokens": ["0.500"],
            }
        ],
    }
    _write(run / "paper_claim_map.json", binding)
    _write(run / "paper_narrative_input.json", {"schema_version": "fixture"})
    _write(run / "model_route_v2_1.json", {})
    _write(run / "result_report.json", {})
    check = {"status": "passed", "evidence": ["fixture"], "issues": []}
    consistency = {
        "schema_version": "1.0.0",
        "paper_source_sha256": _sha(main),
        "model_route": "model_route_v2_1.json",
        "model_route_sha256": _sha(run / "model_route_v2_1.json"),
        "result_report": "result_report.json",
        "result_report_sha256": _sha(run / "result_report.json"),
        "checks": {
            name: dict(check)
            for name in (
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
    _write(run / "model_text_consistency_input.json", consistency)

    monkeypatch.setattr(pipeline, "_require_gate_4_state", lambda _run: None)
    monkeypatch.setattr(
        pipeline,
        "require_active_formal_result",
        lambda _run: {
            "formal_result_id": "fr-1",
            "formal_result_domain": "predictive_modeling",
            "envelope_path": str(formal / "formal_result_envelope.json"),
            "envelope_file_sha256": _sha(formal / "formal_result_envelope.json"),
            "domain_manifest_path": str(formal / "domain_manifest.json"),
        },
    )

    def fake_precheck(**kwargs: object) -> dict[str, object]:
        _write(Path(str(kwargs["report_path"])), {"status": "passed"})
        _write(Path(str(kwargs["suggestions_path"])), {"repairs": []})
        return {"status": "passed"}

    monkeypatch.setattr(pipeline, "run_external_precheck", fake_precheck)
    monkeypatch.setattr(
        pipeline,
        "build_narrative_report",
        lambda **_kwargs: {"status": "passed"},
    )
    monkeypatch.setattr(
        pipeline,
        "check_humanization_diff",
        lambda _source, _output: {"status": "passed"},
    )
    monkeypatch.setattr(
        pipeline,
        "check_bindings",
        lambda _bindings, _paper, _root: {"passed": True, "issues": []},
    )

    def fake_render(**kwargs: object) -> dict[str, object]:
        output = Path(str(kwargs["output_pdf"]))
        output.write_bytes(b"%PDF-1.4\n%%EOF\n")
        _write(Path(str(kwargs["attestation_path"])), {"compiled": True})
        return {"output_pdf_sha256": _sha(output)}

    monkeypatch.setattr(pipeline, "render_submission", fake_render)

    def fake_raster(pdf: Path, output: Path, dpi: int) -> dict[str, object]:
        output.mkdir()
        page = output / "page-001.png"
        page.write_bytes(b"png")
        return {
            "pdf_sha256": _sha(pdf),
            "page_count": 1,
            "pages": [{"file": str(page.resolve()), "sha256": _sha(page)}],
        }

    monkeypatch.setattr(pipeline, "rasterize_pdf", fake_raster)
    state = pipeline.prepare_pipeline(
        run_dir=run,
        source_dir=source,
        source_entry=Path("main.typ"),
        narrative_input_path=run / "paper_narrative_input.json",
        model_consistency_path=run / "model_text_consistency_input.json",
        renderer_executable="typst-test",
    )

    assert state["status"] == "awaiting_visual_review"
    assert not (run / "paper_visual_review.json").exists()
    assert not (run / "paper_candidate_manifest.json").exists()

    with pytest.raises(FileNotFoundError, match="逐页视觉审核记录"):
        pipeline.finalize_pipeline(run_dir=run)

    assert not (run / "paper_visual_review.json").exists()
    assert not (run / "paper_candidate_manifest.json").exists()


def test_bound_content_contract_runs_f2_before_candidate_creation(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "paper_content_contract.yaml").write_text(
        "schema_version: '1.0.0'\ncontract_id: fixture_contract\nproblem_id: 2025-C\nrole_requirements:\n  Q1:\n    - role: calibration\n      severity: critical\n",
        encoding="utf-8",
    )
    _write(
        run / "paper_evidence_role_registry.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "paper_evidence_role_registry",
            "problem_id": "2025-C",
            "contract_id": "fixture_contract",
            "run_id": "run-1",
            "formal_result_ids": ["fr-1"],
            "roles": [],
        },
    )
    _write(run / "paper_claim_map.json", {"claims": []})
    status = pipeline._run_content_quality_if_bound(
        run,
        {
            "run_id": "run-1",
            "problem_id": "2025-C",
            "profile": "prediction",
            "runtime_version": "1.0.0",
            "runtime_pack_sha256": "a" * 64,
        },
    )

    assert status is not None
    assert status["status"] == "content_repair_required"
    assert (run / "paper_substantive_completeness_report.json").is_file()
    assert (run / "paper_gate_f_status.json").is_file()


def test_handoff_rejects_bound_run_without_f3_pass(tmp_path: Path) -> None:
    (tmp_path / "paper_content_contract.yaml").write_text("contract_id: fixture\n", encoding="utf-8")
    _write(
        tmp_path / "paper_gate_f_status.json",
        {
            "status": "content_repair_required",
            "eligible_for_gate_g": False,
        },
    )

    with pytest.raises(ValueError, match="禁止生成最终人工终审交接包"):
        _require_gate_f_ready_for_handoff(tmp_path)
