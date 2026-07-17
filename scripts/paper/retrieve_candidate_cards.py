from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from paper_compiler_common import load_json, load_verified_bundle_cards, validate_schema, write_json


def retrieve_cards(
    plan_path: Path,
    projection_path: Path,
    card_dir: Path,
    bundle_path: Path,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    projection = load_json(projection_path)
    bundle = load_json(bundle_path)
    validate_schema(plan, "paper_fact_realization_plan.schema.json")
    validate_schema(projection, "paper_fact_projection.schema.json")
    validate_schema(bundle, "paper_rhetoric_bundle.schema.json")
    cards, bundle_issues = load_verified_bundle_cards(card_dir, bundle)
    bundle_ids = {item["card_id"] for item in bundle["cards"]}
    bindings = {item["binding_id"]: item for item in projection["fact_bindings"]}
    results = []
    issues = list(bundle_issues)
    for section in plan["sections"]:
        for paragraph in section["paragraphs"]:
            fact_types = {
                bindings[segment["ref_id"]]["ref_type"]
                for segment in paragraph["segments"]
                if segment["type"] == "fact_ref" and segment["ref_id"] in bindings
            }
            candidates = []
            rejected = []
            for card_id in sorted(bundle_ids):
                card = cards.get(card_id)
                if not card:
                    rejected.append(
                        {"card_id": card_id, "reason": "卡片缺失或未通过 Manifest 校验"}
                    )
                    continue
                if card["state"] not in {"task_adapted", "eligible_for_qualification"}:
                    rejected.append({"card_id": card_id, "reason": "Candidate 状态不允许"})
                    continue
                if paragraph["role"] not in card["applicable_roles"]:
                    rejected.append({"card_id": card_id, "reason": "段落职责不匹配"})
                    continue
                missing_types = sorted(set(card["required_fact_types"]) - fact_types)
                if missing_types:
                    rejected.append(
                        {"card_id": card_id, "reason": f"缺少事实类型：{', '.join(missing_types)}"}
                    )
                    continue
                candidates.append(card_id)
            selected = paragraph["card_ids"]
            if plan["mode"] == "candidate_with_cards" and not selected:
                issues.append(
                    {
                        "code": "PFC_CARD_RETRIEVAL_EMPTY",
                        "paragraph_id": paragraph["paragraph_id"],
                        "card_ids": [],
                    }
                )
            invalid = sorted(set(selected) - set(candidates))
            if invalid:
                issues.append(
                    {
                        "code": "PFC_CARD_RETRIEVAL_INVALID",
                        "paragraph_id": paragraph["paragraph_id"],
                        "card_ids": invalid,
                    }
                )
            results.append(
                {
                    "paragraph_id": paragraph["paragraph_id"],
                    "role": paragraph["role"],
                    "available_fact_types": sorted(fact_types),
                    "candidate_card_ids": candidates,
                    "selected_card_ids": selected,
                    "selection_reason": "职责、事实类型、Candidate 状态和卡片包版本均匹配",
                    "rejected_cards": rejected,
                }
            )
    return {
        "schema_version": "1.0.0",
        "artifact_type": "paper_rhetoric_retrieval_report",
        "status": "failed" if issues else "passed",
        "bundle_id": bundle["bundle_id"],
        "paragraphs": results,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="按段落职责和事实类型检索 Candidate 表达卡片")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--card-dir", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = retrieve_cards(
        args.plan,
        args.projection,
        args.card_dir,
        args.bundle,
    )
    write_json(args.output, report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
