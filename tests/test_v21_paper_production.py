from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from build_v21_production_manifest import build_manifest
from render_v21_figure import render, sha256_file


def test_non_formal_figure_requires_verified_attestation(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "source_data").mkdir(parents=True)
    source = run_dir / "source_data" / "metric.csv"
    source.write_text("scenario,value\n1,2\n", encoding="utf-8")
    contract = {
        "schema_version": "1.0.0",
        "figure_id": "figure_001",
        "core_conclusion": "The metric is reported for the tested scenario.",
        "evidence_chain": ["C001"],
        "archetype": "quantitative_grid",
        "source_data_ref": {"path": "source_data/metric.csv", "sha256": sha256_file(source)},
        "x": "scenario",
        "y": "value",
        "chart_type": "line",
    }
    contract_path = run_dir / "figure_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ValueError, match="source_data_attestation_ref"):
        render(run_dir, contract_path)


def test_python_figure_and_paper_manifest_bind_current_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "source_data").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(json.dumps({"run_id": "paper_test"}), encoding="utf-8")
    source = run_dir / "source_data" / "metric.csv"
    source.write_text("scenario,value\n1,2\n2,3\n3,5\n", encoding="utf-8")
    attestation = run_dir / "source_data" / "metric.attestation.json"
    attestation.write_text(
        json.dumps(
            {
                "status": "verified",
                "source_data_ref": {"path": "source_data/metric.csv", "sha256": sha256_file(source)},
            }
        ),
        encoding="utf-8",
    )
    contract = {
        "schema_version": "1.0.0",
        "figure_id": "figure_001",
        "core_conclusion": "The validated metric increases across the three tested scenarios.",
        "evidence_chain": ["C001", "formal_result.metric"],
        "archetype": "quantitative_grid",
        "source_data_ref": {"path": "source_data/metric.csv", "sha256": sha256_file(source)},
        "source_data_attestation_ref": {"path": "source_data/metric.attestation.json", "sha256": sha256_file(attestation)},
        "x": "scenario",
        "y": "value",
        "chart_type": "line",
        "title": "Validated scenario response",
    }
    contract_path = run_dir / "figure_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    fragment = render(run_dir, contract_path)
    fragment_path = run_dir / "figures" / "figure_001.fragment.json"
    fragment_path.write_text(json.dumps(fragment), encoding="utf-8")
    assert fragment["exports"]["tiff"]["path"].endswith(".tiff")
    assert (run_dir / fragment["qa_ref"]["path"]).is_file()

    admission = {
        "run_id": "paper_test",
        "submission_paper_allowed": False,
    }
    (run_dir / "paper_admission_report.json").write_text(json.dumps(admission), encoding="utf-8")
    for name in ("terminology.md", "paper_claim_map.json", "technical_report.md", "technical_report.pdf", "matlab_level_a_report.json", "matlab_level_b_report.json"):
        (run_dir / name).write_text("{}", encoding="utf-8")
    manifest = build_manifest(
        run_dir,
        one_sentence_argument="A validated optimization workflow supports bounded decisions without overstating model evidence.",
        terminology_ledger="terminology.md",
        claim_map="paper_claim_map.json",
        manuscript="technical_report.md",
        pdf="technical_report.pdf",
        figure_fragments=["figures/figure_001.fragment.json"],
        missing_evidence_placeholders=["EVIDENCE_REQUIRED: competition value below admission threshold"],
        status="candidate",
    )
    assert manifest["paper_type"] == "technical_report"
    assert manifest["figure_backend"] == "python"
