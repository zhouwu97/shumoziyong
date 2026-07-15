"""数学建模工作流 v2.1 合同与准入判定。

该模块只增加 v2.1 能力，不改变历史 v2/Runtime 1.1/1.2 的解释方式。
所有状态均由输入工件重新计算，避免把模型或论文自报的布尔值当作证据。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - 仓库测试环境会安装 jsonschema
    Draft202012Validator = None  # type: ignore[assignment]
    FormatChecker = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
V21_RUNTIME_MANIFEST_VERSION = "1.3.0"
V21_GATE_CONTRACT_VERSION = "2.1.0"
V21_MODEL_ROUTE_VERSION = "2.1.0"
FATAL_CODES = {"F1", "F2", "F3", "F4", "F5"}
SEVERITIES = {"fatal", "major", "minor", "editorial"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _schema_errors(value: Any, schema_name: str) -> list[str]:
    if Draft202012Validator is None:
        return ["jsonschema 未安装"]
    path = ROOT / "schemas" / schema_name
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Schema {schema_name} 无法读取：{exc}"]
    errors = Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)
    return ["/".join(str(part) for part in error.absolute_path) + ": " + error.message for error in errors]


def validate_model_route_v21(value: Mapping[str, Any]) -> list[str]:
    return _schema_errors(value, "model_route_v2_1.schema.json")


def validate_model_validity_contract(value: Mapping[str, Any]) -> list[str]:
    errors = _schema_errors(value, "model_validity_contract.schema.json")
    if errors:
        return errors
    if value.get("contract_status") != "planned":
        errors.append("Gate 1 模型有效性合同只能是 planned，不能宣称已验证")
    for ref in value.get("assertion_refs", []):
        if ref.get("layer") == "sealed" and (ref.get("sealed") is not True or ref.get("blind_evidence") is not True):
            errors.append("sealed 断言必须同时 sealed=true 且 blind_evidence=true")
        if ref.get("layer") == "public" and ref.get("sealed") is True:
            errors.append("public 断言不能标记为 sealed=true")
    return errors


def validate_model_validity_report(
    value: Mapping[str, Any],
    contract: Mapping[str, Any] | None = None,
    *,
    contract_path: Path | None = None,
) -> list[str]:
    errors = _schema_errors(value, "model_validity_report.schema.json")
    if errors:
        return errors
    if contract is not None:
        if value.get("run_id") != contract.get("run_id"):
            errors.append("model_validity_report.run_id 与合同不一致")
        ref = value.get("contract_ref", {})
        if contract_path is not None:
            if ref.get("path") != contract_path.name:
                errors.append("model_validity_report.contract_ref.path 与实际合同不一致")
            if contract_path.is_file() and ref.get("sha256") != sha256_file(contract_path):
                errors.append("model_validity_report.contract_ref.sha256 与实际合同不一致")
        expected_groups = {
            "small_examples": {str(item.get("case_id")) for item in contract.get("small_examples", [])},
            "limit_cases": {str(item.get("case_id")) for item in contract.get("limit_cases", [])},
        }
        for field, expected_ids in expected_groups.items():
            actual_ids = {
                str(item.get("case_id"))
                for item in value.get(field, {}).get("results", [])
            }
            if actual_ids != expected_ids:
                errors.append(f"model_validity_report.{field} 未完整覆盖 Gate 1 合同用例")
    if value.get("execution_status") == "passed" and value.get("fatal_codes"):
        errors.append("存在 F1-F5 时 execution_status 不能为 passed")
    return errors


def validate_validator_independence(value: Mapping[str, Any]) -> list[str]:
    errors = _schema_errors(value, "validator_independence_manifest.schema.json")
    if errors:
        return errors
    shared = value.get("shared_source_modules", [])
    dependent = bool(value.get("reads_primary_intermediates") or value.get("reads_primary_metrics"))
    if dependent:
        if value.get("f5_status") != "fail":
            errors.append("Validator 读取主中间量或指标时必须触发 F5")
    elif value.get("f5_status") == "fail":
        errors.append("独立 Validator 不应无依据标记 F5")
    if value.get("independent_formula_implementation") is not True:
        errors.append("Validator 必须声明 independent_formula_implementation=true")
    if value.get("reconstructs_coefficients_independently") is not True:
        errors.append("Validator 必须独立重建关键系数")
    if any("model_validation" in str(item) or "solver" in str(item) for item in shared):
        errors.append("Validator 不得共享主求解器的计算模块")
    return errors


def validate_formal_result_identity(
    run_manifest: Mapping[str, Any],
    formal_result: Mapping[str, Any],
    *,
    execution_started_at: str | None = None,
) -> list[str]:
    """验证 v2.1 Formal Result 是否属于当前 Run，而非仅文件名更新。"""
    errors: list[str] = []
    if run_manifest.get("runtime_manifest_version") not in (None, V21_RUNTIME_MANIFEST_VERSION) and run_manifest.get("runtime_pack_manifest_version") not in (None, V21_RUNTIME_MANIFEST_VERSION):
        return errors
    expected = {
        "run_id": run_manifest.get("run_id"),
        "problem_manifest_sha256": run_manifest.get("material_manifest_sha256"),
        "execution_spec_sha256": run_manifest.get("execution_spec_sha256"),
        "source_manifest_sha256": run_manifest.get("source_manifest_sha256"),
    }
    aliases = {
        "problem_manifest_sha256": ("problem_manifest_sha256", "material_manifest_sha256"),
        "execution_spec_sha256": ("execution_spec_sha256",),
        "source_manifest_sha256": ("source_manifest_sha256", "code_tree_sha256"),
    }
    if formal_result.get("run_id") != expected["run_id"]:
        errors.append("Formal Result.run_id 与当前运行不一致")
    for field, names in aliases.items():
        expected_value = expected[field]
        if expected_value is None:
            continue
        if not any(formal_result.get(name) == expected_value for name in names):
            errors.append(f"Formal Result.{field} 未绑定当前运行")
    if formal_result.get("activation_status") not in (None, "active", "run_execution_verified"):
        errors.append("Formal Result.activation_status 不是 active")
    if formal_result.get("activation_status") == "active" and formal_result.get("candidate_output_used") is True:
        errors.append("active Formal Result 不得使用 candidate output")
    if execution_started_at and formal_result.get("created_at"):
        try:
            started = datetime.fromisoformat(execution_started_at.replace("Z", "+00:00"))
            created = datetime.fromisoformat(str(formal_result["created_at"]).replace("Z", "+00:00"))
            if created < started:
                errors.append("Formal Result.created_at 早于当前执行开始事件")
        except ValueError:
            errors.append("Formal Result.created_at 或执行开始时间不是合法 ISO 8601")
    return errors


def validate_formal_result_run_binding(
    value: Mapping[str, Any],
    *,
    run_dir: Path,
    run_manifest: Mapping[str, Any],
    formal_result_summary: Mapping[str, Any],
) -> list[str]:
    """验证 v2.1 运行绑定工件中的文件哈希和时间顺序。"""
    errors = _schema_errors(value, "formal_result_run_binding.schema.json")
    if errors:
        return errors
    if value.get("run_id") != run_manifest.get("run_id"):
        errors.append("Formal Result 绑定的 run_id 与当前运行不一致")
    expected_hashes = {
        "problem_manifest_sha256": sha256_file(run_dir / "problem_manifest.json"),
        "execution_spec_sha256": sha256_file(run_dir / "execution_spec.json"),
    }
    artifacts = formal_result_summary.get("artifacts", {})
    source_item = artifacts.get("code_manifest.json") if isinstance(artifacts, Mapping) else None
    if isinstance(source_item, Mapping):
        source_path = run_dir / str(source_item.get("path"))
        if source_path.is_file():
            expected_hashes["source_manifest_sha256"] = sha256_file(source_path)
    if "source_manifest_sha256" not in expected_hashes:
        errors.append("Formal Result 缺少可验证的 code_manifest.json")
    for field, expected in expected_hashes.items():
        if value.get(field) != expected:
            errors.append(f"Formal Result 绑定字段 {field} 与当前运行文件不一致")
    ref = value.get("formal_result_ref", {})
    expected_path = str(formal_result_summary.get("envelope_path"))
    if ref.get("path") != expected_path:
        errors.append("Formal Result 绑定未引用当前 Envelope")
    envelope_path = run_dir / expected_path
    if envelope_path.is_file() and ref.get("sha256") != sha256_file(envelope_path):
        errors.append("Formal Result 绑定的 Envelope 哈希不一致")
    try:
        started = datetime.fromisoformat(str(value["execution_started_at"]).replace("Z", "+00:00"))
        created = datetime.fromisoformat(str(value["created_at"]).replace("Z", "+00:00"))
        if created < started:
            errors.append("Formal Result.created_at 早于当前执行开始事件")
    except (KeyError, ValueError):
        errors.append("Formal Result 执行时间不是合法 ISO 8601")
    if formal_result_summary.get("formal_result_eligible") is not True:
        errors.append("Formal Result 尚未达到 active/eligible 状态")
    return errors


def classify_benchmark(problem_id: str, *, materials_previously_read: bool = False) -> dict[str, Any]:
    """返回开发基准身份；不把已读旧题升级成盲测证据。"""
    if problem_id == "2024-C":
        return {
            "classification": "development_integration_benchmark",
            "blind_generalization": False,
            "profile_promotion_eligible": False,
        }
    if materials_previously_read:
        return {
            "classification": "development_benchmark",
            "blind_generalization": False,
            "profile_promotion_eligible": False,
        }
    return {
        "classification": "unseen_case_candidate",
        "blind_generalization": True,
        "profile_promotion_eligible": False,
    }


def compute_score_v2(
    diagnosis_structure_score: float,
    model_quality_score: float,
    result_quality_score: float,
    paper_presentation_score: float,
    *,
    fatal_codes: list[str] | None = None,
    unresolved_major: bool = False,
) -> dict[str, Any]:
    technical_merit = min(float(model_quality_score), float(result_quality_score))
    competition = 0.8 * technical_merit + 0.2 * float(paper_presentation_score)
    ineligible = bool(set(fatal_codes or []) & FATAL_CODES) or unresolved_major
    return {
        "diagnosis_structure_score": float(diagnosis_structure_score),
        "model_quality_score": float(model_quality_score),
        "result_quality_score": float(result_quality_score),
        "paper_presentation_score": float(paper_presentation_score),
        "technical_merit": technical_merit,
        "competition_submission_score": competition,
        "competition_submission_status": "not_eligible" if ineligible else "eligible",
    }


def evaluate_paper_admission(
    *,
    implementation_status: str,
    model_validity_status: str,
    competition_score: float,
    competition_status: str,
    findings: list[Mapping[str, Any]] | None = None,
    reviewer_ref: Mapping[str, Any] | None = None,
    baseline_improvement_supported: bool | None = None,
    operational_value_supported: bool | None = None,
) -> dict[str, Any]:
    findings = list(findings or [])
    unresolved_fatal_major = any(
        item.get("severity") in {"fatal", "major"} and item.get("resolved") is not True
        for item in findings
    )
    f_codes = {str(item.get("code")) for item in findings if str(item.get("code")) in FATAL_CODES}
    admitted = (
        implementation_status == "pass"
        and model_validity_status == "pass"
        and competition_status != "fail"
        and float(competition_score) >= 70
        and not unresolved_fatal_major
        and not f_codes
    )
    competition_value = {
        "score": float(competition_score),
        "status": competition_status,
        "reviewer_required": True,
        "baseline_improvement_supported": (
            competition_status != "fail"
            if baseline_improvement_supported is None
            else bool(baseline_improvement_supported)
        ),
        "operational_value_supported": (
            competition_status != "fail"
            if operational_value_supported is None
            else bool(operational_value_supported)
        ),
    }
    if reviewer_ref is not None:
        competition_value["reviewer_ref"] = dict(reviewer_ref)
    return {
        "implementation_correctness": {"status": implementation_status},
        "model_validity": {"status": model_validity_status, "fatal_codes": sorted(f_codes)},
        "competition_value": competition_value,
        "blocking_findings": findings,
        "admission_status": "admitted" if admitted else "blocked",
        "technical_report_allowed": True,
        "submission_paper_allowed": admitted,
    }


def validate_reviewer_report(value: Mapping[str, Any]) -> list[str]:
    errors = _schema_errors(value, "reviewer_report.schema.json")
    if errors:
        return errors
    if value.get("independence_mode") == "independent" and value.get("write_access") is not False:
        errors.append("独立审稿必须是只读输入")
    allowed = {
        "model": {"problem", "model_contract", "formal_result", "validity_report", "manuscript", "review_report"},
        "paper": {"problem", "formal_result", "claim_map", "manuscript", "figure", "review_report"},
    }
    role = str(value.get("review_role"))
    for item in value.get("input_artifacts", []):
        category = item.get("category")
        if category not in allowed.get(role, set()):
            errors.append(f"Reviewer {role} 输入类别越权：{category}")
    if value.get("review_round") == 2:
        if not value.get("prior_round_report_refs"):
            errors.append("第二轮 Reviewer 必须引用本角色第一轮报告")
        if not value.get("remediation_evidence_refs"):
            errors.append("第二轮 Reviewer 必须引用修复后重跑证据")
        if any(
            item.get("severity") in {"fatal", "major"} and item.get("resolved") is not True
            for item in value.get("findings", [])
        ):
            errors.append("第二轮仍存在未解决 fatal/major 问题")
        if value.get("decision") != "pass":
            errors.append("第二轮 Reviewer 必须给出 pass 才能进入 Gate 5")
    return errors


def validate_reviewer_pair(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    run_dir: Path | None = None,
) -> list[str]:
    errors = validate_reviewer_report(first) + validate_reviewer_report(second)
    if first.get("run_id") != second.get("run_id"):
        errors.append("两份审稿报告不属于同一 Run")
    if first.get("review_role") == second.get("review_role"):
        errors.append("Reviewer A/B 必须分别承担 model 与 paper 角色")
    if first.get("review_round") != second.get("review_round"):
        errors.append("Reviewer A/B 必须属于同一轮次")
    same_engine = first.get("reviewer_model") == second.get("reviewer_model")
    same_prompt = first.get("prompt_profile") == second.get("prompt_profile")
    if same_engine or same_prompt:
        if first.get("independence_mode") != "role_separated_review" or second.get("independence_mode") != "role_separated_review":
            errors.append("同模型或同提示上下文只能标记为 role_separated_review")
    if first.get("reviewed_bundle_sha256") == second.get("reviewed_bundle_sha256") and first.get("independence_mode") == "independent" and second.get("independence_mode") == "independent":
        errors.append("独立 Reviewer 不得共享同一输入包")
    first_paths = {item.get("path") for item in first.get("input_artifacts", [])}
    second_paths = {item.get("path") for item in second.get("input_artifacts", [])}
    if first_paths & second_paths and first.get("independence_mode") == "independent" and second.get("independence_mode") == "independent":
        errors.append("独立 Reviewer 输入包存在交叉文件")
    if first.get("review_role") == "model":
        model, paper = first, second
    else:
        model, paper = second, first
    for item in model.get("input_artifacts", []):
        if "chat" in str(item.get("path", "")).lower() or "reviewer_b" in str(item.get("path", "")).lower():
            errors.append("Reviewer A 不得读取聊天记录或 Reviewer B 报告")
    for item in paper.get("input_artifacts", []):
        if "chat" in str(item.get("path", "")).lower() or "reviewer_a" in str(item.get("path", "")).lower():
            errors.append("Reviewer B 不得读取聊天记录或 Reviewer A 报告")
    if run_dir is not None:
        for report in (first, second):
            for item in report.get("input_artifacts", []):
                errors.extend(_validate_file_ref(run_dir, item, "Reviewer 输入"))
    return errors


def _validate_file_ref(run_dir: Path, ref: Mapping[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    root = run_dir.resolve()
    path = (run_dir / str(ref.get("path", ""))).resolve()
    if not path.is_relative_to(root):
        return [f"{label}路径位于运行目录外：{ref.get('path')}"]
    if not path.is_file():
        return [f"{label}文件不存在：{ref.get('path')}"]
    if ref.get("sha256") != sha256_file(path):
        errors.append(f"{label}文件哈希不一致：{ref.get('path')}")
    return errors


def validate_competition_value_assessment(value: Mapping[str, Any]) -> list[str]:
    errors = _schema_errors(value, "competition_value_assessment.schema.json")
    if errors:
        return errors
    if value.get("status") == "pass" and float(value.get("score", 0)) < 70:
        errors.append("竞赛价值低于 70 分时不能标记 pass")
    return errors


def validate_paper_production_manifest(
    value: Mapping[str, Any],
    *,
    run_dir: Path,
    admission: Mapping[str, Any],
) -> list[str]:
    """验证论文和图表只引用当前运行内的已哈希文件。"""
    errors = _schema_errors(value, "paper_production_manifest.schema.json")
    if errors:
        return errors
    if value.get("run_id") != admission.get("run_id"):
        errors.append("论文生产清单与 Paper Admission 不属于同一 Run")
    admitted = admission.get("submission_paper_allowed") is True
    paper_type = value.get("paper_type")
    if admitted and paper_type != "submission_paper":
        errors.append("准入通过后正式候选稿必须标记为 submission_paper")
    if not admitted and paper_type != "technical_report":
        errors.append("Paper Admission 未通过时只能生成 technical_report")
    ref_fields = [
        ("paper_admission_ref", value.get("paper_admission_ref")),
        ("terminology_ledger_ref", value.get("terminology_ledger_ref")),
        ("claim_map_ref", value.get("claim_map_ref")),
        ("manuscript_ref", value.get("manuscript_ref")),
        ("pdf_ref", value.get("pdf_ref")),
    ]
    for label, ref in ref_fields:
        if isinstance(ref, Mapping):
            errors.extend(_validate_file_ref(run_dir, ref, label))
    for ref in value.get("matlab_evidence_refs", []):
        errors.extend(_validate_file_ref(run_dir, ref, "MATLAB 证据"))
    matlab_paths = {str(item.get("path")) for item in value.get("matlab_evidence_refs", [])}
    if not {"matlab_level_a_report.json", "matlab_level_b_report.json"}.issubset(matlab_paths):
        errors.append("论文生产清单必须同时绑定 MATLAB Level A+B 报告")
    for figure in value.get("figures", []):
        for key in ("source_data_ref", "script_ref", "qa_ref"):
            errors.extend(_validate_file_ref(run_dir, figure.get(key, {}), f"图表 {key}"))
        attestation_ref = figure.get("source_data_attestation_ref")
        if attestation_ref is not None:
            errors.extend(_validate_file_ref(run_dir, attestation_ref, "图表 source_data_attestation_ref"))
            attestation_path = (run_dir / str(attestation_ref.get("path", ""))).resolve()
            if attestation_path.is_relative_to(run_dir.resolve()) and attestation_path.is_file():
                try:
                    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    errors.append("图表 source_data_attestation_ref 不是合法 JSON")
                else:
                    if attestation.get("status") != "verified":
                        errors.append("图表 source_data_attestation_ref.status 必须为 verified")
                    if attestation.get("source_data_ref") != figure.get("source_data_ref"):
                        errors.append("图表 source_data_attestation_ref 与 source_data_ref 不一致")
        source_ref = figure.get("source_data_ref", {})
        source_path = str(source_ref.get("path", "")).replace("\\", "/")
        if not source_path.startswith("formal_results/") and figure.get("source_data_attestation_ref") is None:
            errors.append("非 active Formal Result 图表数据必须绑定 source_data_attestation_ref")
        for fmt, ref in figure.get("exports", {}).items():
            errors.extend(_validate_file_ref(run_dir, ref, f"图表 {fmt} 导出"))
    return errors


def detect_f5(value: Mapping[str, Any]) -> bool:
    """F5 的可执行判定：主 Validator 复用主求解器中间计算。"""
    return bool(
        value.get("reads_primary_intermediates")
        or value.get("reads_primary_metrics")
        or value.get("shared_source_modules")
    )


def validate_matlab_recomputation(value: Mapping[str, Any]) -> list[str]:
    """验证 MATLAB Level A/B 证据的最小结构，不把 A/B 冒充 Level C。"""
    errors: list[str] = []
    level = value.get("level")
    if level not in {"A", "B", "C"}:
        errors.append("MATLAB 复算 level 必须为 A/B/C")
    if value.get("backend") != "matlab":
        errors.append("第一轮复算 backend 必须为 matlab")
    if value.get("independent_from_python") is not True:
        errors.append("MATLAB 复算必须声明 independent_from_python=true")
    if level == "A" and value.get("full_model_solved") is True:
        errors.append("Level A 不能声明完整模型独立求解")
    if level == "B" and not value.get("small_example_ids"):
        errors.append("Level B 必须列出独立小样例")
    return errors
