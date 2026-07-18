"""Gate A-C 建模合同的加载、语义校验和冻结证据包实现。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from atomic_io import atomic_write_bytes


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
CASE_REQUIRED_JSON = {
    "requirement_map": ("modeling/requirement_map.json", "requirement_map.schema.json"),
    "mechanism_scope_ledger": (
        "modeling/mechanism_scope_ledger.json",
        "mechanism_scope_ledger.schema.json",
    ),
    "route_applicability": (
        "modeling/route_applicability.json",
        "route_applicability.schema.json",
    ),
    "route_falsification_plan": (
        "modeling/route_falsification_plan.json",
        "route_falsification_plan.schema.json",
    ),
    "reference_oracle_registry": (
        "modeling/reference_oracle_registry.json",
        "reference_oracle_registry.schema.json",
    ),
    "contribution_ledger": (
        "modeling/contribution_ledger.json",
        "contribution_ledger.schema.json",
    ),
    "headline_claim_registry": (
        "modeling/headline_claim_registry.json",
        "headline_claim_registry.schema.json",
    ),
}
BUNDLE_ROLES = {
    "problem_manifest": "manifest.yaml",
    "data_contract": "data_contract.yaml",
    "model_spec": "model_spec.md",
    "validator_contract": "validator_contract.yaml",
    "validation_numerics": "validation_numerics.yaml",
    "dependency_boundary_policy": "dependency_boundary_policy.yaml",
    **{role: path for role, (path, _) in CASE_REQUIRED_JSON.items()},
}
TRUTH_ORACLE_TYPES = {
    "analytic_exact_case",
    "human_hand_calculation",
    "independent_literature_formula",
    "high_precision_reference",
}
PROPERTY_ORACLE_TYPES = {
    "dimensional_invariant",
    "symmetry_invariant",
    "limit_case",
    "coordinate_invariance",
    "unit_scaling_property",
    "metamorphic_property",
    "mesh_convergence",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalized_excerpt_sha256(value: str) -> str:
    normalized = " ".join(value.split())
    return sha256_bytes(normalized.encode("utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须为对象：{path}")
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"YAML 顶层必须为对象：{path}")
    return value


def _schema_registry() -> Registry:
    registry = Registry()
    for candidate in SCHEMA_DIR.glob("*.json"):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        schema_id = schema.get("$id")
        if isinstance(schema_id, str):
            registry = registry.with_resource(schema_id, Resource.from_contents(schema))
    return registry


def schema_errors(value: Mapping[str, Any], schema_name: str) -> list[str]:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema,
        registry=_schema_registry(),
        format_checker=FormatChecker(),
    )
    errors = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{schema_name}:{location}: {error.message}")
    return errors


def validate_requirement_map(value: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(value, "requirement_map.schema.json")
    requirements = value.get("requirements", [])
    if not isinstance(requirements, list):
        return errors
    ids: set[str] = set()
    anchors: set[tuple[Any, ...]] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        requirement_id = requirement.get("requirement_id")
        if requirement_id in ids:
            errors.append(f"Requirement ID 重复：{requirement_id}")
        ids.add(str(requirement_id))
        anchor = requirement.get("source_anchor", {})
        anchor_key = (
            anchor.get("document_id"),
            anchor.get("page"),
            anchor.get("clause_label"),
            anchor.get("normalized_excerpt_sha256"),
        )
        if anchor_key in anchors:
            errors.append(f"Source Anchor 重复注册：{anchor_key}")
        anchors.add(anchor_key)
        excerpt = anchor.get("normalized_excerpt")
        digest = anchor.get("normalized_excerpt_sha256")
        if isinstance(excerpt, str) and digest != normalized_excerpt_sha256(excerpt):
            errors.append(f"Source Anchor 摘要哈希不匹配：{requirement_id}")
        bindings = requirement.get("verification_bindings", [])
        required_bindings = [item for item in bindings if item.get("required") is True]
        if requirement.get("criticality") == "core" and not required_bindings:
            errors.append(f"Core Requirement 缺少 required 验证绑定：{requirement_id}")
        if requirement.get("requirement_type") == "explanation" and required_bindings:
            modes = {item.get("mode") for item in required_bindings}
            if modes == {"numerical_validator"}:
                errors.append(f"解释类 Requirement 不能只绑定数值 Validator：{requirement_id}")
    inventory = {str(item) for item in value.get("source_core_fragment_ids", [])}
    core_ids = {
        str(item.get("requirement_id"))
        for item in requirements
        if isinstance(item, dict) and item.get("criticality") == "core"
    }
    if core_ids != inventory:
        errors.append(
            "Core 题面语义覆盖不是 100%："
            f"missing={sorted(inventory - core_ids)} extra={sorted(core_ids - inventory)}"
        )
    return errors


def validate_mechanism_ledger(
    value: Mapping[str, Any], requirement_ids: set[str] | None = None
) -> list[str]:
    errors = schema_errors(value, "mechanism_scope_ledger.schema.json")
    seen: set[str] = set()
    for mechanism in value.get("mechanisms", []):
        mechanism_id = mechanism.get("mechanism_id")
        if mechanism_id in seen:
            errors.append(f"Mechanism ID 重复：{mechanism_id}")
        seen.add(str(mechanism_id))
        if requirement_ids is not None:
            unknown = set(mechanism.get("source_requirement_ids", [])) - requirement_ids
            if unknown:
                errors.append(f"Mechanism 引用未知 Requirement：{mechanism_id}: {sorted(unknown)}")
        decision = mechanism.get("decision")
        criticality = mechanism.get("criticality")
        if criticality == "core" and decision == "unsupported":
            errors.append(f"Core Mechanism 不得静默 unsupported：{mechanism_id}")
        if criticality == "core" and decision == "descoped" and not mechanism.get(
            "human_approval_ref"
        ):
            errors.append(f"Core Mechanism descoped 缺少人工批准：{mechanism_id}")
        if decision == "proxied" and not mechanism.get("approximation_error_evidence"):
            errors.append(f"Proxy Mechanism 缺少误差或风险证据：{mechanism_id}")
        if decision == "modeled" and not mechanism.get("coverage_scope"):
            errors.append(f"Modeled Mechanism 缺少 coverage_scope：{mechanism_id}")
    inventory = set(value.get("source_mechanism_ids", []))
    if seen != inventory:
        errors.append(
            "Core Mechanism 存在静默丢弃或未登记项："
            f"missing={sorted(inventory - seen)} extra={sorted(seen - inventory)}"
        )
    return errors


def validate_route_applicability(value: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(value, "route_applicability.schema.json")
    subproblems = {item.get("subproblem_id"): item for item in value.get("subproblems", [])}
    if set(subproblems) != {"Q1", "Q2", "Q3", "Q4"}:
        errors.append("Route Applicability 必须且只能登记 Q1-Q4")
    for subproblem_id in ("Q1", "Q2"):
        item = subproblems.get(subproblem_id, {})
        requirement = item.get("route_requirement", {})
        alternatives = set(item.get("required_alternatives", []))
        if requirement.get("applicability") != "not_applicable":
            errors.append(f"{subproblem_id} 解析题不得伪造结构路线竞争")
        if requirement.get("minimum_structural_routes") != 1:
            errors.append(f"{subproblem_id} 解析题只允许一个主推导")
        expected = {"independent_reference_implementation", "reference_oracle"}
        if alternatives != expected:
            errors.append(f"{subproblem_id} 缺少独立参考实现或 Reference Oracle")
    for subproblem_id in ("Q3", "Q4"):
        item = subproblems.get(subproblem_id, {})
        requirement = item.get("route_requirement", {})
        roles = set(requirement.get("required_roles", []))
        if requirement.get("applicability") != "required":
            errors.append(f"{subproblem_id} 存在实质优化空间，必须竞争结构路线")
        if requirement.get("minimum_structural_routes", 0) < 3:
            errors.append(f"{subproblem_id} 至少需要三条结构路线")
        if roles != {"baseline", "primary", "structural_alternative"}:
            errors.append(f"{subproblem_id} 路线角色不完整")
    return errors


def validate_oracle_registry(value: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(value, "reference_oracle_registry.schema.json")
    ids: set[str] = set()
    target_classes: dict[str, set[str]] = {}
    for oracle in value.get("oracles", []):
        oracle_id = oracle.get("oracle_id")
        if oracle_id in ids:
            errors.append(f"Oracle ID 重复：{oracle_id}")
        ids.add(str(oracle_id))
        oracle_class = oracle.get("oracle_class")
        oracle_type = oracle.get("type")
        if oracle_class == "truth" and oracle_type not in TRUTH_ORACLE_TYPES:
            errors.append(f"Oracle 类型与 truth 分类不一致：{oracle_id}")
        if oracle_class == "property" and oracle_type not in PROPERTY_ORACLE_TYPES:
            errors.append(f"Oracle 类型与 property 分类不一致：{oracle_id}")
        if oracle.get("critical"):
            target_classes.setdefault(str(oracle.get("target")), set()).add(str(oracle_class))
    for target, classes in target_classes.items():
        if classes != {"truth", "property"}:
            errors.append(f"关键指标必须同时具有真值型和性质型 Oracle：{target}")
    return errors


def validate_falsification_plan(
    value: Mapping[str, Any], applicability: Mapping[str, Any]
) -> list[str]:
    errors = schema_errors(value, "route_falsification_plan.schema.json")
    required = {
        item["subproblem_id"]
        for item in applicability.get("subproblems", [])
        if item.get("route_requirement", {}).get("applicability") == "required"
    }
    routes = value.get("routes", [])
    route_ids = {route.get("route_id") for route in routes}
    for subproblem_id in required:
        problem_routes = [route for route in routes if route.get("subproblem_id") == subproblem_id]
        roles = {route.get("role") for route in problem_routes}
        if roles != {"baseline", "primary", "structural_alternative"}:
            errors.append(f"{subproblem_id} 证伪计划缺少完整路线角色")
        for route in problem_routes:
            tests = route.get("falsification_tests", [])
            categories = {test.get("category") for test in tests}
            if not ({"analytic", "mechanism"} & categories):
                errors.append(f"路线缺少数学、解析或机制证伪测试：{route.get('route_id')}")
            if "numerical" not in categories:
                errors.append(f"路线缺少数值证伪测试：{route.get('route_id')}")
            if not route.get("identifiability_risks"):
                errors.append(f"路线缺少机制、数据或识别风险：{route.get('route_id')}")
            if any(test.get("triggerability") not in {"demonstrated_by_fixture", "threshold_defined"} for test in tests):
                errors.append(f"路线包含不可触发的失败条件：{route.get('route_id')}")
            fallback = route.get("fallback_route_id")
            if route.get("role") == "primary" and fallback not in route_ids:
                errors.append(f"主路线缺少有效 fallback：{route.get('route_id')}")
    return errors


def validate_headline_registry(value: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(value, "headline_claim_registry.schema.json")
    for claim in value.get("claims", []):
        claim_id = claim.get("claim_id")
        dimensions = set(claim.get("validation_dimensions", []))
        stress = set(claim.get("required_stress_tests", []))
        if not claim.get("sensitive_parameters"):
            errors.append(f"Headline Claim 未登记最弱参数：{claim_id}")
        if claim.get("claim_type") == "ranking" and "ranking_reversal" not in stress:
            errors.append(f"Ranking Claim 未登记排序反转测试：{claim_id}")
        if claim.get("claim_type") == "feasibility" and "all_hard_constraints" not in dimensions:
            errors.append(f"Feasibility Claim 必须检查全部硬约束：{claim_id}")
    return errors


def validate_contribution_ledger(value: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(value, "contribution_ledger.schema.json")
    standard_markers = {"遗传算法", "随机森林", "TOPSIS", "genetic algorithm"}
    for entry in value.get("entries", []):
        claim = str(entry.get("claim", ""))
        novelty = entry.get("novelty_status")
        if any(marker.lower() in claim.lower() for marker in standard_markers) and novelty in {
            "potentially_novel",
            "external_review_supported",
        }:
            errors.append(f"标准方法不能仅凭名称登记为创新：{entry.get('contribution_id')}")
        if novelty == "external_review_supported" and not entry.get("novelty_evidence"):
            errors.append(f"外部新颖性支持缺少证据：{entry.get('contribution_id')}")
    return errors


def derive_technical_contribution_status(
    entry: Mapping[str, Any], validator_supported: bool
) -> dict[str, Any]:
    """Validator 只派生技术状态，原样保留独立来源的新颖性状态。"""
    technical_status = entry.get("technical_status")
    if validator_supported and technical_status in {"implemented", "validator_supported"}:
        technical_status = "validator_supported"
    return {
        "contribution_id": entry.get("contribution_id"),
        "technical_status": technical_status,
        "novelty_status": entry.get("novelty_status"),
    }


def validate_common_formula_evidence(evidence: Mapping[str, Any]) -> list[str]:
    """阻止 Solver 与 Validator 的共同实现错误伪装成独立正确性。"""
    errors = []
    if evidence.get("solver_value") == evidence.get("validator_value"):
        oracle_value = evidence.get("oracle_value")
        if oracle_value is None:
            errors.append("Solver 与 Validator 一致但缺少独立 Reference Oracle")
        else:
            tolerance = float(evidence.get("tolerance", 0.0))
            if abs(float(evidence["solver_value"]) - float(oracle_value)) > tolerance:
                errors.append("Reference Oracle 发现 Solver 与 Validator 复制了同一错误")
    return errors


def validate_paper_projection(
    projection: Iterable[Mapping[str, Any]], mechanisms: Mapping[str, Any]
) -> list[str]:
    errors = []
    by_id = {
        item.get("mechanism_id"): item for item in mechanisms.get("mechanisms", [])
    }
    for claim in projection:
        mechanism = by_id.get(claim.get("mechanism_id"))
        if mechanism is None:
            errors.append(f"论文主张引用未知 Mechanism：{claim.get('claim_id')}")
            continue
        if claim.get("asserted_scope") == "full" and mechanism.get("coverage_scope") != "full":
            errors.append(f"局部或代理机制不得写成完整建模：{claim.get('claim_id')}")
    return errors


def validate_qualification_evidence(items: Iterable[Mapping[str, Any]]) -> list[str]:
    return [
        f"AI 预评审不得进入资格聚合：{item.get('evidence_id', '<unknown>')}"
        for item in items
        if item.get("review_type") == "ai_exploratory_pre_review"
        and item.get("qualification_usage") is not False
    ]


def validate_uncovered_area_claim(claim: Mapping[str, Any]) -> list[str]:
    estimated = claim.get("estimated_uncovered_area")
    uncertainty = claim.get("area_uncertainty_upper_bound")
    text = str(claim.get("text", ""))
    if isinstance(estimated, (int, float)) and isinstance(uncertainty, (int, float)):
        if estimated <= uncertainty and ("100%" in text or "无漏测" in text):
            return ["漏测面积低于数值分辨能力时不得宣称无漏测或 100% 覆盖"]
    return []


def _resolve_inside_case(case_dir: Path, relative: str) -> Path:
    resolved = (case_dir / relative).resolve()
    if not resolved.is_relative_to(case_dir.resolve()):
        raise ValueError(f"路径越出案例目录：{relative}")
    return resolved


def _material_manifest_errors(case_dir: Path, manifest: Mapping[str, Any]) -> list[str]:
    errors = []
    material_root_raw = manifest.get("material_root")
    if not isinstance(material_root_raw, str):
        return ["manifest.yaml 缺少 material_root"]
    material_root = (ROOT / material_root_raw).resolve()
    if not material_root.is_relative_to(ROOT.resolve()):
        return ["官方材料路径越出仓库"]
    for item in manifest.get("files", []):
        relative = item.get("path")
        if not isinstance(relative, str):
            errors.append("材料条目缺少 path")
            continue
        path = (material_root / relative).resolve()
        if not path.is_relative_to(material_root) or not path.is_file():
            errors.append(f"官方材料缺失：{relative}")
        elif sha256_file(path) != item.get("sha256"):
            errors.append(f"官方材料哈希不匹配：{relative}")
    hashes_path = case_dir / "hashes.sha256"
    if hashes_path.is_file():
        declared = {
            line.split(maxsplit=1)[1]: line.split(maxsplit=1)[0]
            for line in hashes_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and len(line.split(maxsplit=1)) == 2
        }
        for item in manifest.get("files", []):
            if declared.get(item.get("path")) != item.get("sha256"):
                errors.append(f"hashes.sha256 与 Manifest 不一致：{item.get('path')}")
    return errors


def validate_gate_a(case_dir: Path) -> list[str]:
    errors = []
    required = {
        "case_identity.yaml",
        "manifest.yaml",
        "hashes.sha256",
        "source_guide.md",
        "access_scope_manifest.json",
        "environment_manifest.json",
    }
    for relative in required:
        if not (case_dir / relative).is_file():
            errors.append(f"Gate A 缺少：{relative}")
    if errors:
        return errors
    identity = load_yaml(case_dir / "case_identity.yaml")
    if identity.get("evidence_mode") != "reference_exposed_reconstruction":
        errors.append("2023-B 必须登记为 reference_exposed_reconstruction")
    usage = identity.get("qualification_usage", {})
    for forbidden in ("unseen_problem_generalization", "hidden_benchmark", "competition_qualification"):
        if usage.get(forbidden) is not False:
            errors.append(f"资格用途必须关闭：{forbidden}")
    access = load_json(case_dir / "access_scope_manifest.json")
    if access.get("proxy_substitution_allowed") is not False:
        errors.append("Gate A 禁止代理材料替代")
    if access.get("network_allowed") is not False:
        errors.append("Gate A 冻结阶段必须关闭网络")
    errors.extend(_material_manifest_errors(case_dir, load_yaml(case_dir / "manifest.yaml")))
    return errors


def validate_gate_b(case_dir: Path) -> list[str]:
    errors = []
    for relative in (
        "data_contract.yaml",
        "authority_order.md",
        "model_spec.md",
        "metric_denominator_registry.yaml",
    ):
        if not (case_dir / relative).is_file():
            errors.append(f"Gate B 缺少：{relative}")
    values: dict[str, dict[str, Any]] = {}
    for role in ("requirement_map", "mechanism_scope_ledger", "route_applicability", "reference_oracle_registry"):
        relative, _ = CASE_REQUIRED_JSON[role]
        if not (case_dir / relative).is_file():
            errors.append(f"Gate B 缺少：{relative}")
        else:
            values[role] = load_json(case_dir / relative)
    if errors:
        return errors
    requirements = values["requirement_map"]
    errors.extend(validate_requirement_map(requirements))
    ids = {item.get("requirement_id") for item in requirements.get("requirements", [])}
    errors.extend(validate_mechanism_ledger(values["mechanism_scope_ledger"], ids))
    errors.extend(validate_route_applicability(values["route_applicability"]))
    errors.extend(validate_oracle_registry(values["reference_oracle_registry"]))
    data_contract = load_yaml(case_dir / "data_contract.yaml")
    if set(data_contract.get("subproblems", {})) != {"Q1", "Q2", "Q3", "Q4"}:
        errors.append("Data Contract 必须冻结 Q1-Q4")
    denominators = load_yaml(case_dir / "metric_denominator_registry.yaml")
    if not denominators.get("metrics"):
        errors.append("所有百分比指标必须登记分母")
    return errors


def canonical_bundle_digest(artifacts: list[Mapping[str, Any]]) -> str:
    payload = json.dumps(artifacts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def build_bundle(case_dir: Path, frozen_at: str | None = None) -> dict[str, Any]:
    artifacts = []
    for role, relative in BUNDLE_ROLES.items():
        path = _resolve_inside_case(case_dir, relative)
        if not path.is_file():
            raise ValueError(f"Bundle 输入缺失：{relative}")
        artifacts.append({"role": role, "path": relative, "sha256": sha256_file(path)})
    artifacts.sort(key=lambda item: item["role"])
    return {
        "schema_version": "1.0.0",
        "artifact_type": "modeling_evidence_bundle_v1",
        "problem_id": "2023-B",
        "bundle_status": "frozen_for_solver",
        "frozen_at": frozen_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "bundle_sha256": canonical_bundle_digest(artifacts),
        "artifacts": artifacts,
    }


def write_bundle(case_dir: Path, frozen_at: str | None = None) -> Path:
    bundle = build_bundle(case_dir, frozen_at=frozen_at)
    output = case_dir / "modeling" / "modeling_evidence_bundle.json"
    atomic_write_bytes(
        output,
        (json.dumps(bundle, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return output


def validate_bundle(case_dir: Path, bundle: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(bundle, "modeling_evidence_bundle.schema.json")
    artifacts = bundle.get("artifacts", [])
    if canonical_bundle_digest(artifacts) != bundle.get("bundle_sha256"):
        errors.append("Bundle 自身摘要不匹配")
    expected_roles = set(BUNDLE_ROLES)
    actual_roles = {item.get("role") for item in artifacts}
    if actual_roles != expected_roles:
        errors.append("Bundle 角色集合与冻结合同不一致")
    for item in artifacts:
        try:
            path = _resolve_inside_case(case_dir, str(item.get("path")))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            errors.append(f"Bundle 冻结后漂移：{item.get('path')}")
    return errors


def validate_run_bundle_binding(run_record: Mapping[str, Any], bundle: Mapping[str, Any]) -> list[str]:
    if run_record.get("modeling_bundle_sha256") != bundle.get("bundle_sha256"):
        return ["旧 Run 引用的 Modeling Bundle 已失效，必须重新执行 Solver 与 Validator"]
    return []


def validate_gate_c(case_dir: Path) -> list[str]:
    errors = []
    for relative in (
        "validator_contract.yaml",
        "validation_numerics.yaml",
        "dependency_boundary_policy.yaml",
        "validator_test_cases",
    ):
        if not (case_dir / relative).exists():
            errors.append(f"Gate C 缺少：{relative}")
    values = {}
    for role in ("route_applicability", "route_falsification_plan", "headline_claim_registry", "contribution_ledger"):
        relative, _ = CASE_REQUIRED_JSON[role]
        if not (case_dir / relative).is_file():
            errors.append(f"Gate C 缺少：{relative}")
        else:
            values[role] = load_json(case_dir / relative)
    bundle_path = case_dir / "modeling" / "modeling_evidence_bundle.json"
    if not bundle_path.is_file():
        errors.append("Gate C 缺少：modeling/modeling_evidence_bundle.json")
    if errors:
        return errors
    errors.extend(validate_route_applicability(values["route_applicability"]))
    errors.extend(
        validate_falsification_plan(
            values["route_falsification_plan"], values["route_applicability"]
        )
    )
    errors.extend(validate_headline_registry(values["headline_claim_registry"]))
    errors.extend(validate_contribution_ledger(values["contribution_ledger"]))
    policy = load_yaml(case_dir / "dependency_boundary_policy.yaml")
    if policy.get("solver_may_import_validator") is not False:
        errors.append("Solver 不得导入 Validator")
    if policy.get("validator_may_import_solver") is not False:
        errors.append("Validator 不得导入 Solver")
    numerics = load_yaml(case_dir / "validation_numerics.yaml")
    if not numerics.get("area_uncertainty_upper_bound"):
        errors.append("Validation Numerics 必须冻结面积误差上界方法")
    errors.extend(validate_bundle(case_dir, load_json(bundle_path)))
    return errors


def validate_case(case_dir: Path) -> dict[str, Any]:
    gate_errors = {
        "A": validate_gate_a(case_dir),
        "B": validate_gate_b(case_dir),
        "C": validate_gate_c(case_dir),
    }
    gate_status = {gate: not errors for gate, errors in gate_errors.items()}
    return {
        "schema_version": "1.0.0",
        "artifact_type": "modeling_gate_report_v1",
        "problem_id": "2023-B",
        "gates": gate_status,
        "status": "gate_c_modeling_design_frozen" if all(gate_status.values()) else "blocked",
        "formal_result_eligible": False,
        "errors": gate_errors,
    }
