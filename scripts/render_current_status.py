"""从 Runtime Profile 与能力证据生成唯一的当前状态页面。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from derive_capability_maturity import derive_maturity, validate_evidence


EVIDENCE_PATH = ROOT / "capability_evidence" / "current" / "engineering_optimization.json"
PROFILE_PATH = ROOT / "runtime_profiles" / "engineering_optimization.json"
CAPABILITY_POLICY_PATH = ROOT / "policies" / "capability_maturity_policy.json"
RUNTIME_PROFILE_SCHEMA_PATH = ROOT / "schemas" / "runtime_profile.schema.json"
OUTPUT_PATH = ROOT / "docs" / "status" / "CURRENT_STATUS.md"

GENERATED_HEADER = """<!--
AUTO-GENERATED FILE.
Source:
- capability_evidence/current/engineering_optimization.json
- runtime_profiles/engineering_optimization.json
- policies/capability_maturity_policy.json

Regenerate:
python scripts/render_current_status.py

DO NOT EDIT MANUALLY.
-->"""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"缺少{label}：{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取{label}：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}根节点必须是对象：{path}")
    return value


def _validate_runtime_profile(profile: Mapping[str, Any], schema_path: Path) -> None:
    schema = _load_object(schema_path, "Runtime Profile Schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(profile),
        key=lambda error: list(error.path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError("Runtime Profile 不符合 Schema：" + details)


def _qualification_eligible(
    capability_report: Mapping[str, Any],
    evidence: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> bool:
    """只从派生成熟度和已验证资格题计算资格可用性。"""
    ordered_statuses = policy.get("ordered_statuses")
    if not isinstance(ordered_statuses, list) or "profile_qualified" not in ordered_statuses:
        raise ValueError("能力政策缺少 profile_qualified 状态")
    qualification_index = ordered_statuses.index("profile_qualified")
    allowed_states = set(ordered_statuses[qualification_index:])
    derived_maturity = capability_report.get("derived_maturity")
    satisfied_statuses = capability_report.get("satisfied_statuses", [])
    qualification_cases = evidence.get("qualification_cases", [])
    cases_are_valid = (
        isinstance(qualification_cases, list)
        and bool(qualification_cases)
        and isinstance(satisfied_statuses, list)
        and "profile_qualified" in satisfied_statuses
    )
    return (
        isinstance(derived_maturity, str) and derived_maturity in allowed_states and cases_are_valid
    )


def build_status_model(
    *,
    evidence_path: Path = EVIDENCE_PATH,
    profile_path: Path = PROFILE_PATH,
    capability_policy_path: Path = CAPABILITY_POLICY_PATH,
    runtime_profile_schema_path: Path = RUNTIME_PROFILE_SCHEMA_PATH,
) -> dict[str, Any]:
    """构建分离命名空间的状态模型，不比较两类成熟度。"""
    evidence = _load_object(evidence_path, "Capability Evidence")
    validate_evidence(evidence)
    profile = _load_object(profile_path, "Runtime Profile")
    _validate_runtime_profile(profile, runtime_profile_schema_path)
    policy = _load_object(capability_policy_path, "Capability Maturity Policy")
    capability_report = derive_maturity(evidence, policy)

    benchmark = evidence["benchmark"]
    assert isinstance(benchmark, dict)  # Schema 验证已保证类型。
    return {
        "runtime_profile": {
            "profile": profile["profile_id"],
            "version": profile["version"],
            "lifecycle_state": profile["maturity"],
            "validation_record_count": len(profile["validation_records"]),
        },
        "capability_policy": {
            "derived_maturity": capability_report["derived_maturity"],
            "qualification_eligible": _qualification_eligible(capability_report, evidence, policy),
            "next_target": capability_report["next_status"],
            "missing_requirements": capability_report["missing_requirements"],
        },
        "evidence": {
            "qualification_case_count": len(evidence["qualification_cases"]),
            "blind_benchmark_case_count": len(benchmark["blind_cases"]),
            "simulation_count": len(evidence["simulations"]),
            "independent_review_count": len(evidence["independent_reviews"]),
        },
    }


def render_current_status(
    *,
    evidence_path: Path = EVIDENCE_PATH,
    profile_path: Path = PROFILE_PATH,
    capability_policy_path: Path = CAPABILITY_POLICY_PATH,
    runtime_profile_schema_path: Path = RUNTIME_PROFILE_SCHEMA_PATH,
) -> str:
    """返回稳定、可字节比较的 Markdown。"""
    model = build_status_model(
        evidence_path=evidence_path,
        profile_path=profile_path,
        capability_policy_path=capability_policy_path,
        runtime_profile_schema_path=runtime_profile_schema_path,
    )
    runtime = model["runtime_profile"]
    capability = model["capability_policy"]
    evidence = model["evidence"]
    missing = capability["missing_requirements"]
    missing_lines = [f"- {item}" for item in missing] or ["- 无"]
    qualification = str(capability["qualification_eligible"]).lower()
    lines = [
        GENERATED_HEADER,
        "",
        "# 当前状态",
        "",
        "Runtime Profile lifecycle 与 Capability Policy maturity 属于不同命名空间，",
        "不得相互比较、覆盖或据此推断资格状态。",
        "",
        "## Runtime Profile",
        "",
        f"- profile: `{runtime['profile']}`",
        f"- version: `{runtime['version']}`",
        f"- lifecycle state: `{runtime['lifecycle_state']}`",
        f"- validation records: `{runtime['validation_record_count']}`",
        "",
        "## Capability Policy",
        "",
        f"- derived maturity: `{capability['derived_maturity']}`",
        f"- qualification eligible: `{qualification}`",
        f"- next target: `{capability['next_target']}`",
        "",
        "### Missing requirements",
        "",
        *missing_lines,
        "",
        "## Evidence",
        "",
        f"- qualification cases: `{evidence['qualification_case_count']}`",
        f"- blind benchmark cases: `{evidence['blind_benchmark_case_count']}`",
        f"- simulations: `{evidence['simulation_count']}`",
        f"- independent reviews: `{evidence['independent_review_count']}`",
        "",
        "## Legacy labels",
        "",
        "`candidate+`、`stable candidate`、`verified_candidate / cross_mechanism / L4`",
        "仅为旧训练流程中的历史标签，不构成当前机器状态或 Profile Qualification。",
        "",
    ]
    return "\n".join(lines)


def write_current_status(
    output_path: Path = OUTPUT_PATH,
    *,
    evidence_path: Path = EVIDENCE_PATH,
    profile_path: Path = PROFILE_PATH,
    capability_policy_path: Path = CAPABILITY_POLICY_PATH,
    runtime_profile_schema_path: Path = RUNTIME_PROFILE_SCHEMA_PATH,
) -> None:
    content = render_current_status(
        evidence_path=evidence_path,
        profile_path=profile_path,
        capability_policy_path=capability_policy_path,
        runtime_profile_schema_path=runtime_profile_schema_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="生成机器派生的当前状态页面")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    write_current_status(args.output)
    print(f"已生成：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
