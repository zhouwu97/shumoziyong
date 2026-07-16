"""从当前 PR-2 证据生成九维 score_v3，不解释历史 score_v2。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from competition_route_runtime import EVIDENCE_FILENAMES, evaluate_competition_gate3


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "runtime_contracts" / "score_v3_policy_v1.json"
DIMENSIONS = (
    "mechanism_hypothesis",
    "business_constraints",
    "route_competition",
    "execution_completeness",
    "comparison_quality",
    "formal_evidence",
    "operability",
    "risk_robustness",
    "submission_readiness",
)
SOURCE_PATHS = {
    "model_route": EVIDENCE_FILENAMES["model_route"],
    "route_execution": EVIDENCE_FILENAMES["execution"],
    "route_comparison": EVIDENCE_FILENAMES["comparison"],
    "operability_contract": EVIDENCE_FILENAMES["operability_contract"],
    "operability_report": EVIDENCE_FILENAMES["operability_report"],
    "risk_contract": EVIDENCE_FILENAMES["risk_contract"],
    "risk_report": EVIDENCE_FILENAMES["risk_report"],
    "gate3_decision": EVIDENCE_FILENAMES["decision"],
}
REQUIRED_DIMENSION_EVIDENCE = {
    "mechanism_hypothesis": {"model_route"},
    "business_constraints": {"model_route", "operability_contract"},
    "route_competition": {"model_route", "route_comparison"},
    "execution_completeness": {"route_execution"},
    "comparison_quality": {"route_comparison", "gate3_decision"},
    "formal_evidence": {"gate3_decision"},
    "operability": {"operability_contract", "operability_report", "gate3_decision"},
    "risk_robustness": {"risk_contract", "risk_report", "gate3_decision"},
    "submission_readiness": {"gate3_decision"},
}


class ScoreV3Error(ValueError):
    """评分输入、证据绑定或派生结果不满足 score_v3 政策。"""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoreV3Error(f"{label} 无法读取：{exc}") from exc
    if not isinstance(value, dict):
        raise ScoreV3Error(f"{label} 顶层必须是对象")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_schema(value: Mapping[str, Any], schema_name: str, label: str) -> None:
    schema = _load_object(ROOT / "schemas" / schema_name, schema_name)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ScoreV3Error(f"{label} 不符合 Schema：{location}: {error.message}")


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _evidence_refs(run_root: Path, subproblem_id: str) -> dict[str, dict[str, str]]:
    refs: dict[str, dict[str, str]] = {}
    for key, template in SOURCE_PATHS.items():
        relative = template.format(subproblem_id=subproblem_id)
        path = run_root / relative
        if not path.is_file():
            raise ScoreV3Error(f"缺少 PR-2 当前运行证据：{relative}")
        refs[key] = {"path": relative, "sha256": _sha256(path)}
    return refs


def _dimension_ceilings(gate3: Mapping[str, Any]) -> dict[str, float]:
    codes = set(gate3["decision_codes"])
    decision = gate3["decision"]
    comparison_ceiling = 100.0
    if codes & {"G3V3_SELECTED_ROUTE_INADMISSIBLE", "G3V3_DATA_LEAKAGE"}:
        comparison_ceiling = 0.0
    elif "G3V3_ROUTE_DEGRADED" in codes:
        comparison_ceiling = 70.0
    risk_ceiling = 100.0
    if codes & {"G3V3_RISK_BLOCK", "G3V3_DATA_LEAKAGE"}:
        risk_ceiling = 0.0
    elif "G3V3_RISK_TECHNICAL_ONLY" in codes:
        risk_ceiling = 70.0
    return {
        "mechanism_hypothesis": 100.0,
        "business_constraints": 100.0,
        "route_competition": 100.0,
        "execution_completeness": (
            0.0 if "G3V3_ROUTE_EXECUTION_INCOMPLETE" in codes else 100.0
        ),
        "comparison_quality": comparison_ceiling,
        "formal_evidence": (
            70.0 if "G3V3_FORMAL_RESULT_INELIGIBLE" in codes else 100.0
        ),
        "operability": 0.0 if "G3V3_OPERABILITY_FAILED" in codes else 100.0,
        "risk_robustness": risk_ceiling,
        "submission_readiness": {
            "allow_paper": 100.0,
            "technical_report_only": 70.0,
            "block": 0.0,
        }[decision],
    }


def build_score_v3(
    run_dir: Path,
    subproblem_id: str,
    ratings_path: Path,
    *,
    write_report: bool = True,
) -> dict[str, Any]:
    """复算 Gate 3、绑定当前哈希并应用固定权重、证据上限与致命封顶。"""
    run_root = run_dir.resolve()
    policy = _load_object(POLICY_PATH, "score_v3_policy_v1.json")
    _validate_schema(policy, "score_v3_policy.schema.json", "score_v3_policy_v1.json")
    if abs(sum(float(value) for value in policy["weights"].values()) - 1.0) > 1e-12:
        raise ScoreV3Error("score_v3 权重和必须精确为 1")

    ratings = _load_object(ratings_path.resolve(), "score_v3 ratings")
    _validate_schema(ratings, "score_v3_ratings.schema.json", "score_v3 ratings")
    existing_gate3_path = run_root / EVIDENCE_FILENAMES["decision"].format(
        subproblem_id=subproblem_id
    )
    existing_gate3 = _load_object(existing_gate3_path, existing_gate3_path.name)
    if ratings["gate3_decision_sha256"] != _sha256(existing_gate3_path):
        raise ScoreV3Error("ratings 绑定的 Gate 3 SHA-256 与当前文件不一致")
    validator_id = str(existing_gate3["validator"]["validator_id"])
    recomputed_gate3 = evaluate_competition_gate3(
        run_root,
        subproblem_id,
        validator_id,
        write_report=False,
    )
    if existing_gate3 != recomputed_gate3:
        raise ScoreV3Error("competition_gate3_decision 与当前 PR-2 证据复算结果不一致")
    if ratings["run_id"] != recomputed_gate3["run_id"]:
        raise ScoreV3Error("ratings.run_id 与当前 Gate 3 Run 不一致")
    if ratings["subproblem_id"] != subproblem_id:
        raise ScoreV3Error("ratings.subproblem_id 与目标子问题不一致")

    source_refs = _evidence_refs(run_root, subproblem_id)
    allowed_paths = {ref["path"]: ref for ref in source_refs.values()}
    ceilings = _dimension_ceilings(recomputed_gate3)
    dimension_results: dict[str, dict[str, Any]] = {}
    raw_total = 0.0
    for dimension in DIMENSIONS:
        rating = ratings["dimensions"][dimension]
        evidence_paths = set(rating["evidence_paths"])
        unknown = evidence_paths - set(allowed_paths)
        if unknown:
            raise ScoreV3Error(
                f"{dimension} 引用了 PR-2 当前证据集合之外的路径：{sorted(unknown)}"
            )
        required_paths = {
            source_refs[key]["path"] for key in REQUIRED_DIMENSION_EVIDENCE[dimension]
        }
        missing = required_paths - evidence_paths
        if missing:
            raise ScoreV3Error(f"{dimension} 缺少必需证据：{sorted(missing)}")
        awarded = float(rating["score"])
        ceiling = ceilings[dimension]
        effective = min(awarded, ceiling)
        weight = float(policy["weights"][dimension])
        weighted = effective * weight
        raw_total += weighted
        dimension_results[dimension] = {
            "awarded_score": awarded,
            "evidence_ceiling": ceiling,
            "effective_score": effective,
            "weight": weight,
            "weighted_score": round(weighted, 6),
            "rationale": rating["rationale"],
            "evidence_refs": [allowed_paths[path] for path in sorted(evidence_paths)],
        }

    raw_total = round(raw_total, 6)
    fatal_mapping = policy["fatal_mapping"]
    fatal_codes = sorted(
        fatal_mapping[code]
        for code in recomputed_gate3["decision_codes"]
        if code in fatal_mapping
    )
    fatal_cap_applied = bool(fatal_codes)
    final_score = min(raw_total, float(policy["fatal_cap"])) if fatal_codes else raw_total
    gate3_decision = recomputed_gate3["decision"]
    if gate3_decision == "block":
        submission_status = "blocked"
    elif (
        gate3_decision != "allow_paper"
        or fatal_codes
        or final_score < float(policy["submission_threshold"])
    ):
        submission_status = "technical_report_only"
    else:
        submission_status = "eligible"

    result = {
        "schema_version": "1.0.0",
        "artifact_type": "score_v3",
        "run_id": recomputed_gate3["run_id"],
        "subproblem_id": subproblem_id,
        "scorer_id": ratings["scorer_id"],
        "policy": {
            "path": "runtime_contracts/score_v3_policy_v1.json",
            "sha256": _sha256(POLICY_PATH),
        },
        "source_evidence": source_refs,
        "dimensions": dimension_results,
        "raw_total": raw_total,
        "fatal_cap_applied": fatal_cap_applied,
        "final_score": round(final_score, 6),
        "fatal_codes": fatal_codes,
        "gate3_decision": gate3_decision,
        "submission_status": submission_status,
        "submission_allowed": submission_status == "eligible",
        "technical_report_allowed": True,
    }
    _validate_schema(result, "score_v3.schema.json", "score_v3")
    if write_report:
        output_path = run_root / f"score_v3_{subproblem_id}.json"
        _write_json_atomic(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--subproblem", required=True)
    parser.add_argument("--ratings", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = build_score_v3(args.run_dir, args.subproblem, args.ratings)
    except (ScoreV3Error, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["submission_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
