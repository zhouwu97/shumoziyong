from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
PAPER_SCRIPTS = ROOT / "scripts" / "paper"
sys.path.insert(0, str(PAPER_SCRIPTS))

from paper_compiler_common import load_json, sha256_file, validate_schema  # noqa: E402
from validate_ai_pre_review_evidence import (  # noqa: E402
    REVIEW_DIRS,
    ZIP_PACKAGE_DIRS,
    assert_completed_review,
    derive_ai_pre_review_conclusion,
    validate_evidence,
    verify_recovered_zip,
)


def test_ai_pre_review_validation_schema_is_valid() -> None:
    schema = load_json(
        ROOT / "schemas/paper_compiler_ai_pre_review_validation.schema.json"
    )
    Draft202012Validator.check_schema(schema)


def test_completed_ai_reviews_and_evidence_chain_validate(tmp_path: Path) -> None:
    protected = {
        reviewer_id: sha256_file(
            review_dir / f"{reviewer_id}_ai_pre_review.json"
        )
        for reviewer_id, review_dir in REVIEW_DIRS.items()
    }
    report = validate_evidence(tmp_path / "validation_report.json")

    assert report["overall_status"] == (
        "existing_evidence_validated_zip_recheck_incomplete"
    )
    assert report["components"]["review_schema_validation"]["status"] == "passed"
    assert report["components"]["protocol_and_mapping_validation"]["status"] == "passed"
    assert report["components"]["admin_integrity_and_source_protection"]["status"] == (
        "passed"
    )
    assert report["components"]["original_zip_reverification"]["status"] == (
        "missing"
    )
    assert all(item["exists"] is False for item in report["components"]["original_zip_reverification"]["expected_zips"])
    for reviewer_id, review_dir in REVIEW_DIRS.items():
        assert sha256_file(review_dir / f"{reviewer_id}_ai_pre_review.json") == protected[
            reviewer_id
        ]


def _zip_package(package_dir: Path, output: Path, *, traversal: bool = False) -> None:
    manifest = load_json(package_dir / "package_manifest.json")
    names = [item["path"] for item in manifest["files"]] + ["package_manifest.json"]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, (package_dir / name).read_bytes())
        if traversal:
            archive.writestr("../blind_mapping_admin.json", b"{}")


def test_recovered_zip_accepts_exact_whitelist_and_hash(tmp_path: Path) -> None:
    package_dir = ZIP_PACKAGE_DIRS["reviewer_1_ai_pre_review.zip"]
    zip_path = tmp_path / "reviewer.zip"
    _zip_package(package_dir, zip_path)

    record = verify_recovered_zip(zip_path, sha256_file(zip_path), package_dir)

    assert record["status"] == "verified"
    assert record["issues"] == []


def test_recovered_zip_wrong_hash_is_invalid(tmp_path: Path) -> None:
    package_dir = ZIP_PACKAGE_DIRS["reviewer_1_ai_pre_review.zip"]
    zip_path = tmp_path / "reviewer.zip"
    _zip_package(package_dir, zip_path)

    record = verify_recovered_zip(zip_path, "0" * 64, package_dir)

    assert record["status"] == "invalid"
    assert any("SHA-256" in issue for issue in record["issues"])


def test_recovered_zip_path_traversal_is_invalid(tmp_path: Path) -> None:
    package_dir = ZIP_PACKAGE_DIRS["reviewer_1_ai_pre_review.zip"]
    zip_path = tmp_path / "reviewer.zip"
    _zip_package(package_dir, zip_path, traversal=True)

    record = verify_recovered_zip(zip_path, sha256_file(zip_path), package_dir)

    assert record["status"] == "invalid"
    assert any("路径穿越" in issue for issue in record["issues"])


def test_ai_review_date_format_is_enforced() -> None:
    payload = load_json(
        REVIEW_DIRS["reviewer_1"] / "reviewer_1_ai_pre_review.json"
    )
    payload["completed_at"] = "not-a-date"

    with pytest.raises(ValueError, match="completed_at"):
        assert_completed_review(payload, "reviewer_1")


def test_negative_markdown_context_cannot_override_structured_conclusion() -> None:
    deceptive_summary = "本文不认为系统 production_ready，也没有正式资格。"
    reviews = {
        reviewer_id: load_json(review_dir / f"{reviewer_id}_ai_pre_review.json")
        for reviewer_id, review_dir in REVIEW_DIRS.items()
    }

    assert "production_ready" in deceptive_summary
    assert derive_ai_pre_review_conclusion(reviews) == "ai_pre_review_revise"


def test_landed_validation_report_matches_schema_with_formats() -> None:
    report = load_json(
        ROOT
        / "capability_evidence/paper_compiler_v1_1_1/ai_pre_review_packages/"
        "admin_only/AI_PRE_REVIEW_VALIDATION_REPORT.json"
    )
    validate_schema(report, "paper_compiler_ai_pre_review_validation.schema.json")
