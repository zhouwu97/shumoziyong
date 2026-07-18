from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
PAPER_SCRIPTS = ROOT / "scripts" / "paper"
sys.path.insert(0, str(PAPER_SCRIPTS))

from build_ai_pre_review_packages import (  # noqa: E402
    DEFAULT_OUTPUT,
    LEAKAGE_PATTERNS,
    ai_review_template,
    build_review_facts,
    normalized_text_sha256,
    resolve_canonical_mapping,
    scan_package,
)
from paper_compiler_common import load_json  # noqa: E402


def test_ai_pre_review_schema_and_pending_templates() -> None:
    schema = load_json(ROOT / "schemas/paper_compiler_ai_pre_review.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    for reviewer_id, order in {
        "reviewer_1": ("X", "Y", "Z"),
        "reviewer_2": ("Z", "X", "Y"),
    }.items():
        payload = ai_review_template(
            reviewer_id, order, "review-freeze-0123456789abcdef"
        )
        validator.validate(payload)
        assert payload["reviewer_type"] == "ai_pre_review"
        assert payload["formal_human_review"] is False
        assert payload["status"] == "pending"


def test_canonical_anonymous_mapping_is_hash_verified() -> None:
    mapping, _, anonymous = resolve_canonical_mapping()
    originals = {
        "A": ROOT / "capability_evidence/paper_compiler_v1_1_1/baseline/version_a.md",
        "B": ROOT / "capability_evidence/paper_compiler_v1_1_1/current/version_b.md",
        "C": ROOT / "capability_evidence/paper_compiler_v1_1_1/current/version_c.md",
    }

    assert set(mapping) == {"X", "Y", "Z"}
    assert set(mapping.values()) == {"A", "B", "C"}
    for label, variant in mapping.items():
        assert normalized_text_sha256(anonymous[label]) == normalized_text_sha256(
            originals[variant]
        )


def test_review_fact_view_has_no_internal_generation_metadata() -> None:
    facts = build_review_facts()
    serialized = str(facts)

    assert facts["comparison"]["direction"] == "increase"
    assert facts["inference_policy"]["strength"] == "bounded_inference"
    for forbidden in ("card_id", "planner", "prompt", "bundle", "version_a", "version_b", "version_c"):
        assert forbidden not in serialized.lower()


def test_built_packages_pass_leakage_and_record_missing_zip_boundary() -> None:
    assert DEFAULT_OUTPUT.is_dir()
    for reviewer_id in ("reviewer_1", "reviewer_2"):
        package_dir = DEFAULT_OUTPUT / reviewer_id
        result = scan_package(package_dir)
        assert result == {"status": "passed", "findings": []}
        zip_path = DEFAULT_OUTPUT / f"{reviewer_id}_ai_pre_review.zip"
        if zip_path.exists():
            assert zipfile.is_zipfile(zip_path)
            with zipfile.ZipFile(zip_path) as archive:
                names = archive.namelist()
                assert "package_manifest.json" in names
                assert all(not name.startswith("admin_only/") for name in names)
                assert all("blind_mapping" not in name for name in names)
        else:
            validation = load_json(
                DEFAULT_OUTPUT / "admin_only/AI_PRE_REVIEW_VALIDATION_REPORT.json"
            )
            zip_component = validation["components"]["original_zip_reverification"]
            assert zip_component["status"] == "missing"
            expected = {Path(item["path"]).name: item for item in zip_component["expected_zips"]}
            assert expected[zip_path.name]["exists"] is False

    assert LEAKAGE_PATTERNS
