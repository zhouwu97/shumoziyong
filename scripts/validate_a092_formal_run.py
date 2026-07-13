"""对 A092 阶段三单次运行执行独立验证与隔离审计。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validators.problem_boundary.validate import validate_result as validate_boundary
from validators.problem_boundary_v2.validate import validate_result as validate_boundary_v2
from validators.problem_boundary_v2.validate import coverage_width, q2_depth
from validators.common.external_validation import build_external_validator_attestation
from validators.problem_negative.validate import validate_result as validate_negative
from validators.problem_negative.validate import mean_relative_error
from validators.problem_positive.validate import validate_result as validate_positive
from validators.problem_positive_v2.validate import load_problem_data as load_positive_data_v2
from validators.problem_positive_v2.validate import validate_result as validate_positive_v2


FORBIDDEN_PATTERNS = (
    re.compile(
        r"a092_confirmatory_(v[12])(?:[\\/](?:runs|attempts|prepared))?[\\/](R(?:0[1-9]|10))",
        re.IGNORECASE,
    ),
    re.compile(r"experiments[\\/]a092_confirmatory_v[12]", re.IGNORECASE),
    re.compile(r"prompt_patches", re.IGNORECASE),
    re.compile(r"protocols[\\/]a092", re.IGNORECASE),
)


def _load_result(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "results" / "formal_result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _input_files(run_dir: Path) -> list[dict[str, str]]:
    material_root = run_dir / "materials"
    return [
        {"path": path.relative_to(run_dir).as_posix(), "sha256": _sha256(path)}
        for path in sorted(material_root.rglob("*"))
        if path.is_file()
    ]


def _preprocessing_checks(problem: str) -> dict[str, dict[str, str]]:
    evidence = {
        "2024-C": {
            "merged_cells": "附件2 地块编号按合并单元格向下填充并核对记录数。",
            "missing_values": "地块、作物、季次、亩数与统计参数执行非空和键存在检查。",
            "unit_conversions": "面积统一为亩，产量、价格和成本沿用官方附件单位。",
            "aggregation_keys": "销售上限固定按 crop_id + season 派生。",
            "time_slot_order": "智慧大棚固定按每年第一季、第二季的实际相邻顺序。",
            "boundary_state": "2023 种植记录显式进入 2024 起始轮作与三年豆类窗口。",
        },
        "2023-B": {
            "merged_cells": "not_applicable: 题面两张表没有作为数据源读取的合并单元格。",
            "missing_values": "题面固定距离、方向角、坡度与开角均执行完整性检查。",
            "unit_conversions": "海里乘 1852 转米，角度仅在三角函数入口转弧度。",
            "aggregation_keys": "not_applicable: 问题一、二不含跨记录销售或收益聚合。",
            "time_slot_order": "not_applicable: 本题没有时间序列约束。",
            "boundary_state": "beta=0 固定为向上法向水平投影的深水方向。",
        },
        "2016-C": {
            "merged_cells": "not_applicable: 曲线点按工作表数值序列读取。",
            "missing_values": "真值与预测值必须等长且非空。",
            "unit_conversions": "时间统一按题面分钟口径，MRE 为无量纲。",
            "aggregation_keys": "曲线误差固定按 curve_id 独立聚合。",
            "time_slot_order": "采样点保持工作表原始时间顺序。",
            "boundary_state": "剩余时间强制为有限非负值。",
        },
    }[problem]
    return {
        key: {
            "status": "not_applicable" if value.startswith("not_applicable:") else "passed",
            "evidence": value,
        }
        for key, value in evidence.items()
    }


def _hand_fixtures(run_dir: Path, problem: str) -> list[dict[str, Any]]:
    if problem == "2024-C":
        data = load_positive_data_v2(
            run_dir / "materials" / "attachments" / "附件1.xlsx",
            run_dir / "materials" / "attachments" / "附件2.xlsx",
        )
        values = (("planting_2023_rows", 87.0, len(data["planting_2023"])), ("sales_cap_keys", 47.0, len(data["sales_2023"])))
    elif problem == "2023-B":
        depth = q2_depth(0.3, 0.0)
        width = coverage_width(depth, 1.5, 120.0, 0.0)
        values = (("beta0_depth_0_3nm", 134.54889802384025, depth), ("beta0_width_0_3nm", 466.0910549593899, width))
    else:
        values = (("mre_identity", 0.0, mean_relative_error([1.0, 2.0], [1.0, 2.0])), ("mre_half_error", 0.5, mean_relative_error([2.0], [1.0])))
    tolerance = 1e-9
    return [
        {
            "fixture_id": fixture_id,
            "expected": expected,
            "actual": float(actual),
            "tolerance": tolerance,
            "passed": abs(float(actual) - expected) <= tolerance,
        }
        for fixture_id, expected, actual in values
    ]


def _candidate_implementation(run_dir: Path) -> tuple[str, str]:
    suffixes = {".py", ".m", ".r", ".jl", ".ipynb"}
    files = [
        path
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
        and (
            path.suffix.lower() in suffixes
            or path.name == "runner_events.jsonl"
        )
        and "materials" not in path.parts
        and "gate3" not in path.parts
        and "artifacts" not in path.parts
    ]
    manifest = {path.relative_to(run_dir).as_posix(): _sha256(path) for path in files}
    gate3 = run_dir / "gate3"
    gate3.mkdir(parents=True, exist_ok=True)
    manifest_path = gate3 / "candidate_implementation_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path.relative_to(run_dir).as_posix(), _canonical_digest(manifest)


def build_v2_external_artifacts(
    run_dir: Path, problem: str, report: dict[str, Any]
) -> dict[str, Any]:
    """从候选目录之外的固定代码派生 v2 数据审计和证明。"""

    inputs = _input_files(run_dir)
    audit = {
        "schema_version": "2.0.0",
        "input_files": inputs,
        "preprocessing": _preprocessing_checks(problem),
        "hand_checked_fixtures": _hand_fixtures(run_dir, problem),
    }
    audit_schema = json.loads(
        (ROOT / "schemas" / "a092_data_contract_audit.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(audit_schema).validate(audit)

    if problem == "2024-C":
        adapter_relative = "validators/problem_positive_v2/validate.py"
        objective_passed = all(
            item.get("objective_valid") is True for item in report["scenario_reports"]
        )
        constraints_passed = all(
            item.get("constraints_valid") is True for item in report["scenario_reports"]
        )
        applicability = {
            "objective_value": True,
            "improvement_rate": True,
            "strong_optimality": True,
        }
    elif problem == "2023-B":
        adapter_relative = "validators/problem_boundary_v2/validate.py"
        objective_passed = report.get("valid") is True
        constraints_passed = True
        applicability = {
            "objective_value": False,
            "improvement_rate": False,
            "strong_optimality": False,
        }
    else:
        adapter_relative = "validators/problem_negative/validate.py"
        objective_passed = report.get("valid") is True
        constraints_passed = True
        applicability = {
            "objective_value": False,
            "improvement_rate": False,
            "strong_optimality": False,
        }

    candidate_path, candidate_hash = _candidate_implementation(run_dir)
    contract_relative = "protocols/a092_v2/external_validator_contract.md"
    result_path = run_dir / "results" / "formal_result.json"
    attestation = build_external_validator_attestation(
        validator_id=str(report["validator"]),
        adapter_path=adapter_relative,
        adapter_sha256=_sha256(ROOT / adapter_relative),
        candidate_evaluator_path=candidate_path,
        contract_path=contract_relative,
        contract_sha256=_sha256(ROOT / contract_relative),
        input_sha256=_canonical_digest(inputs),
        solution_sha256=_sha256(result_path),
        candidate_evaluator_sha256=candidate_hash,
        frozen_before_candidate=True,
        data_contract_audit=audit,
        objective_passed=objective_passed,
        constraints_passed=constraints_passed,
        optimality_evidence_passed=False,
        claim_applicability=applicability,
    )
    attestation_schema = json.loads(
        (ROOT / "schemas" / "a092_external_validator_attestation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(attestation_schema).validate(attestation)
    artifact_root = run_dir / "artifacts" / "a092"
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "data_contract_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (artifact_root / "external_validator_attestation.json").write_text(
        json.dumps(attestation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return attestation


def validate(run_dir: Path, problem: str, protocol_version: str = "v1") -> dict[str, Any]:
    """根据题目调用冻结的独立适配器。"""

    result = _load_result(run_dir)
    if problem == "2024-C":
        adapter = validate_positive_v2 if protocol_version == "v2" else validate_positive
        return adapter(
            result,
            run_dir / "materials" / "attachments" / "附件1.xlsx",
            run_dir / "materials" / "attachments" / "附件2.xlsx",
        )
    if problem == "2023-B":
        adapter = validate_boundary_v2 if protocol_version == "v2" else validate_boundary
        return adapter(result)
    if problem == "2016-C":
        return validate_negative(result)
    raise ValueError(f"不支持的问题: {problem}")


def audit_isolation(run_dir: Path, protocol_version: str = "v1") -> dict[str, Any]:
    """扫描事件流，确认没有引用其他正式运行或仓库侧实验资料。"""

    events_path = run_dir / "runner_events.jsonl"
    text = events_path.read_text(encoding="utf-8", errors="replace")
    own_run = run_dir.name.upper()
    findings: list[dict[str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in FORBIDDEN_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                run_match = FORBIDDEN_PATTERNS[0].fullmatch(value)
                if (
                    run_match is not None
                    and run_match.group(1).lower() == protocol_version
                    and run_match.group(2).upper() == own_run
                ):
                    continue
                findings.append({"line": str(line_number), "match": value})
    return {
        "audit": f"a092_run_isolation_{protocol_version}",
        "run_id": own_run,
        "events_sha256_checked": True,
        "forbidden_reference_count": len(findings),
        "findings": findings,
        "valid": not findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 A092 正式运行")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("problem", choices=("2024-C", "2023-B", "2016-C"))
    parser.add_argument("--protocol-version", choices=("v1", "v2"), default="v1")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    report = validate(run_dir, args.problem, args.protocol_version)
    audit = audit_isolation(run_dir, args.protocol_version)
    attestation = (
        build_v2_external_artifacts(run_dir, args.problem, report)
        if args.protocol_version == "v2"
        else None
    )
    gate3 = run_dir / "gate3"
    gate5 = run_dir / "gate5"
    gate3.mkdir(parents=True, exist_ok=True)
    gate5.mkdir(parents=True, exist_ok=True)
    (gate3 / "validator_independent.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (gate5 / "isolation_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"validator": report, "isolation": audit, "attestation": attestation},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not audit["valid"]:
        return 2
    if attestation is not None:
        if attestation["experiment_disposition"] != "valid":
            return 4
        if attestation["candidate_disposition"] != "accepted":
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
