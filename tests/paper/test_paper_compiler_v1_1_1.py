from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
PAPER_SCRIPTS = ROOT / "scripts" / "paper"
sys.path.insert(0, str(PAPER_SCRIPTS))

from build_fact_projection import build_projection  # noqa: E402
from build_qualification_boundary import baseline_exception  # noqa: E402
from build_review_freeze import (  # noqa: E402
    pending_review_is_empty,
    review_template,
    reviewer_mapping,
    validate_existing_freeze,
)
from build_rhetoric_bundle import build_bundle  # noqa: E402
from paper_compiler_common import load_json, rhetoric_bundle_digest, write_json  # noqa: E402
from parse_typed_exemptions import parse_exemptions  # noqa: E402
from render_fact_references import render_plan  # noqa: E402
from retrieve_candidate_cards import retrieve_cards  # noqa: E402
from run_paper_compiler_fault_injection import run_fault_injections  # noqa: E402
from validate_fact_projection import validate_projection  # noqa: E402
from validate_fact_realization import validate_realization  # noqa: E402
from validate_exploratory_review import validate_reviews  # noqa: E402


RUN_DIR = ROOT / "runs" / "2024C_v21_full_replay_20260715"
BASELINE_DIR = ROOT / "capability_evidence" / "paper_compiler_v1_1_1" / "baseline"
CARD_DIR = ROOT / "papers" / "rhetoric_cards"


def test_paper_compiler_contract_schemas_are_valid() -> None:
    names = (
        "paper_claim_binding.schema.json",
        "paper_fact_projection.schema.json",
        "minimal_argument_graph.schema.json",
        "paper_rhetoric_card.schema.json",
        "paper_rhetoric_bundle.schema.json",
        "paper_fact_realization_plan.schema.json",
        "paper_fact_realization_report.schema.json",
        "paper_typed_exemptions.schema.json",
        "paper_rhetoric_overlap_report.schema.json",
        "paper_compiler_qualification_boundary.schema.json",
        "paper_compiler_exploratory_review.schema.json",
        "paper_compiler_review_freeze.schema.json",
        "paper_compiler_human_overlap_review.schema.json",
        "paper_compiler_review_status.schema.json",
        "paper_compiler_pilot_manifest.schema.json",
    )
    for name in names:
        schema = load_json(ROOT / "schemas" / name)
        Draft202012Validator.check_schema(schema)


def test_projection_is_read_only_and_upstream_hashes_validate(tmp_path: Path) -> None:
    projection = build_projection(RUN_DIR, BASELINE_DIR / "claim_bindings.json", "Q1")
    projection_path = tmp_path / "paper_fact_projection.json"
    write_json(projection_path, projection)

    report = validate_projection(projection_path, RUN_DIR)

    assert report["status"] == "passed"
    assert projection["run_id"] == RUN_DIR.name
    assert {item["claim_id"] for item in projection["claims"]} == {"C001", "C002"}
    by_id = {item["binding_id"]: item for item in projection["fact_bindings"]}
    assert by_id["CB-Q1-WASTE-PROFIT"]["rendered_text"] == "1730.80 万元"
    assert by_id["CB-Q1-SCENARIO-DIFFERENCE"]["rendered_text"] == "较超产滞销情形增加 3675.75 万元"
    assert by_id["CB-Q1-SCENARIO-DIFFERENCE"]["derives_from"] == [
        "CB-Q1-DISCOUNT-PROFIT",
        "CB-Q1-WASTE-PROFIT",
    ]


def build_candidate_c(tmp_path: Path) -> tuple[Path, Path, Path]:
    projection = build_projection(RUN_DIR, BASELINE_DIR / "claim_bindings.json", "Q1")
    projection_path = tmp_path / "paper_fact_projection.json"
    write_json(projection_path, projection)
    bundle_path = tmp_path / "bundle.json"
    build_bundle(CARD_DIR, bundle_path)
    annotated = tmp_path / "annotated.md"
    clean = tmp_path / "clean.md"
    report = render_plan(
        BASELINE_DIR / "plan_c.json",
        projection_path,
        BASELINE_DIR / "argument_graph.json",
        annotated,
        clean,
        tmp_path / "render_report.json",
        CARD_DIR,
        bundle_path,
    )
    assert report["status"] == "passed"
    return projection_path, bundle_path, annotated


def test_structured_plan_renders_and_revalidates_without_fact_drift(tmp_path: Path) -> None:
    projection_path, bundle_path, annotated = build_candidate_c(tmp_path)
    exemptions = parse_exemptions(annotated)
    exemptions_path = tmp_path / "typed_exemptions.json"
    write_json(exemptions_path, exemptions)

    report = validate_realization(annotated, projection_path, exemptions_path)

    assert report["status"] == "passed"
    assert report["summary"]["failures"] == 0
    assert report["reference_counts"]["BD-Q1-OPTIMALITY"] == 1
    retrieval = retrieve_cards(
        BASELINE_DIR / "plan_c.json",
        projection_path,
        CARD_DIR,
        bundle_path,
    )
    assert retrieval["status"] == "passed"
    assert all(item["selected_card_ids"] for item in retrieval["paragraphs"])


def test_descriptive_attribution_rejects_causal_verb(tmp_path: Path) -> None:
    projection_path, bundle_path, _ = build_candidate_c(tmp_path)
    plan = copy.deepcopy(load_json(BASELINE_DIR / "plan_c.json"))
    explain = plan["sections"][0]["paragraphs"][2]
    explain["segments"][-1]["value"] = "。这一规则直接导致利润增加。"
    plan_path = tmp_path / "causal_plan.json"
    write_json(plan_path, plan)

    report = render_plan(
        plan_path,
        projection_path,
        BASELINE_DIR / "argument_graph.json",
        tmp_path / "causal.md",
        tmp_path / "causal_clean.md",
        tmp_path / "causal_report.json",
        CARD_DIR,
        bundle_path,
    )

    assert report["status"] == "failed"
    assert "ARG_CAUSAL_VERB_WITHOUT_CAUSAL_EVIDENCE" in {item["code"] for item in report["issues"]}


def test_typed_exemptions_are_parser_generated_and_hash_bound(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("# 1. 结果\n\n2024 年的依据见文献 [12, 14-16]。\n", encoding="utf-8")

    payload = parse_exemptions(source)

    assert {item["type"] for item in payload["exemptions"]} == {
        "section_number",
        "year",
        "citation_number",
    }
    assert all(
        item["source_span"]["end_byte"] > item["source_span"]["start_byte"]
        for item in payload["exemptions"]
    )
    citation_values = {
        item["value"] for item in payload["exemptions"] if item["type"] == "citation_number"
    }
    assert citation_values == {"12", "14", "16"}


def test_card_bundle_hash_is_enforced_during_render(tmp_path: Path) -> None:
    projection_path, bundle_path, _ = build_candidate_c(tmp_path)
    bundle = load_json(bundle_path)
    bundle["cards"][0]["sha256"] = "0" * 64
    bundle["content_sha256"] = rhetoric_bundle_digest(bundle["cards"])
    write_json(bundle_path, bundle)

    report = render_plan(
        BASELINE_DIR / "plan_c.json",
        projection_path,
        BASELINE_DIR / "argument_graph.json",
        tmp_path / "hash_drift.md",
        tmp_path / "hash_drift_clean.md",
        tmp_path / "hash_drift_report.json",
        CARD_DIR,
        bundle_path,
    )

    assert report["status"] == "failed"
    assert "PFC_CARD_BUNDLE_HASH_DRIFT" in {item["code"] for item in report["issues"]}


def test_attribution_strength_must_match_inference_type(tmp_path: Path) -> None:
    projection_path, bundle_path, _ = build_candidate_c(tmp_path)
    graph = copy.deepcopy(load_json(BASELINE_DIR / "argument_graph.json"))
    attribution = next(node for node in graph["nodes"] if node["type"] == "attribution")
    attribution["claim_strength"] = "identified"
    graph_path = tmp_path / "invalid_strength_graph.json"
    write_json(graph_path, graph)

    report = render_plan(
        BASELINE_DIR / "plan_c.json",
        projection_path,
        graph_path,
        tmp_path / "invalid_strength.md",
        tmp_path / "invalid_strength_clean.md",
        tmp_path / "invalid_strength_report.json",
        CARD_DIR,
        bundle_path,
    )

    assert report["status"] == "failed"
    assert "ARG_INFERENCE_STRENGTH_MISMATCH" in {item["code"] for item in report["issues"]}


def test_reviewer_packages_use_distinct_permutations() -> None:
    first = reviewer_mapping(20260717)
    second = reviewer_mapping(20260718)
    adjudicator = reviewer_mapping(20260720)

    assert first != second
    assert tuple(adjudicator.items()) not in {tuple(first.items()), tuple(second.items())}
    assert set(first.values()) == {"A", "B", "C"}
    assert set(second.values()) == {"A", "B", "C"}


def test_nonempty_human_review_cannot_be_reinitialized(tmp_path: Path) -> None:
    reviewer_path = tmp_path / "reviewer_1.json"
    payload = review_template("reviewer_1", "review-freeze-0123456789abcdef")
    write_json(reviewer_path, payload)
    assert pending_review_is_empty(reviewer_path)

    payload["versions"]["X"]["comments"] = ["人工评语"]
    write_json(reviewer_path, payload)
    assert not pending_review_is_empty(reviewer_path)


def test_markdown_failures_are_proven_in_base_commit() -> None:
    exception = baseline_exception(
        "BE-MD-LINK-001",
        "README.md",
        "docs/status/CURRENT_STATUS.md",
        "docs/status/CURRENT_STATUS.md",
    )

    assert exception["present_in_base_commit"] is True
    assert exception["introduced_by_pilot"] is False
    assert exception["line"] > 0


def test_frozen_review_package_is_intact_and_mapping_is_private(tmp_path: Path) -> None:
    review_dir = ROOT / "capability_evidence/paper_compiler_v1_1_1/exploratory_ab"
    freeze = validate_existing_freeze(review_dir / "review_freeze_manifest.json")

    assert freeze["review_started_at"] is None
    assert freeze["source_state"]["pilot_commit_sha"] is None
    assert len(freeze["reviewer_packages"]) == 3
    for package in freeze["reviewer_packages"]:
        manifest = load_json(ROOT / package["package_manifest"])
        assert manifest["mapping_disclosed"] is False
        assert "mapping" not in manifest

    status = validate_reviews(review_dir, tmp_path / "status.json")
    assert status["integrity_status"] == "passed"
    assert status["status"] == "awaiting_external_human_review"
    assert status["decision"] is None


def test_qualification_boundary_does_not_claim_repository_green() -> None:
    report = load_json(
        ROOT
        / "capability_evidence/paper_compiler_v1_1_1/current/qualification_boundary_report.json"
    )

    assert report["automated_scope"] == "paper_compiler_v1_1_1_pilot"
    assert report["components"]["repository_validator"]["status"] == (
        "failed_preexisting_issues"
    )
    assert report["components"]["full_test_suite"]["status"] == (
        "blocked_workspace_optional_dependencies"
    )
    assert {item["module"] for item in report["full_suite_blockers"]} == {
        "pypandoc",
        "e2b_code_interpreter",
    }


def test_all_ten_fault_injections_are_caught(tmp_path: Path) -> None:
    projection_path, bundle_path, annotated = build_candidate_c(tmp_path)
    summary = run_fault_injections(
        annotated,
        projection_path,
        BASELINE_DIR / "plan_c.json",
        BASELINE_DIR / "argument_graph.json",
        CARD_DIR,
        bundle_path,
        tmp_path / "faults",
    )

    assert summary["status"] == "passed"
    assert summary["cases_total"] == 10
    assert summary["cases_caught"] == 10
