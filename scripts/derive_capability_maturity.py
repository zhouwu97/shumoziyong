"""根据不可手填的能力证据，派生系统或 Profile 的成熟度。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policies" / "capability_maturity_policy.json"
SCHEMA_PATH = ROOT / "schemas" / "capability_evidence.schema.json"


def _passed(items: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in items if item.get("status") == "passed"]


def _require_at_least(label: str, actual: int, expected: int) -> list[str]:
    if actual >= expected:
        return []
    return [f"{label}不足：需要至少 {expected}，当前 {actual}"]


def _missing_for_status(
    status: str,
    evidence: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[str]:
    """返回某一成熟度缺少的可审计事实，不接受人工声明替代事实。"""
    config = policy[status]
    if status == "foundation":
        present = set(evidence["foundation_documents"])
        missing = sorted(set(config["required_documents"]) - present)
        return [f"缺少基础文档证据：{item}" for item in missing]

    if status == "runtime_trusted":
        return _require_at_least(
            "通过的 Runtime 验证",
            len(_passed(evidence["runtime_verifications"])),
            config["minimum_passed_runtime_verifications"],
        )

    if status == "contract_ready":
        present = {item["contract_id"] for item in evidence["contracts"]}
        missing = sorted(set(config["required_contract_ids"]) - present)
        return [f"缺少已哈希的合同：{item}" for item in missing]

    if status == "executor_validated":
        issues = _require_at_least(
            "通过的候选执行-收集-正式结果闭环",
            len(_passed(evidence["execution_cycles"])),
            config["minimum_passed_execution_cycles"],
        )
        if config["forbid_fabrication"] and any(
            item["fabrication_detected"] for item in evidence["execution_cycles"]
        ):
            issues.append("存在执行结果伪造记录")
        return issues

    if status == "profile_qualified":
        cases = evidence["qualification_cases"]
        issues = _require_at_least("资格题目", len(cases), config["minimum_cases"])
        issues.extend(
            _require_at_least(
                "资格题覆盖年份",
                len({item["year"] for item in cases}),
                config["minimum_distinct_years"],
            )
        )
        issues.extend(
            _require_at_least(
                "资格题覆盖机制",
                len({item["mechanism"] for item in cases}),
                config["minimum_distinct_mechanisms"],
            )
        )
        if cases:
            replay_rate = sum(item["formal_replay_status"] == "passed" for item in cases) / len(cases)
            if replay_rate < config["required_formal_replay_rate"]:
                issues.append(
                    f"正式重跑率不足：需要 {config['required_formal_replay_rate']:.0%}，当前 {replay_rate:.0%}"
                )
        else:
            issues.append("无法计算正式重跑率：没有资格题")
        if config["forbid_fabrication"] and any(item["fabrication_detected"] for item in cases):
            issues.append("资格题存在结果伪造")
        if config["forbid_fatal_math_error"] and any(item["fatal_math_error"] for item in cases):
            issues.append("资格题存在致命数学错误")
        reviewers = {review["reviewer_id"] for item in cases for review in item["reviewers"]}
        issues.extend(
            _require_at_least("独立评审", len(reviewers), config["minimum_independent_reviewers"])
        )
        if config["forbid_common_p0"] and any(
            review["shared_p0"] for item in cases for review in item["reviewers"]
        ):
            issues.append("独立评审存在共同 P0")
        return issues

    if status == "benchmark_candidate":
        benchmark = evidence["benchmark"]
        issues: list[str] = []
        if config["require_registered_protocol"] and not benchmark["protocol_registered"]:
            issues.append("盲测协议尚未登记")
        blind_replayed = [
            item
            for item in benchmark["blind_cases"]
            if item["blind"] and item["formal_replay_status"] == "passed"
        ]
        issues.extend(
            _require_at_least(
                "通过正式重跑的盲测题",
                len(blind_replayed),
                config["minimum_blind_benchmark_cases"],
            )
        )
        return issues

    if status == "competition_ready":
        passed = _passed(evidence["simulations"])
        issues = _require_at_least("通过的限时模拟赛", len(passed), config["minimum_simulations"])
        over_limit = [item["simulation_id"] for item in passed if item["duration_hours"] > config["maximum_simulation_hours"]]
        if over_limit:
            issues.append("模拟赛超过时限：" + ", ".join(over_limit))
        if config["require_reproducible_delivery"]:
            unreproducible = [
                item["simulation_id"] for item in passed if not item["reproducible_delivery"]
            ]
            if unreproducible:
                issues.append("模拟赛交付不可复现：" + ", ".join(unreproducible))
        return issues

    if status == "national_award_competitive":
        cases = evidence["qualification_cases"]
        issues: list[str] = []
        if config["forbid_fabrication"] and any(item["fabrication_detected"] for item in cases):
            issues.append("存在结果伪造记录")
        if config["forbid_fatal_math_error"] and any(item["fatal_math_error"] for item in cases):
            issues.append("存在致命数学错误")
        formal_award = bool(evidence.get("formal_national_award", False))
        if not (config["formal_national_award_alternative"] and formal_award):
            blind_reviews = {
                item["reviewer_id"] for item in evidence["independent_reviews"] if item["blind"]
            }
            issues.extend(
                _require_at_least(
                    "独立专家盲评",
                    len(blind_reviews),
                    config["minimum_blind_expert_reviews"],
                )
            )
            if evidence["benchmark"]["average_score"] < config["minimum_blind_benchmark_score"]:
                issues.append(
                    "盲测平均分不足："
                    f"需要 {config['minimum_blind_benchmark_score']}，"
                    f"当前 {evidence['benchmark']['average_score']}"
                )
        return issues

    raise ValueError(f"未知成熟度：{status}")


def derive_maturity(
    evidence: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """按顺序派生最高连续成熟度，并返回下一阶段缺口。"""
    achieved: list[str] = []
    first_missing: list[str] = []
    for status in policy["ordered_statuses"]:
        missing = _missing_for_status(status, evidence, policy)
        if missing:
            first_missing = missing
            break
        achieved.append(status)
    return {
        "evidence_id": evidence["evidence_id"],
        "scope": evidence["scope"],
        "profile": evidence.get("profile"),
        "derived_maturity": achieved[-1] if achieved else None,
        "satisfied_statuses": achieved,
        "next_status": policy["ordered_statuses"][len(achieved)]
        if len(achieved) < len(policy["ordered_statuses"])
        else None,
        "missing_requirements": first_missing,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象：{path}")
    return value


def validate_evidence(evidence: Mapping[str, Any]) -> None:
    schema = _load_json(SCHEMA_PATH)
    errors = sorted(Draft202012Validator(schema).iter_errors(evidence), key=lambda e: list(e.path))
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError("capability_evidence 不符合 Schema：" + details)


def main() -> int:
    parser = argparse.ArgumentParser(description="从能力证据派生成熟度，不接受手填状态")
    parser.add_argument("--evidence", required=True, type=Path, help="capability_evidence JSON 文件")
    args = parser.parse_args()
    evidence = _load_json(args.evidence)
    validate_evidence(evidence)
    result = derive_maturity(evidence, _load_json(POLICY_PATH))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
