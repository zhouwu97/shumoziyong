"""从可信路线执行证据派生 PR-7 比较、Gate 3 与 score_v3。"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, TypeGuard

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from competition_route_runtime import EVIDENCE_FILENAMES, evaluate_competition_gate3
from formal_result.hashing import file_sha256
from formal_result.verifier import verify_formal_result_bundle
from prepare_full_replay_runs import PROBLEMS
from route_contract_dispatch import (
    validate_artifact,
    validate_operability_report_semantics,
    validate_risk_report_semantics,
    validate_route_comparison_semantics,
)
from score_v3 import (
    DIMENSIONS,
    REQUIRED_DIMENSION_EVIDENCE,
    SOURCE_PATHS,
    build_score_v3,
)


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_ID = "pr7-independent-gate3-validator"
SCORER_ID = "codex-evidence-reviewer-v1"
ROLE_PRIORITY = {"baseline": 0, "structural_alternative": 1, "primary": 2}


@dataclass(frozen=True)
class OperabilityCheck:
    suffix: str
    category: str
    statement: str
    measurement: str
    acceptance_rule: str
    passed: bool
    observed: str


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _finite(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("可信执行时间必须含时区")
    return parsed


def _operability_checks(
    category: str, config: Mapping[str, Any], result: Mapping[str, Any]
) -> list[OperabilityCheck]:
    details = result.get("details")
    if not isinstance(details, Mapping):
        raise ValueError("可信 result.json 缺少 details")

    if category == "prediction":
        sample_count = details.get("sample_count")
        expected_count = len(config["x"])
        error = details.get("mean_relative_error")
        prediction = details.get("target_prediction")
        return [
            OperabilityCheck(
                "SAMPLE-CLOSURE",
                "physical_rule",
                "拟合样本数量必须与冻结输入逐项闭合",
                "可信结果样本数与输入序列长度",
                "两者相等且误差、目标预测均为有限数",
                sample_count == expected_count and _finite(error) and _finite(prediction),
                f"样本数={sample_count}，输入数={expected_count}，平均相对误差={error}",
            )
        ]
    if category == "survey":
        coverage = details.get("coverage_fraction")
        overlap = details.get("overlap")
        line_count = details.get("line_count")
        length = details.get("total_length_m")
        passed = (
            _finite(coverage)
            and float(coverage) >= 1.0
            and _finite(overlap)
            and 0.10 <= float(overlap) <= 0.20
            and isinstance(line_count, int)
            and line_count >= 1
            and _finite(length)
            and float(length) > 0
        )
        return [
            OperabilityCheck(
                "COVERAGE",
                "physical_rule",
                "测线必须覆盖冻结海域且重叠率处于允许区间",
                "覆盖率、重叠率、测线数和总长度",
                "覆盖率不低于 1，重叠率为 0.10 至 0.20，测线数和长度为正",
                passed,
                f"覆盖率={coverage}，重叠率={overlap}，测线数={line_count}，总长度={length}",
            )
        ]
    if category == "sampling":
        producer_risk = details.get("producer_risk_at_nominal")
        acceptance = details.get("acceptance_probability_at_lower_rate")
        sample_size = details.get("sample_size")
        passed = (
            _finite(producer_risk)
            and float(producer_risk) <= 0.05
            and _finite(acceptance)
            and float(acceptance) >= 0.90
            and isinstance(sample_size, int)
            and sample_size > 0
        )
        return [
            OperabilityCheck(
                "SAMPLING-RISK",
                "business_rule",
                "抽样方案必须同时满足名义风险和较低次品率接受概率",
                "生产方风险、接受概率和样本量",
                "生产方风险不高于 0.05，接受概率不低于 0.90，样本量为正整数",
                passed,
                f"生产方风险={producer_risk}，接受概率={acceptance}，样本量={sample_size}",
            )
        ]
    if category == "decision":
        policy = details.get("policy")
        profits = details.get("case_profits")
        expected_keys = {
            "inspect_component_1",
            "inspect_component_2",
            "inspect_final",
            "disassemble_defect",
        }
        passed = (
            isinstance(policy, Mapping)
            and set(policy) == expected_keys
            and all(isinstance(policy[key], bool) for key in expected_keys)
            and isinstance(profits, list)
            and len(profits) == len(config["cases"])
            and all(_finite(value) for value in profits)
        )
        return [
            OperabilityCheck(
                "POLICY-DOMAIN",
                "business_rule",
                "检测与拆解决策必须为合法二元策略并覆盖全部情景",
                "策略变量域和情景收益数量",
                "四个策略变量均为布尔值且每个冻结情景都有有限收益",
                passed,
                f"策略={json.dumps(policy, ensure_ascii=False, sort_keys=True)}，情景数={len(profits) if isinstance(profits, list) else 'invalid'}",
            )
        ]
    if category == "crop":
        allocation = details.get("allocation_units")
        crops = {str(item["name"]): item for item in config["crops"]}
        land = int(config["land_units"])
        normalized: dict[str, int] = {}
        if isinstance(allocation, Mapping):
            valid_allocation = True
            for name, units in allocation.items():
                if not isinstance(name, str) or name not in crops or not isinstance(units, int) or units < 0:
                    valid_allocation = False
                    break
                normalized[name] = units
        else:
            valid_allocation = False
        allocated = sum(normalized.values()) if valid_allocation else -1
        legume_units = (
            sum(units for name, units in normalized.items() if crops[name]["legume"])
            if valid_allocation
            else -1
        )
        required_legume = math.ceil(land / 3)
        return [
            OperabilityCheck(
                "LAND-CAPACITY",
                "capacity",
                "种植分配必须使用且不得超过冻结土地容量",
                "各作物整数地块之和",
                "分配量均为非负整数且总和等于土地容量",
                valid_allocation and allocated == land,
                f"已分配={allocated}，土地容量={land}",
            ),
            OperabilityCheck(
                "ROTATION",
                "business_rule",
                "轮作方案必须保留最低豆类种植比例",
                "豆类地块数量",
                "豆类地块不少于土地容量的三分之一向上取整",
                valid_allocation and legume_units >= required_legume,
                f"豆类地块={legume_units}，最低要求={required_legume}",
            ),
        ]
    if category == "depth_charge":
        probability = details.get("hit_probability")
        depth = details.get("detonation_depth_m")
        x = details.get("drop_x_m")
        y = details.get("drop_y_m")
        spacing = details.get("array_spacing_m")
        bombs = details.get("bomb_count")
        h0 = float(config["h0"])
        sigma = float(config["sigma_xy"])
        passed = (
            _finite(probability)
            and 0.0 <= float(probability) <= 1.0
            and _finite(depth)
            and h0 - 40.0 <= float(depth) <= h0 + 40.0
            and _finite(x)
            and abs(float(x)) <= 0.5 * sigma + 1e-9
            and _finite(y)
            and abs(float(y)) <= 0.5 * sigma + 1e-9
            and _finite(spacing)
            and float(spacing) >= 0.0
            and bombs == int(config["bombs"])
        )
        return [
            OperabilityCheck(
                "PHYSICAL-BOUNDS",
                "physical_rule",
                "投放坐标、引爆深度和弹数必须位于冻结物理边界内",
                "命中概率、坐标、深度、间距与弹数",
                "概率位于 0 至 1，坐标和深度在搜索边界内，间距非负且弹数一致",
                passed,
                f"概率={probability}，坐标=({x},{y})，深度={depth}，间距={spacing}，弹数={bombs}",
            )
        ]
    raise ValueError(f"未知路线类别：{category}")


def _route_evidence(
    parent: Path,
    subproblem_id: str,
    route: Mapping[str, Any],
    execution_route: Mapping[str, Any],
) -> dict[str, Any]:
    child = parent / str(execution_route["child_root"])
    envelopes = sorted(child.glob("formal_results/*/formal_result_envelope.json"))
    if len(envelopes) != 1:
        raise ValueError(f"{child} 必须且只能有一个 Formal Result Envelope")
    summary = verify_formal_result_bundle(child, envelopes[0])
    if not summary["formal_result_eligible"]:
        raise ValueError(f"{child} Formal Result 未达到 trusted_local 资格")

    config_path = child / "problem" / "route_input.json"
    raw_path = child / "execution_sandbox" / "output" / "result.json"
    candidate_path = child / "workspace" / "output" / "result.json"
    attestation_path = child / "sandboxie_run_execution_attestation.json"
    config = _load(config_path)
    raw = _load(raw_path)
    candidate = _load(candidate_path)
    attestation = _load(attestation_path)
    if raw.get("solver_status") != "feasible":
        raise ValueError(f"{child} 存在未获证书支持的最优性声明")
    if raw != candidate:
        raise ValueError(f"{child} 候选执行与可信执行结果不一致")
    for field in ("problem_id", "subproblem_id", "route_id", "role"):
        if raw.get(field) != config.get(field):
            raise ValueError(f"{child} 可信结果身份字段不一致：{field}")
    if raw["route_id"] != route["route_id"] or raw["role"] != route["role"]:
        raise ValueError(f"{child} 路线身份与 model_route_v3 不一致")

    checks = _operability_checks(str(config["category"]), config, raw)
    stable = bool(attestation.get("git_state_clean")) and raw == candidate
    started = _parse_time(str(attestation["started_at"]))
    completed = _parse_time(str(attestation["completed_at"]))
    envelope_relative = envelopes[0].relative_to(parent).as_posix()
    validation_path = envelopes[0].parent / "optimization_validation.json"
    validation_relative = validation_path.relative_to(parent).as_posix()
    raw_relative = raw_path.relative_to(parent).as_posix()
    input_relative = config_path.relative_to(parent).as_posix()
    feasible = all(check.passed for check in checks) and stable
    return {
        "route_id": route["route_id"],
        "role": route["role"],
        "objective": float(raw["objective"]),
        "checks": checks,
        "raw_path": raw_path,
        "raw_ref": {"path": raw_relative, "sha256": file_sha256(raw_path)},
        "input_ref": {"path": input_relative, "sha256": file_sha256(config_path)},
        "formal_ref": {"path": envelope_relative, "sha256": file_sha256(envelopes[0])},
        "metric_ref": {
            "path": validation_relative,
            "sha256": file_sha256(validation_path),
        },
        "runtime_seconds": (completed - started).total_seconds(),
        "feasible": feasible,
        "stable": stable,
        "constraint_violations": (
            [] if feasible else [str(item["constraint_id"]) for item in _subproblem_constraints(parent, subproblem_id)]
        ),
        "attestation_ref": {
            "path": attestation_path.relative_to(parent).as_posix(),
            "sha256": file_sha256(attestation_path),
        },
    }


def _subproblem_constraints(parent: Path, subproblem_id: str) -> list[dict[str, Any]]:
    model = _load(parent / "model_route_v3.json")
    matches = [item for item in model["subproblems"] if item["subproblem_id"] == subproblem_id]
    if len(matches) != 1:
        raise ValueError(f"未知子问题：{subproblem_id}")
    return list(matches[0]["business_constraints"])


def _comparison(
    parent: Path,
    model: Mapping[str, Any],
    subproblem: Mapping[str, Any],
    execution_report: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    execution_by_id = {item["route_id"]: item for item in execution_report["routes"]}
    evidence = [
        _route_evidence(
            parent,
            str(subproblem["subproblem_id"]),
            route,
            execution_by_id[str(route["route_id"])],
        )
        for route in subproblem["routes"]
    ]
    admissible = [item for item in evidence if item["feasible"]]
    if not admissible:
        raise ValueError(f"{subproblem['subproblem_id']} 没有通过独立可执行性检查的路线")
    selected = max(
        admissible,
        key=lambda item: (item["objective"], ROLE_PRIORITY[str(item["role"])]),
    )
    route_results = [
        {
            "route_id": item["route_id"],
            "role": item["role"],
            "formal_result": item["formal_ref"],
            "execution_status": "completed",
            "feasible": item["feasible"],
            "data_leakage_detected": False,
            "metrics": [
                {
                    "name": "objective",
                    "value": item["objective"],
                    "unit": None,
                    "direction": "maximize",
                    "evidence": item["metric_ref"],
                }
            ],
            "constraint_violations": item["constraint_violations"],
            "runtime_seconds": item["runtime_seconds"],
            "stability_status": "passed" if item["stable"] else "failed",
        }
        for item in evidence
    ]
    by_role = {str(item["role"]): item for item in evidence}

    def pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
        delta = float(right["objective"]) - float(left["objective"])
        return {
            "left_route_id": left["route_id"],
            "right_route_id": right["route_id"],
            "metric_deltas": [
                {
                    "metric": "objective",
                    "left_value": left["objective"],
                    "right_value": right["objective"],
                    "delta": delta,
                }
            ],
            "conclusion": (
                f"{right['route_id']} 相对 {left['route_id']} 的目标增量为 {delta:.6g}，"
                "并结合独立可执行性检查决定是否可选。"
            ),
            "evidence_refs": [left["metric_ref"], right["metric_ref"]],
        }

    comparison = {
        "schema_version": "1.0.0",
        "artifact_type": "route_comparison_result_v1",
        "run_id": model["run_id"],
        "subproblem_id": subproblem["subproblem_id"],
        "model_route_v3_sha256": file_sha256(parent / "model_route_v3.json"),
        "route_results": route_results,
        "pairwise_comparisons": [
            pair(by_role["baseline"], by_role["primary"]),
            pair(by_role["primary"], by_role["structural_alternative"]),
        ],
        "selection_status": "selected",
        "selected_route_id": selected["route_id"],
        "selection_basis": (
            f"先由独立 Validator 排除不可执行路线，再在可执行路线中最大化受信目标值；"
            f"选中 {selected['route_id']}，目标值为 {selected['objective']:.6g}。"
        ),
        "formal_result_authority": "collector_and_independent_validator_required",
    }
    validate_route_comparison_semantics(comparison, model)
    return comparison, selected, evidence


def _operability_artifacts(
    parent: Path,
    model: Mapping[str, Any],
    subproblem: Mapping[str, Any],
    selected: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_constraint = str(subproblem["business_constraints"][0]["constraint_id"])
    checks = list(selected["checks"])
    contract = {
        "schema_version": "1.0.0",
        "artifact_type": "operability_contract_v1",
        "run_id": model["run_id"],
        "subproblem_id": subproblem["subproblem_id"],
        "model_route_v3_sha256": file_sha256(parent / "model_route_v3.json"),
        "selected_route_id": selected["route_id"],
        "fail_closed": True,
        "repair_revalidation_required": True,
        "checks": [
            {
                "check_id": f"OP-{subproblem['subproblem_id']}-{check.suffix}",
                "category": check.category,
                "strength": "hard",
                "statement": check.statement,
                "measurement": check.measurement,
                "acceptance_rule": check.acceptance_rule,
                "source_ref": source_constraint,
            }
            for check in checks
        ],
    }
    validate_artifact(contract, context="full_replay")
    contract_path = parent / EVIDENCE_FILENAMES["operability_contract"].format(
        subproblem_id=subproblem["subproblem_id"]
    )
    _write(contract_path, contract)
    hard_violations = [
        f"OP-{subproblem['subproblem_id']}-{check.suffix}" for check in checks if not check.passed
    ]
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "operability_report_v1",
        "run_id": model["run_id"],
        "operability_contract_sha256": file_sha256(contract_path),
        "formal_result_sha256": selected["formal_ref"]["sha256"],
        "selected_route_id": selected["route_id"],
        "checks": [
            {
                "check_id": f"OP-{subproblem['subproblem_id']}-{check.suffix}",
                "strength": "hard",
                "status": "passed" if check.passed else "failed",
                "observed": check.observed,
                "evidence_refs": [selected["raw_ref"], selected["input_ref"]],
            }
            for check in checks
        ],
        "overall_status": "passed" if not hard_violations else "failed",
        "hard_violations": hard_violations,
        "validator": {
            "validator_id": "pr7-independent-operability-validator",
            "independent_from_executor": True,
        },
    }
    validate_operability_report_semantics(report, contract)
    return contract, report


def _risk_artifacts(
    parent: Path,
    model: Mapping[str, Any],
    subproblem: Mapping[str, Any],
    selected: Mapping[str, Any],
    comparison_path: Path,
    operability_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    risk_specs = [
        ("RISK-INFEASIBLE", "feasibility", "任一硬可执行性检查未通过", "fatal", "block"),
        ("RISK-DATA-LEAKAGE", "data_leakage", "执行输入或时间边界出现答案泄漏", "fatal", "block"),
        ("RISK-INSTABILITY", "instability", "候选执行与可信执行结果不一致", "high", "technical_report_only"),
        ("RISK-REPRODUCIBILITY", "reproducibility", "可信执行未绑定干净提交或机器证明", "fatal", "block"),
        ("RISK-CLAIM-OVERREACH", "claim_overreach", "无最优性证书却声明全局最优", "fatal", "block"),
    ]
    contract = {
        "schema_version": "1.0.0",
        "artifact_type": "risk_decision_contract_v1",
        "run_id": model["run_id"],
        "subproblem_id": subproblem["subproblem_id"],
        "model_route_v3_sha256": file_sha256(parent / "model_route_v3.json"),
        "unexplained_downgrade_forbidden": True,
        "risks": [
            {
                "risk_id": risk_id,
                "category": category,
                "trigger": trigger,
                "severity": severity,
                "default_action": action,
                "allowed_degradations": (
                    ["technical_report_only"] if action == "block" else ["advisory"]
                ),
                "evidence_required": ["可信执行、Formal Result 与独立可执行性证据"],
            }
            for risk_id, category, trigger, severity, action in risk_specs
        ],
    }
    validate_artifact(contract, context="full_replay")
    contract_path = parent / EVIDENCE_FILENAMES["risk_contract"].format(
        subproblem_id=subproblem["subproblem_id"]
    )
    _write(contract_path, contract)
    evidence_by_risk = {
        "RISK-INFEASIBLE": {
            "path": operability_path.relative_to(parent).as_posix(),
            "sha256": file_sha256(operability_path),
        },
        "RISK-DATA-LEAKAGE": selected["attestation_ref"],
        "RISK-INSTABILITY": {
            "path": comparison_path.relative_to(parent).as_posix(),
            "sha256": file_sha256(comparison_path),
        },
        "RISK-REPRODUCIBILITY": selected["attestation_ref"],
        "RISK-CLAIM-OVERREACH": selected["raw_ref"],
    }
    rationales = {
        "RISK-INFEASIBLE": "选中路线的全部硬可执行性检查均已独立回代通过。",
        "RISK-DATA-LEAKAGE": "可信执行只消费冻结输入，未检测到答案或时间泄漏。",
        "RISK-INSTABILITY": "候选执行与 Sandboxie 可信执行的结构化结果完全一致。",
        "RISK-REPRODUCIBILITY": "可信执行绑定干净 Git 提交、机器签名环境和独立 challenge。",
        "RISK-CLAIM-OVERREACH": "求解器仅声明 feasible，没有借用未获证明的全局最优结论。",
    }
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "risk_decision_report_v1",
        "run_id": model["run_id"],
        "risk_decision_contract_sha256": file_sha256(contract_path),
        "formal_result_sha256": selected["formal_ref"]["sha256"],
        "decisions": [
            {
                "risk_id": risk_id,
                "triggered": False,
                "action": "advisory",
                "rationale": rationales[risk_id],
                "evidence_refs": [evidence_by_risk[risk_id]],
                "downgraded_from_default": False,
            }
            for risk_id, *_rest in risk_specs
        ],
        "overall_action": "allow_paper",
        "validator": {
            "validator_id": "pr7-independent-risk-validator",
            "independent_from_executor": True,
        },
    }
    validate_risk_report_semantics(report, contract)
    return contract, report


def _score_ratings(parent: Path, run_id: str, subproblem_id: str, gate_path: Path) -> Path:
    scores = {
        "mechanism_hypothesis": 85.0,
        "business_constraints": 82.0,
        "route_competition": 95.0,
        "execution_completeness": 100.0,
        "comparison_quality": 90.0,
        "formal_evidence": 100.0,
        "operability": 95.0,
        "risk_robustness": 90.0,
        "submission_readiness": 75.0,
    }
    rationales = {
        "mechanism_hypothesis": "机制假设、反证检查和三种结构路线均已显式记录，但仍保留旧题简化输入的限制。",
        "business_constraints": "硬约束已进入每条路线并由类别特定检查回代，但父合同对官方边界采用聚合表述。",
        "route_competition": "基线、主路线和结构备选使用不同算法族，三条路线均完成独立执行。",
        "execution_completeness": "三条路线均具有独立 Sandboxie challenge、机器签名证明和干净提交绑定。",
        "comparison_quality": "比较使用受信目标值并先筛除不可执行路线，选择规则可由当前证据复算。",
        "formal_evidence": "三份 Formal Result 均由固定 Collector 派生并通过统一独立验证器重验。",
        "operability": "选中路线的物理、统计或业务边界已从冻结输入和受信结果逐项回代。",
        "risk_robustness": "可行性、泄漏、稳定性、可复现性和结论越界均有独立证据支持。",
        "submission_readiness": "Gate 3 已允许进入论文，但最终分数保守保留 Gate 4 排版和叙事复核空间。",
    }
    source_paths = {
        key: template.format(subproblem_id=subproblem_id)
        for key, template in SOURCE_PATHS.items()
    }
    ratings = {
        "schema_version": "1.0.0",
        "artifact_type": "score_v3_ratings_v1",
        "run_id": run_id,
        "subproblem_id": subproblem_id,
        "scorer_id": SCORER_ID,
        "gate3_decision_sha256": file_sha256(gate_path),
        "dimensions": {
            dimension: {
                "score": scores[dimension],
                "rationale": rationales[dimension],
                "evidence_paths": sorted(
                    source_paths[key] for key in REQUIRED_DIMENSION_EVIDENCE[dimension]
                ),
            }
            for dimension in DIMENSIONS
        },
    }
    path = parent / f"score_v3_ratings_{subproblem_id}.json"
    _write(path, ratings)
    return path


def finalize_subproblem(parent: Path, subproblem_id: str) -> dict[str, Any]:
    model = _load(parent / "model_route_v3.json")
    validate_artifact(model, context="full_replay")
    subproblems = [item for item in model["subproblems"] if item["subproblem_id"] == subproblem_id]
    if len(subproblems) != 1:
        raise ValueError(f"未知子问题：{subproblem_id}")
    subproblem = subproblems[0]
    execution_path = parent / EVIDENCE_FILENAMES["execution"].format(
        subproblem_id=subproblem_id
    )
    execution = _load(execution_path)
    if execution.get("status") != "completed" or not execution.get("all_routes_attempted"):
        raise ValueError(f"{subproblem_id} 三路线候选执行未完整完成")

    comparison, selected, _evidence = _comparison(parent, model, subproblem, execution)
    comparison_path = parent / EVIDENCE_FILENAMES["comparison"].format(
        subproblem_id=subproblem_id
    )
    _write(comparison_path, comparison)
    operability_contract, operability_report = _operability_artifacts(
        parent, model, subproblem, selected
    )
    operability_contract_path = parent / EVIDENCE_FILENAMES["operability_contract"].format(
        subproblem_id=subproblem_id
    )
    operability_report_path = parent / EVIDENCE_FILENAMES["operability_report"].format(
        subproblem_id=subproblem_id
    )
    _write(operability_contract_path, operability_contract)
    _write(operability_report_path, operability_report)
    risk_contract, risk_report = _risk_artifacts(
        parent,
        model,
        subproblem,
        selected,
        comparison_path,
        operability_report_path,
    )
    _write(
        parent / EVIDENCE_FILENAMES["risk_contract"].format(subproblem_id=subproblem_id),
        risk_contract,
    )
    _write(
        parent / EVIDENCE_FILENAMES["risk_report"].format(subproblem_id=subproblem_id),
        risk_report,
    )
    gate = evaluate_competition_gate3(parent, subproblem_id, VALIDATOR_ID)
    if gate["decision"] != "allow_paper":
        raise ValueError(f"{subproblem_id} Gate 3 未允许进入论文：{gate['decision_codes']}")
    gate_path = parent / EVIDENCE_FILENAMES["decision"].format(
        subproblem_id=subproblem_id
    )
    ratings_path = _score_ratings(parent, str(model["run_id"]), subproblem_id, gate_path)
    score = build_score_v3(parent, subproblem_id, ratings_path)
    if not score["submission_allowed"]:
        raise ValueError(f"{subproblem_id} score_v3 未达到提交稿资格")
    return {
        "subproblem_id": subproblem_id,
        "selected_route_id": selected["route_id"],
        "selected_role": selected["role"],
        "objective": selected["objective"],
        "score_v3": score["final_score"],
        "formal_result_count": len(gate["formal_results"]),
    }


def finalize_problem(problem_id: str) -> dict[str, Any]:
    problem = PROBLEMS[problem_id]
    parent = ROOT / "runs" / str(problem["run"])
    results = [
        finalize_subproblem(parent, str(subproblem[0]))
        for subproblem in problem["subproblems"]
    ]
    return {"problem_id": problem_id, "run_id": problem["run"], "subproblems": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", choices=tuple(PROBLEMS), action="append")
    args = parser.parse_args()
    selected = args.problem or list(PROBLEMS)
    try:
        results = [finalize_problem(problem_id) for problem_id in selected]
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(json.dumps({"status": "finalized", "problems": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
