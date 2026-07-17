from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any

from paper_compiler_common import (
    load_json,
    load_verified_bundle_cards,
    sha256_file,
    validate_schema,
    write_json,
)


NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[,.]\d+)*(?:%|‰)?")
CAUSAL_VERBS = ("导致", "决定", "造成", "证明了因果关系")


def issue(code: str, message: str, ref_id: str | None = None) -> dict[str, str]:
    value = {"severity": "FAIL", "code": code, "message": message}
    if ref_id:
        value["ref_id"] = ref_id
    return value


def validate_plan_usage(
    plan: dict[str, Any],
    projection: dict[str, Any],
    graph: dict[str, Any],
    cards: dict[str, dict[str, Any]],
    bundle: dict[str, Any] | None,
) -> tuple[list[dict[str, str]], Counter[str]]:
    issues: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    bindings = {item["binding_id"]: item for item in projection["fact_bindings"]}
    nodes = {item["node_id"]: item for item in graph["nodes"]}
    bundle_cards = {item["card_id"] for item in bundle.get("cards", [])} if bundle else set()
    derivation_nodes = {
        node_id
        for edge in graph["edges"]
        if edge["type"] == "derives_from"
        for node_id in (edge["from"], edge["to"])
    }

    if plan["mode"] == "production":
        if not bundle or bundle["status"] != "production_ready" or not bundle["production_allowed"]:
            issues.append(
                issue(
                    "PFC_PRODUCTION_BUNDLE_NOT_READY", "Production 模式必须使用已确认资格的卡片包"
                )
            )
    elif bundle and bundle["status"] == "production_ready":
        issues.append(
            issue("PFC_CANDIDATE_USES_PRODUCTION_BUNDLE", "Candidate 实验不应伪装成生产运行")
        )

    for section in plan["sections"]:
        section_id = section["section_id"]
        for paragraph in section["paragraphs"]:
            role = paragraph["role"]
            paragraph_text = "".join(
                segment.get("value", "")
                for segment in paragraph["segments"]
                if segment["type"] == "text"
            )
            attribution_nodes: list[dict[str, Any]] = []
            for node_id in paragraph["argument_nodes"]:
                node = nodes.get(node_id)
                if not node:
                    issues.append(issue("ARG_NODE_MISSING", f"段落引用不存在的论证节点：{node_id}"))
                    continue
                if node["type"] == "attribution":
                    attribution_nodes.append(node)
                    if not node.get("evidence_refs"):
                        issues.append(
                            issue("ARG_ATTRIBUTION_EVIDENCE_MISSING", f"{node_id} 缺少归因证据")
                        )
                    inference_type = node.get("inference_type")
                    claim_strength = node.get("claim_strength")
                    allowed_strengths = {
                        "descriptive": {"observed", "supported"},
                        "mechanistic": {"supported", "derived"},
                        "causal": {"identified"},
                    }
                    if claim_strength not in allowed_strengths.get(inference_type, set()):
                        issues.append(
                            issue(
                                "ARG_INFERENCE_STRENGTH_MISMATCH",
                                f"{node_id} 的 {inference_type} 推断与 {claim_strength} 证据等级不匹配",
                            )
                        )
                    if inference_type == "mechanistic" and node_id not in derivation_nodes:
                        issues.append(
                            issue(
                                "ARG_MECHANISTIC_CLAIM_WITHOUT_DERIVATION",
                                f"{node_id} 的机理解释缺少 derives_from 关系",
                            )
                        )
                    forbidden_verbs = set(node.get("forbidden_verbs", []))
                    if inference_type == "descriptive":
                        forbidden_verbs.update(CAUSAL_VERBS)
                    if any(verb in paragraph_text for verb in forbidden_verbs):
                        issues.append(
                            issue(
                                "ARG_CAUSAL_VERB_WITHOUT_CAUSAL_EVIDENCE",
                                f"{node_id} 使用了超出证据等级的归因动词",
                            )
                        )

            if plan["mode"] == "candidate_without_cards" and paragraph["card_ids"]:
                issues.append(
                    issue("PFC_CARD_UNEXPECTED", f"{paragraph['paragraph_id']} 不应加载表达卡片")
                )
            if plan["mode"] == "candidate_with_cards" and not paragraph["card_ids"]:
                issues.append(
                    issue("PFC_CARD_REQUIRED", f"{paragraph['paragraph_id']} 缺少表达卡片")
                )
            for card_id in paragraph["card_ids"]:
                card = cards.get(card_id)
                if not card or card_id not in bundle_cards:
                    issues.append(
                        issue("PFC_CARD_SEMANTIC_MISMATCH", f"卡片未纳入当前包或不存在：{card_id}")
                    )
                    continue
                if role not in card["applicable_roles"]:
                    issues.append(
                        issue("PFC_CARD_SEMANTIC_MISMATCH", f"卡片 {card_id} 不适用于职责 {role}")
                    )
                if (
                    card["state"] not in {"task_adapted", "eligible_for_qualification"}
                    and plan["mode"] != "production"
                ):
                    issues.append(
                        issue(
                            "PFC_CARD_STATE_INVALID", f"Candidate 模式不能加载状态 {card['state']}"
                        )
                    )
                policy = card.get("inference_policy")
                if policy:
                    invalid_types = sorted(
                        {
                            node["inference_type"]
                            for node in attribution_nodes
                            if node.get("inference_type") not in policy["allowed_inference_types"]
                        }
                    )
                    if invalid_types:
                        issues.append(
                            issue(
                                "PFC_CARD_SEMANTIC_MISMATCH",
                                f"卡片 {card_id} 不允许归因类型：{invalid_types}",
                            )
                        )
                    if any(verb in paragraph_text for verb in policy["forbidden_verbs"]):
                        issues.append(
                            issue(
                                "PFC_CARD_SEMANTIC_MISMATCH",
                                f"卡片 {card_id} 的禁止动词出现在段落中",
                            )
                        )

            for segment in paragraph["segments"]:
                if segment["type"] == "text":
                    if NUMBER_PATTERN.search(segment["value"]):
                        issues.append(
                            issue(
                                "PFC_RAW_NUMBER_IN_TEXT_SEGMENT",
                                f"{paragraph['paragraph_id']} 的 text 段含数字",
                            )
                        )
                    continue
                ref_id = segment["ref_id"]
                binding = bindings.get(ref_id)
                if not binding:
                    issues.append(
                        issue("PFC_UNKNOWN_FACT_REF", f"事实引用不存在：{ref_id}", ref_id)
                    )
                    continue
                if binding["ref_type"] != segment["ref_type"]:
                    issues.append(
                        issue("PFC_FACT_TYPE_MISMATCH", f"事实引用类型不匹配：{ref_id}", ref_id)
                    )
                usage = binding["usage"]
                if section_id not in usage["allowed_sections"] or section_id in usage.get(
                    "forbidden_sections", []
                ):
                    issues.append(
                        issue(
                            "PFC_FACT_FORBIDDEN_IN_SECTION",
                            f"{ref_id} 不允许出现在 {section_id}",
                            ref_id,
                        )
                    )
                counts[ref_id] += 1

    for ref_id, binding in bindings.items():
        requirement = binding["usage"]["requirement"]
        count = counts[ref_id]
        if requirement == "required_once" and count != 1:
            issues.append(
                issue("PFC_FACT_CARDINALITY", f"{ref_id} 应恰好使用一次，实际 {count} 次", ref_id)
            )
        elif requirement == "required_at_least_once" and count < 1:
            issues.append(issue("PFC_FACT_CARDINALITY", f"{ref_id} 至少应使用一次", ref_id))
    return issues, counts


def render_plan(
    plan_path: Path,
    projection_path: Path,
    graph_path: Path,
    output_path: Path,
    clean_output_path: Path,
    report_path: Path,
    card_dir: Path | None = None,
    bundle_path: Path | None = None,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    projection = load_json(projection_path)
    graph = load_json(graph_path)
    validate_schema(plan, "paper_fact_realization_plan.schema.json")
    validate_schema(projection, "paper_fact_projection.schema.json")
    validate_schema(graph, "minimal_argument_graph.schema.json")
    bundle = load_json(bundle_path) if bundle_path else None
    if bundle:
        validate_schema(bundle, "paper_rhetoric_bundle.schema.json")
    bundle_issues: list[dict[str, str]] = []
    cards: dict[str, dict[str, Any]] = {}
    if bundle and card_dir:
        cards, bundle_issues = load_verified_bundle_cards(card_dir, bundle)
    elif bundle or card_dir:
        bundle_issues.append(issue("PFC_CARD_BUNDLE_INCOMPLETE", "卡片目录与卡片包必须同时提供"))
    usage_issues, counts = validate_plan_usage(plan, projection, graph, cards, bundle)
    issues = [*bundle_issues, *usage_issues]
    bindings = {item["binding_id"]: item for item in projection["fact_bindings"]}

    annotated_lines: list[str] = []
    clean_lines: list[str] = []
    for section in plan["sections"]:
        heading = f"## {section['title']}"
        annotated_lines.extend([heading, ""])
        clean_lines.extend([heading, ""])
        for paragraph in section["paragraphs"]:
            metadata = (
                f"<!--PARAGRAPH:{paragraph['paragraph_id']} role={paragraph['role']} "
                f"cards={','.join(paragraph['card_ids'])}-->"
            )
            annotated_parts = [metadata]
            clean_parts: list[str] = []
            for segment in paragraph["segments"]:
                if segment["type"] == "text":
                    annotated_parts.append(segment["value"])
                    clean_parts.append(segment["value"])
                    continue
                ref_id = segment["ref_id"]
                binding = bindings.get(ref_id)
                if not binding:
                    continue
                rendered = binding["rendered_text"]
                annotated_parts.append(
                    f"<!--FACT:{ref_id} type={binding['ref_type']}-->{rendered}<!--/FACT:{ref_id}-->"
                )
                clean_parts.append(rendered)
            annotated_lines.extend(["".join(annotated_parts), ""])
            clean_lines.extend(["".join(clean_parts), ""])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(annotated_lines).rstrip() + "\n", encoding="utf-8")
    clean_output_path.parent.mkdir(parents=True, exist_ok=True)
    clean_output_path.write_text("\n".join(clean_lines).rstrip() + "\n", encoding="utf-8")
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_fact_realization_report",
        "status": "failed" if issues else "passed",
        "inputs": {
            "plan": str(plan_path.resolve()),
            "plan_sha256": sha256_file(plan_path),
            "projection": str(projection_path.resolve()),
            "projection_sha256": sha256_file(projection_path),
            "graph": str(graph_path.resolve()),
            "graph_sha256": sha256_file(graph_path),
        },
        "summary": {"bindings_checked": len(counts), "failures": len(issues)},
        "issues": issues,
        "reference_counts": dict(sorted(counts.items())),
    }
    validate_schema(report, "paper_fact_realization_report.schema.json")
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="确定性渲染结构化事实引用")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clean-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--card-dir", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    report = render_plan(
        args.plan,
        args.projection,
        args.graph,
        args.output,
        args.clean_output,
        args.report,
        args.card_dir,
        args.bundle,
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
