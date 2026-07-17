from __future__ import annotations

import argparse
from pathlib import Path
from statistics import mean
from typing import Any

from build_review_freeze import validate_existing_freeze
from paper_compiler_common import load_json, validate_schema, write_json


STRUCTURE_DIMENSIONS = ("result_location", "comparison_clarity", "paragraph_coherence")
MAIN_DIMENSIONS = ("attribution_quality", "boundary_awareness", "paragraph_coherence")


def issue(code: str, message: str) -> dict[str, str]:
    return {"severity": "FAIL", "code": code, "message": message}


def completed_review_issues(review: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if review["status"] != "completed":
        return issues
    for label, version in review["versions"].items():
        if any(value is None for value in version["scores"].values()):
            issues.append(
                issue("PCR_REVIEW_SCORE_MISSING", f"{review['reviewer_id']} 的 {label} 缺少评分")
            )
        if version["modification_minutes"] is None:
            issues.append(
                issue("PCR_REVIEW_TIME_MISSING", f"{review['reviewer_id']} 的 {label} 缺少修改时间")
            )
        if version["fact_drift_detected"] is None:
            issues.append(
                issue(
                    "PCR_REVIEW_FACT_CHECK_MISSING",
                    f"{review['reviewer_id']} 的 {label} 缺少事实漂移结论",
                )
            )
    return issues


def normalized_reviews(
    reviews: list[dict[str, Any]],
    mappings: dict[str, dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    by_version: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for review in reviews:
        mapping = mappings[review["reviewer_id"]]
        for label, values in review["versions"].items():
            by_version[mapping[label]].append(values)
    return by_version


def dimension_average(values: list[dict[str, Any]], dimensions: tuple[str, ...]) -> float:
    return mean(item["scores"][dimension] for item in values for dimension in dimensions)


def modification_average(values: list[dict[str, Any]]) -> float:
    return mean(item["modification_minutes"] for item in values)


def derive_decision(
    reviews: list[dict[str, Any]],
    overlap: dict[str, Any],
    mappings: dict[str, dict[str, str]],
    adjudicator: dict[str, Any] | None,
) -> str:
    if any(
        version["fact_drift_detected"]
        for review in reviews
        for version in review["versions"].values()
    ):
        return "stop"
    verdicts = {item["verdict"] for item in overlap["items"]}
    if "probable_source_reuse" in verdicts:
        return "stop"

    by_version = normalized_reviews(reviews, mappings)
    structure = {
        version: dimension_average(values, STRUCTURE_DIMENSIONS)
        for version, values in by_version.items()
    }
    main = {
        version: dimension_average(values, MAIN_DIMENSIONS)
        for version, values in by_version.items()
    }
    modification = {version: modification_average(values) for version, values in by_version.items()}
    reviewer_decisions = [review["decision"] for review in reviews]
    effective_decision = adjudicator["decision"] if adjudicator else None
    all_continue = all(value == "continue" for value in reviewer_decisions)
    if effective_decision == "continue":
        all_continue = True
    overlap_safe = verdicts <= {"no_concern", "generic_academic_overlap"}
    time_safe = modification["A"] == 0 or modification["C"] <= 1.10 * modification["A"]
    if (
        all_continue
        and structure["B"] > structure["A"]
        and main["C"] - main["B"] >= -0.25
        and time_safe
        and overlap_safe
    ):
        return "continue"

    all_stop = all(value == "stop" for value in reviewer_decisions)
    if effective_decision == "stop":
        all_stop = True
    burden_increased = (
        modification["A"] > 0
        and modification["B"] > 1.10 * modification["A"]
        and modification["C"] > 1.10 * modification["A"]
    )
    if all_stop or (
        structure["B"] <= structure["A"] and structure["C"] <= structure["A"] and burden_increased
    ):
        return "stop"
    return "revise"


def validate_reviews(review_dir: Path, output_path: Path) -> dict[str, Any]:
    freeze_path = review_dir / "review_freeze_manifest.json"
    issues: list[dict[str, str]] = []
    try:
        freeze = validate_existing_freeze(freeze_path)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        freeze = {"freeze_id": "review-freeze-0000000000000000"}
        issues.append(issue("PCR_FREEZE_INTEGRITY_FAILED", str(exc)))

    reviews = []
    for reviewer_id in ("reviewer_1", "reviewer_2"):
        path = review_dir / f"{reviewer_id}.json"
        try:
            review = load_json(path)
            validate_schema(review, "paper_compiler_exploratory_review.schema.json")
            if review["freeze_id"] != freeze["freeze_id"]:
                raise ValueError("freeze_id 不一致")
            issues.extend(completed_review_issues(review))
            reviews.append(review)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            issues.append(issue("PCR_REVIEW_INVALID", f"{reviewer_id}：{exc}"))

    overlap_path = review_dir / "human_overlap_review.json"
    try:
        overlap = load_json(overlap_path)
        validate_schema(overlap, "paper_compiler_human_overlap_review.schema.json")
        if overlap["freeze_id"] != freeze["freeze_id"]:
            raise ValueError("freeze_id 不一致")
    except (FileNotFoundError, KeyError, ValueError) as exc:
        overlap = {"status": "pending", "items": []}
        issues.append(issue("PCR_HUMAN_OVERLAP_INVALID", str(exc)))

    completed_reviews = [review for review in reviews if review["status"] == "completed"]
    decisions = {review["decision"] for review in completed_reviews}
    adjudicator_required = len(completed_reviews) == 2 and len(decisions) > 1
    adjudicator = None
    if adjudicator_required:
        try:
            candidate = load_json(review_dir / "adjudicator.json")
            validate_schema(candidate, "paper_compiler_exploratory_review.schema.json")
            issues.extend(completed_review_issues(candidate))
            if candidate["status"] == "completed":
                adjudicator = candidate
        except (FileNotFoundError, KeyError, ValueError) as exc:
            issues.append(issue("PCR_ADJUDICATOR_INVALID", str(exc)))

    decision = None
    if issues:
        status = "failed_integrity"
    elif len(completed_reviews) < 2:
        status = "awaiting_external_human_review"
    elif overlap["status"] != "completed":
        status = "awaiting_human_overlap_review"
    elif adjudicator_required and adjudicator is None:
        status = "awaiting_adjudication"
    else:
        private_keys = load_json(review_dir / "private/review_keys.json")
        decision = derive_decision(
            completed_reviews,
            overlap,
            private_keys["mappings"],
            adjudicator,
        )
        status = "completed"

    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_exploratory_review_status",
        "freeze_id": freeze["freeze_id"],
        "status": status,
        "integrity_status": "failed" if issues else "passed",
        "required_reviewers": 2,
        "completed_reviewers": len(completed_reviews),
        "human_overlap_status": overlap["status"],
        "adjudicator_required": adjudicator_required,
        "decision": decision,
        "allowed_decisions": ["continue", "revise", "stop"],
        "ai_may_sign": False,
        "production_ready_allowed": False,
        "issues": issues,
    }
    validate_schema(payload, "paper_compiler_review_status.schema.json")
    write_json(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="校验探索性人工盲评并按冻结策略派生结论")
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate_reviews(args.review_dir, args.output)
    print(
        {
            "status": payload["status"],
            "completed_reviewers": payload["completed_reviewers"],
            "decision": payload["decision"],
        }
    )
    return 1 if payload["integrity_status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
