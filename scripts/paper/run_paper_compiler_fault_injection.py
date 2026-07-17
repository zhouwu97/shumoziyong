from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Callable

from paper_compiler_common import load_json, write_json
from render_fact_references import render_plan
from validate_fact_realization import FACT_PATTERN, validate_realization


Mutation = Callable[[str], str]


def replace_once(old: str, new: str) -> Mutation:
    def mutate(text: str) -> str:
        if old not in text:
            raise ValueError(f"故障注入目标不存在：{old}")
        return text.replace(old, new, 1)

    return mutate


def remove_fact(ref_id: str) -> Mutation:
    def mutate(text: str) -> str:
        for match in FACT_PATTERN.finditer(text):
            if match.group("id") == ref_id:
                return text[: match.start()] + text[match.end() :]
        raise ValueError(f"找不到事实标记：{ref_id}")

    return mutate


def run_fault_injections(
    paper_path: Path,
    projection_path: Path,
    plan_path: Path,
    graph_path: Path,
    card_dir: Path,
    bundle_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    original = paper_path.read_text(encoding="utf-8")
    cases: list[tuple[str, str, Mutation]] = [
        ("number_drift", "PFC_NUMBER_DRIFT", replace_once("5406.55", "5406.56")),
        ("precision_drift", "PFC_PRECISION_DRIFT", replace_once("1730.80", "1730.8")),
        ("unit_drift", "PFC_UNIT_DRIFT", replace_once("5406.55 万元", "5406.55 亿元")),
        ("direction_drift", "PFC_DIRECTION_DRIFT", replace_once("增加 3675.75", "降低 3675.75")),
        ("baseline_mismatch", "PFC_BASELINE_MISMATCH", replace_once("较超产滞销情形增加", "较超产折价情形增加")),
        ("optimality_overclaim", "PFC_OPTIMALITY_OVERCLAIM", lambda text: text + "\n该方案达到全局最优。\n"),
        ("boundary_removed", "PFC_BOUNDARY_REMOVED", remove_fact("BD-Q1-OPTIMALITY")),
        ("unsupported_significance", "PFC_UNSUPPORTED_SIGNIFICANCE", lambda text: text + "\n结果显著提高。\n"),
        ("unbound_number", "PFC_UNBOUND_SEMANTIC_NUMBER", lambda text: text + "\n额外收益为 99 万元。\n"),
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for case_id, expected_code, mutation in cases:
        case_dir = output_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        mutated_path = case_dir / "mutated.md"
        mutated_path.write_text(mutation(original), encoding="utf-8")
        report = validate_realization(mutated_path, projection_path)
        write_json(case_dir / "report.json", report)
        codes = sorted({item["code"] for item in report["issues"]})
        results.append(
            {
                "case_id": case_id,
                "expected_code": expected_code,
                "actual_codes": codes,
                "caught": expected_code in codes,
            }
        )

    wrong_plan = copy.deepcopy(load_json(plan_path))
    wrong_plan["sections"][0]["paragraphs"][0]["card_ids"] = ["RC-WRONG-PROBLEM-999"]
    wrong_dir = output_dir / "wrong_card"
    wrong_dir.mkdir(parents=True, exist_ok=True)
    wrong_plan_path = wrong_dir / "plan.json"
    write_json(wrong_plan_path, wrong_plan)
    report = render_plan(
        wrong_plan_path,
        projection_path,
        graph_path,
        wrong_dir / "annotated.md",
        wrong_dir / "clean.md",
        wrong_dir / "report.json",
        card_dir,
        bundle_path,
    )
    codes = sorted({item["code"] for item in report["issues"]})
    results.append(
        {
            "case_id": "wrong_card",
            "expected_code": "PFC_CARD_SEMANTIC_MISMATCH",
            "actual_codes": codes,
            "caught": "PFC_CARD_SEMANTIC_MISMATCH" in codes,
        }
    )
    summary = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_fault_injection_summary",
        "status": "passed" if all(item["caught"] for item in results) else "failed",
        "cases_total": len(results),
        "cases_caught": sum(1 for item in results if item["caught"]),
        "cases": results,
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="运行论文事实层十类故障注入")
    parser.add_argument("--paper", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--card-dir", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = run_fault_injections(
        args.paper,
        args.projection,
        args.plan,
        args.graph,
        args.card_dir,
        args.bundle,
        args.output_dir,
    )
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
