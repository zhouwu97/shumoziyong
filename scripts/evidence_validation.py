"""跨入口共享的运行、控制和 Profile 证据深验证。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from control_evidence import derive_control_result
from evaluation_case_registry import (
    find_authorized_case,
    load_registry,
    substantive_assertion_count,
)

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少 jsonschema，请安装 requirements.lock 中的依赖") from exc


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"


@dataclass
class EvidenceOutcome:
    valid: bool
    errors: list[str] = field(default_factory=list)
    identity: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] | None = None


@dataclass
class ControlOutcome(EvidenceOutcome):
    result: str = "invalid"
    review: dict[str, Any] | None = None


def _schema_errors(data: Any, schema_name: str) -> list[str]:
    schema_path = SCHEMA_DIR / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    registry = Registry()
    for candidate in SCHEMA_DIR.glob("*.json"):
        candidate_schema = json.loads(candidate.read_text(encoding="utf-8"))
        schema_id = candidate_schema.get("$id")
        if isinstance(schema_id, str):
            registry = registry.with_resource(schema_id, Resource.from_contents(candidate_schema))
    issues = sorted(
        Draft202012Validator(
            schema, registry=registry, format_checker=FormatChecker()
        ).iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )
    return [
        f"{'.'.join(str(part) for part in issue.absolute_path) or '<root>'}: {issue.message}"
        for issue in issues
    ]


def _load_object(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} 无法读取：{exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} 必须是 JSON 对象")
        return None
    return value


def _resolve(root: Path, raw: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(raw, str) or not raw:
        errors.append(f"{label} 必须是非空相对路径")
        return None
    path = (root / raw).resolve()
    if not path.is_relative_to(root.resolve()):
        errors.append(f"{label} 位于证据根目录外：{raw}")
        return None
    return path


def _normalize_prompt(text: str) -> str:
    return "\n".join(
        line.rstrip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
    )


def _parse_time(value: Any, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{label} 不能为空")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} 不是合法 ISO 8601 时间")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label} 必须包含时区")
        return None
    return parsed


def _diagnosis_schema_name(response: Mapping[str, Any]) -> str:
    """按响应声明的主版本选择诊断契约；缺失或非法版本按当前契约闭锁校验。"""
    version = response.get("schema_version")
    if isinstance(version, str):
        major = version.split(".", maxsplit=1)[0]
        if major.isdigit() and int(major) < 2:
            return "diagnosis_output.schema.json"
    return "diagnosis.schema.json"


def failure_fix_evidence_digest(
    *,
    failure_id: str,
    target_patch: str,
    retest_run_id: str,
    failure_record_sha256: str,
    fix_record_sha256: str,
    retest_evidence_manifest_sha256: str,
) -> str:
    """计算失败、修复与重测共同身份的规范化摘要。"""
    payload = {
        "failure_id": failure_id,
        "target_patch": target_patch,
        "retest_run_id": retest_run_id,
        "failure_record_sha256": failure_record_sha256,
        "fix_record_sha256": fix_record_sha256,
        "retest_evidence_manifest_sha256": retest_evidence_manifest_sha256,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_full_run(
    run_dir: Path,
    policy: Mapping[str, Any],
    *,
    expected_profile: str | None = None,
    expected_runtime_version: str | None = None,
    expected_target_patch: str | None = None,
    expected_role: str | None = None,
) -> EvidenceOutcome:
    """验证完整 v2 运行、Seal、Gate 0-5 和 Evidence Manifest 全部内容。"""
    run_dir = run_dir.resolve()
    errors: list[str] = []
    manifest = _load_object(run_dir / "run_manifest.json", "run_manifest.json", errors)
    runtime = _load_object(
        run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json", errors
    )
    metadata = _load_object(run_dir / "ai_run_metadata.json", "ai_run_metadata.json", errors)
    request = _load_object(run_dir / "request.json", "request.json", errors)
    automatic = _load_object(
        run_dir / "automatic_evaluation.json", "automatic_evaluation.json", errors
    )
    problem = _load_object(run_dir / "problem_manifest.json", "problem_manifest.json", errors)
    if any(item is None for item in (manifest, runtime, metadata, request, automatic, problem)):
        return EvidenceOutcome(False, errors)
    assert manifest is not None and runtime is not None and metadata is not None
    assert request is not None and automatic is not None and problem is not None

    for label, value, schema in (
        ("runtime_pack.manifest.json", runtime, "runtime_pack_manifest.schema.json"),
        ("ai_run_metadata.json", metadata, "ai_run_metadata.schema.json"),
    ):
        errors.extend(f"{label} Schema: {issue}" for issue in _schema_errors(value, schema))

    if manifest.get("manifest_version") != "2.0.0":
        errors.append("正式证据必须使用不可变 run_manifest v2")
    if manifest.get("promotion_evidence") is not True:
        errors.append("run_manifest.promotion_evidence 必须为 true")
    bindings = {
        "profile": expected_profile,
        "runtime_version": expected_runtime_version,
        "target_patch": expected_target_patch,
        "experiment_role": expected_role,
    }
    for field_name, expected in bindings.items():
        if expected is not None and manifest.get(field_name) != expected:
            errors.append(f"run_manifest.{field_name} 与预期不一致")
    for field_name in ("profile", "runtime_version"):
        if runtime.get(field_name) != manifest.get(field_name):
            errors.append(f"runtime manifest.{field_name} 与 run_manifest 不一致")

    runtime_pack_path = run_dir / "runtime_pack.md"
    if not runtime_pack_path.is_file():
        errors.append("缺少 runtime_pack.md")
    else:
        actual_pack_sha = hashlib.sha256(runtime_pack_path.read_bytes()).hexdigest()
        if runtime.get("runtime_pack_sha256") != actual_pack_sha:
            errors.append("runtime_pack.manifest.json 与 runtime_pack.md SHA-256 不一致")
        if metadata.get("runtime_pack_sha256") != actual_pack_sha:
            errors.append("ai_run_metadata.runtime_pack_sha256 与运行包不一致")

    if metadata.get("status") != "completed":
        errors.append("ai_run_metadata.status 必须为 completed")
    if request.get("source") != "real_ai_run" or not request.get("prompt"):
        errors.append("request 必须来自非空 real_ai_run")
    if request.get("model") != metadata.get("model"):
        errors.append("request.model 与 ai_run_metadata.model 不一致")
    prompt_sha = hashlib.sha256(
        _normalize_prompt(str(request.get("prompt", ""))).encode("utf-8")
    ).hexdigest()
    if metadata.get("prompt_sha256") != prompt_sha:
        errors.append("ai_run_metadata.prompt_sha256 不匹配")
    started = _parse_time(metadata.get("started_at"), "started_at", errors)
    completed = _parse_time(metadata.get("completed_at"), "completed_at", errors)
    if started is not None and completed is not None and completed < started:
        errors.append("ai_run_metadata.completed_at 早于 started_at")
    if problem.get("content_digest") != metadata.get("problem_material_digest"):
        errors.append("ai_run_metadata.problem_material_digest 不匹配")
    if automatic.get("result") != "pass" or automatic.get("errors"):
        errors.append("automatic_evaluation 未通过")

    response_path = run_dir / "response.json"
    try:
        from evaluate_prompt_response import (
            EVALUATOR_VERSION,
            evaluate_case,
            evaluate_manifest_alignment,
            load_case,
        )

        response_text = response_path.read_text(encoding="utf-8")
        response = json.loads(response_text)
        if not isinstance(response, dict):
            raise ValueError("response.json 必须是 JSON 对象")
        diagnosis_schema = _diagnosis_schema_name(response)
        errors.extend(
            f"response.json {diagnosis_schema}: {issue}"
            for issue in _schema_errors(response, diagnosis_schema)
        )
        runtime_text = (run_dir / "runtime_pack.manifest.json").read_text(
            encoding="utf-8"
        )
        actual_response_sha = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
        actual_runtime_sha = hashlib.sha256(runtime_text.encode("utf-8")).hexdigest()
        if automatic.get("response_sha256") != actual_response_sha:
            errors.append("automatic_evaluation.response_sha256 与现场响应不一致")
        if automatic.get("manifest_sha256") != actual_runtime_sha:
            errors.append("automatic_evaluation.manifest_sha256 与现场运行包不一致")
        case_path = _resolve(
            ROOT, automatic.get("case_file"), "automatic_evaluation.case_file", errors
        )
        if case_path is not None:
            actual_case_sha = hashlib.sha256(case_path.read_bytes()).hexdigest()
            if automatic.get("case_sha256") != actual_case_sha:
                errors.append("automatic_evaluation.case_sha256 与现场用例不一致")
            case = load_case(case_path, automatic.get("case_id"))
            try:
                registry = load_registry()
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"evaluation_case_registry 无法读取：{exc}")
                registry = None
            if registry is not None:
                errors.extend(
                    f"evaluation_case_registry Schema: {issue}"
                    for issue in _schema_errors(
                        registry, "evaluation_case_registry.schema.json"
                    )
                )
                authorized = find_authorized_case(
                    registry,
                    case_id=automatic.get("case_id"),
                    case_file=automatic.get("case_file"),
                    case_sha256=actual_case_sha,
                )
                if authorized is None:
                    errors.append(
                        "automatic_evaluation 用例未被授权："
                        "case_id、case_file 和 case_sha256 必须同时命中注册表"
                    )
                else:
                    assertion_count = substantive_assertion_count(case)
                    minimum_assertions = authorized.get("minimum_assertion_count")
                    if not isinstance(minimum_assertions, int):
                        errors.append("授权用例 minimum_assertion_count 必须是整数")
                    elif assertion_count < minimum_assertions:
                        errors.append(
                            "授权用例的实质断言不足："
                            f"当前 {assertion_count}，授权下限 {minimum_assertions}"
                        )
                    expected_metadata = {
                        "case_registry_version": registry.get("registry_version"),
                        "evaluator_version": registry.get("evaluator_version"),
                        "control_type": authorized.get("control_type"),
                        "target_patch": authorized.get("target_patch"),
                        "assertion_count": assertion_count,
                    }
                    if registry.get("evaluator_version") != EVALUATOR_VERSION:
                        errors.append("用例注册表 evaluator_version 与当前评估器不一致")
                    for field_name, expected in expected_metadata.items():
                        if automatic.get(field_name) != expected:
                            errors.append(
                                f"automatic_evaluation.{field_name} 与授权用例不一致"
                            )
            recomputed_errors = evaluate_case(case, response)
            recomputed_errors.extend(evaluate_manifest_alignment(response, runtime))
            recomputed_result = "fail" if recomputed_errors else "pass"
            if automatic.get("errors") != recomputed_errors:
                errors.append(
                    "automatic_evaluation 现场重算错误列表不一致："
                    f"记录={automatic.get('errors')}，现场={recomputed_errors}"
                )
            if automatic.get("result") != recomputed_result:
                errors.append(
                    "automatic_evaluation 现场重算结论不一致："
                    f"记录={automatic.get('result')}，现场={recomputed_result}"
                )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError) as exc:
        errors.append(f"automatic_evaluation 无法现场重算：{exc}")

    try:
        from run_workflow import replay_transition_log, verify_gate_artifacts, verify_run_seal

        verify_run_seal(run_dir)
        for gate in range(6):
            verify_gate_artifacts(run_dir, gate)
        state = replay_transition_log(run_dir)
        if (
            not state.get("completed")
            or state.get("max_gate") != 5
            or state.get("transition_version") != "2.0.0"
        ):
            errors.append("Gate 状态机不是完整 v2 Gate 0-5 运行")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"运行 Seal 或 Gate 状态无效：{exc}")

    evidence = _load_object(
        run_dir / "run_evidence_manifest.json", "run_evidence_manifest.json", errors
    )
    if evidence is not None:
        errors.extend(
            f"run_evidence_manifest Schema: {issue}"
            for issue in _schema_errors(evidence, "run_evidence_manifest.schema.json")
        )
        checks = policy.get("run_evidence_requirements", {}).get(
            "ai_run_metadata_checks", {}
        )
        required = checks.get("required_artifacts", {})
        try:
            from finalize_run_evidence import validate_evidence_manifest

            errors.extend(validate_evidence_manifest(run_dir, evidence, required))
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"Evidence Manifest Policy 无效：{exc}")
        if evidence.get("run_id") != manifest.get("run_id"):
            errors.append("run_evidence_manifest.run_id 与 run_manifest 不一致")

    identity = {
        "run_id": manifest.get("run_id"),
        "problem_id": manifest.get("problem_id"),
        "profile": manifest.get("profile"),
        "runtime_version": manifest.get("runtime_version"),
        "runtime_pack_sha256": runtime.get("runtime_pack_sha256"),
        "experiment_group_id": manifest.get("experiment_group_id"),
        "target_patch": manifest.get("target_patch"),
        "experiment_role": manifest.get("experiment_role"),
        "prompt_sha256": prompt_sha,
        "response_sha256": (
            hashlib.sha256(response_path.read_bytes()).hexdigest()
            if response_path.is_file()
            else None
        ),
    }
    return EvidenceOutcome(not errors, errors, identity, manifest)


def validate_control_evidence(
    patch_id: str,
    control_type: str,
    control: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_profile: str | None = None,
) -> ControlOutcome:
    """深验证一组 v2 对照证据并派生唯一控制结论。"""
    if "result" in control:
        return ControlOutcome(False, ["v2 控制不得包含手填 result"], result="invalid")
    evidence = control.get("evidence")
    if evidence is None:
        return ControlOutcome(True, result="pending")
    if not isinstance(evidence, Mapping):
        return ControlOutcome(False, ["control.evidence 必须为对象或 null"], result="invalid")
    errors: list[str] = []
    baseline_dir = _resolve(root, evidence.get("baseline_run"), "baseline_run", errors)
    treatment_dir = _resolve(root, evidence.get("treatment_run"), "treatment_run", errors)
    review_path = _resolve(root, evidence.get("comparison_review"), "comparison_review", errors)
    if any(path is None for path in (baseline_dir, treatment_dir, review_path)):
        return ControlOutcome(False, errors, result="invalid")
    assert baseline_dir is not None and treatment_dir is not None and review_path is not None

    review = _load_object(review_path, "comparison_review", errors)
    if review is not None:
        errors.extend(
            f"comparison review Schema: {issue}"
            for issue in _schema_errors(review, "comparison_review_v2.schema.json")
        )
    baseline_evidence = baseline_dir / "run_evidence_manifest.json"
    treatment_evidence = treatment_dir / "run_evidence_manifest.json"
    for label, path, expected_sha in (
        ("baseline", baseline_evidence, evidence.get("baseline_evidence_manifest_sha256")),
        ("treatment", treatment_evidence, evidence.get("treatment_evidence_manifest_sha256")),
    ):
        if not path.is_file():
            errors.append(f"缺少 {label} Evidence Manifest")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
            errors.append(f"{label} Evidence Manifest SHA-256 不匹配")

    baseline = validate_full_run(
        baseline_dir,
        policy,
        expected_profile=expected_profile,
        expected_target_patch=patch_id,
        expected_role="baseline",
    )
    treatment = validate_full_run(
        treatment_dir,
        policy,
        expected_profile=expected_profile,
        expected_target_patch=patch_id,
        expected_role="patch_only",
    )
    errors.extend(f"baseline: {error}" for error in baseline.errors)
    errors.extend(f"treatment: {error}" for error in treatment.errors)

    if review is not None:
        expected_fields = {
            "control_type": control_type,
            "target_patch": patch_id,
            "baseline_run": evidence.get("baseline_run"),
            "treatment_run": evidence.get("treatment_run"),
            "baseline_evidence_manifest_sha256": evidence.get(
                "baseline_evidence_manifest_sha256"
            ),
            "treatment_evidence_manifest_sha256": evidence.get(
                "treatment_evidence_manifest_sha256"
            ),
        }
        for field_name, expected in expected_fields.items():
            if review.get(field_name) != expected:
                errors.append(f"comparison_review.{field_name} 与控制记录不一致")

    for field_name in ("problem_id", "profile", "runtime_version", "experiment_group_id"):
        if baseline.identity.get(field_name) != treatment.identity.get(field_name):
            errors.append(f"baseline/treatment {field_name} 不一致")
    if baseline.identity.get("prompt_sha256") != treatment.identity.get("prompt_sha256"):
        errors.append("baseline/treatment 规范化后的 prompt 不一致")
    if baseline.identity.get("response_sha256") == treatment.identity.get(
        "response_sha256"
    ):
        errors.append("baseline/treatment response 完全相同，不能证明独立运行")
    if control.get("case") != baseline.identity.get("problem_id"):
        errors.append("control.case 与运行 problem_id 不一致")
    if review is not None and review.get("experiment_group_id") != baseline.identity.get(
        "experiment_group_id"
    ):
        errors.append("comparison_review.experiment_group_id 与运行不一致")

    for filename in ("ai_run_metadata.json",):
        b_value = _load_object(baseline_dir / filename, f"baseline {filename}", errors)
        t_value = _load_object(treatment_dir / filename, f"treatment {filename}", errors)
        match_fields = policy.get("run_evidence_requirements", {}).get(
            "ai_run_metadata_checks", {}
        ).get("baseline_treatment_must_match", [])
        if b_value is not None and t_value is not None:
            for field_name in match_fields:
                if b_value.get(field_name) != t_value.get(field_name):
                    errors.append(f"baseline/treatment ai_run_metadata.{field_name} 不一致")

    for filename in ("problem_manifest.json",):
        b_value = _load_object(baseline_dir / filename, f"baseline {filename}", errors)
        t_value = _load_object(treatment_dir / filename, f"treatment {filename}", errors)
        if b_value is not None and t_value is not None and b_value.get(
            "content_digest"
        ) != t_value.get("content_digest"):
            errors.append("baseline/treatment 材料摘要不一致")

    b_runtime = _load_object(
        baseline_dir / "runtime_pack.manifest.json", "baseline runtime manifest", errors
    )
    t_runtime = _load_object(
        treatment_dir / "runtime_pack.manifest.json", "treatment runtime manifest", errors
    )
    if b_runtime is not None and t_runtime is not None:
        b_patches = {item.get("patch_id") for item in b_runtime.get("patches", [])}
        t_patches = {item.get("patch_id") for item in t_runtime.get("patches", [])}
        if t_patches - b_patches != {patch_id} or b_patches - t_patches:
            errors.append("baseline/treatment 不满足仅目标 Patch 不同")

    result = derive_control_result(control, review, evidence_valid=not errors)
    identity = {
        "experiment_group_id": baseline.identity.get("experiment_group_id"),
        "control_type": control_type,
        "target_patch": patch_id,
        "profile": baseline.identity.get("profile"),
        "baseline_run_id": baseline.identity.get("run_id"),
        "treatment_run_id": treatment.identity.get("run_id"),
    }
    return ControlOutcome(not errors, errors, identity, result=result, review=review)


def derive_v2_matrix_results(
    matrix: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], list[str]]:
    """复制 v2 矩阵并为每类控制附加唯一的现场派生结果。"""
    derived = json.loads(json.dumps(matrix))
    errors: list[str] = []
    if derived.get("matrix_version") != "2.0.0":
        return derived, errors
    for patch in derived.get("patches", []):
        patch["_matrix_version"] = derived.get("matrix_version")
        patch_id = str(patch.get("patch_id", "<unknown>"))
        for control_type in ("positive", "boundary", "negative"):
            control = patch.get(control_type)
            if not isinstance(control, dict):
                errors.append(f"{patch_id} {control_type} 控制记录缺失")
                continue
            outcome = validate_control_evidence(
                patch_id, control_type, control, policy, root=root
            )
            control["_derived_result"] = outcome.result
            control["_evidence_errors"] = outcome.errors
            errors.extend(
                f"{patch_id} {control_type}: {error}" for error in outcome.errors
            )
    return derived, errors


def validate_profile_record(
    record: Mapping[str, Any],
    profile_id: str,
    patches: list[dict[str, Any]],
    policy: Mapping[str, Any],
    *,
    root: Path = ROOT,
    validated_formal_patch_ids: set[str] | None = None,
) -> EvidenceOutcome:
    """按记录类型深验证 Profile 引用，不信任记录中的摘要字段。"""
    errors: list[str] = []
    path = _resolve(root, record.get("path"), "validation record path", errors)
    if path is None or not path.is_file():
        if path is not None:
            errors.append("validation record 文件不存在")
        return EvidenceOutcome(False, errors)
    if hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
        errors.append("validation record SHA-256 不匹配")
        return EvidenceOutcome(False, errors)

    kind = record.get("kind")
    if kind == "control_review":
        review = _load_object(path, "comparison review", errors)
        if review is None:
            return EvidenceOutcome(False, errors)
        target_patch = review.get("target_patch")
        patch = next((item for item in patches if item.get("patch_id") == target_patch), None)
        if patch is None or profile_id not in patch.get("runtime_profiles", []):
            errors.append("comparison review 的目标 Patch 不属于当前 Profile")
        control_type = review.get("control_type")
        if record.get("control_type") != control_type:
            errors.append("记录 control_type 与 comparison review 不一致")
        baseline_dir = _resolve(root, review.get("baseline_run"), "baseline_run", errors)
        case: Any = None
        if baseline_dir is not None:
            baseline_manifest = _load_object(
                baseline_dir / "run_manifest.json", "baseline run_manifest", errors
            )
            if baseline_manifest is not None:
                case = baseline_manifest.get("problem_id")
        control = {
            "case": case,
            "evidence": {
                "baseline_run": review.get("baseline_run"),
                "treatment_run": review.get("treatment_run"),
                "comparison_review": str(path.relative_to(root.resolve())).replace("\\", "/"),
                "baseline_evidence_manifest_sha256": review.get(
                    "baseline_evidence_manifest_sha256"
                ),
                "treatment_evidence_manifest_sha256": review.get(
                    "treatment_evidence_manifest_sha256"
                ),
            },
        }
        outcome = validate_control_evidence(
            str(target_patch), str(control_type), control, policy, root=root,
            expected_profile=profile_id,
        )
        errors.extend(outcome.errors)
        if outcome.result != "pass":
            errors.append(f"控制结论不是 pass：{outcome.result}")
        return EvidenceOutcome(
            not errors,
            errors,
            {
                **outcome.identity,
                "evidence_key": f"experiment_group:{outcome.identity.get('experiment_group_id')}",
            },
            review,
        )

    if kind == "full_run":
        if path.name != "seal_record.json":
            errors.append("full_run 必须引用 seal_record.json")
            return EvidenceOutcome(False, errors)
        outcome = validate_full_run(path.parent, policy, expected_profile=profile_id)
        outcome.identity["evidence_key"] = f"full_run:{outcome.identity.get('run_id')}"
        return outcome

    if kind == "competition":
        formal_patch_errors: list[str] = []
        if validated_formal_patch_ids is None:
            validated_formal_patch_ids, formal_patch_errors = (
                derive_validated_formal_patch_ids(patches, policy, root=root)
            )
        errors.extend(formal_patch_errors)
        evidence = _load_object(path, "competition evidence", errors)
        if evidence is None:
            return EvidenceOutcome(False, errors)
        errors.extend(
            f"competition evidence Schema: {issue}"
            for issue in _schema_errors(evidence, "competition_evidence.schema.json")
        )
        if evidence.get("profile") != profile_id:
            errors.append("competition evidence.profile 与当前 Profile 不一致")
        run_dir = _resolve(root, evidence.get("run_dir"), "competition run_dir", errors)
        runtime_path = _resolve(
            root, evidence.get("runtime_pack_manifest"), "runtime_pack_manifest", errors
        )
        result_path = _resolve(root, evidence.get("result_record"), "result_record", errors)
        run_outcome: EvidenceOutcome | None = None
        if run_dir is not None:
            run_outcome = validate_full_run(
                run_dir,
                policy,
                expected_profile=profile_id,
                expected_runtime_version=str(evidence.get("runtime_version")),
            )
            errors.extend(run_outcome.errors)
            if run_outcome.identity.get("run_id") != evidence.get("run_id"):
                errors.append("competition evidence.run_id 与运行不一致")
        for label, artifact_path, expected_sha in (
            ("runtime_pack_manifest", runtime_path, evidence.get("runtime_pack_manifest_sha256")),
            ("result_record", result_path, evidence.get("result_record_sha256")),
        ):
            if artifact_path is None or not artifact_path.is_file():
                errors.append(f"competition {label} 不存在")
            elif hashlib.sha256(artifact_path.read_bytes()).hexdigest() != expected_sha:
                errors.append(f"competition {label} SHA-256 不匹配")
        runtime_data = (
            _load_object(runtime_path, "competition runtime_pack_manifest", errors)
            if runtime_path is not None
            else None
        )
        if runtime_data is not None:
            errors.extend(
                f"runtime_pack_manifest Schema: {issue}"
                for issue in _schema_errors(
                    runtime_data, "runtime_pack_manifest.schema.json"
                )
            )
            if runtime_data.get("profile") != profile_id:
                errors.append("competition Runtime Pack Profile 不一致")
            if runtime_data.get("runtime_version") != evidence.get("runtime_version"):
                errors.append("competition Runtime Pack 版本不一致")
            if (
                run_outcome is not None
                and runtime_data.get("runtime_pack_sha256")
                != run_outcome.identity.get("runtime_pack_sha256")
            ):
                errors.append("competition Runtime Pack 与运行现场 SHA-256 不一致")
            stable_policy = policy.get("runtime_profile_stable_requirements", {})
            candidate = runtime_data.get("candidate_experiment", {})
            exclusion = runtime_data.get("exclusion_experiment", {})
            export_flags = runtime_data.get("export_flags", {})
            if stable_policy.get("forbid_candidate_experiment", True) and (
                not isinstance(candidate, Mapping)
                or candidate.get("enabled") is not False
                or candidate.get("patch_ids")
                or not isinstance(export_flags, Mapping)
                or export_flags.get("candidate_patches")
            ):
                errors.append("competition Profile 证据不得来自 candidate experiment")
            if stable_policy.get("forbid_exclusion_experiment", True) and (
                not isinstance(exclusion, Mapping)
                or exclusion.get("enabled") is not False
                or exclusion.get("patch_ids")
                or not isinstance(export_flags, Mapping)
                or export_flags.get("excluded_patches")
            ):
                errors.append("competition Profile 证据不得来自 exclusion experiment")
            if runtime_data.get("validation_target_status") != "competition_evidenced":
                errors.append(
                    "competition Runtime Pack 必须显式声明 validation_target_status=competition_evidenced"
                )

            expected_patches: dict[str, dict[str, Any]] = {}
            for item in patches:
                patch_id = item.get("patch_id")
                if (
                    isinstance(patch_id, str)
                    and profile_id in item.get("runtime_profiles", [])
                    and patch_id in validated_formal_patch_ids
                ):
                    expected_patches[patch_id] = item
            manifest_entries = runtime_data.get("patches", [])
            actual_patches: dict[str, Mapping[str, Any]] = {}
            for item in manifest_entries:
                if not isinstance(item, Mapping):
                    continue
                patch_id = item.get("patch_id")
                if isinstance(patch_id, str):
                    actual_patches[patch_id] = item
            if stable_policy.get("require_non_empty_verified_patches", True) and not expected_patches:
                errors.append("competition Profile 必须至少包含一个现场验证 Patch")
            if stable_policy.get("require_exact_patch_set", True) and set(
                actual_patches
            ) != set(expected_patches):
                errors.append(
                    "competition Runtime Pack Patch 集合与当前 Profile 不一致："
                    f"期望={sorted(expected_patches)}，实际={sorted(actual_patches)}"
                )
            for patch_id, patch_entry in actual_patches.items():
                indexed = expected_patches.get(patch_id)
                if indexed is None:
                    continue
                patch_path = _resolve(
                    root, indexed.get("file"), f"Patch {patch_id} 文件", errors
                )
                if patch_entry.get("path") != indexed.get("file"):
                    errors.append(f"competition Patch {patch_id} 路径与 patch_index 不一致")
                expected_runtime_status = indexed.get("status")
                if (
                    runtime_data.get("validation_target_status")
                    == "competition_evidenced"
                    and indexed.get("status") == "competition_evidenced"
                ):
                    expected_runtime_status = "regression_verified"
                if patch_entry.get("status") != expected_runtime_status:
                    errors.append(
                        f"competition Patch {patch_id} 当前状态与晋级证据不一致"
                    )
                if patch_path is None or not patch_path.is_file():
                    errors.append(f"competition Patch {patch_id} 文件不存在")
                elif patch_entry.get("sha256") != hashlib.sha256(
                    patch_path.read_bytes()
                ).hexdigest():
                    errors.append(f"competition Patch {patch_id} SHA-256 不一致")
        result_data = (
            _load_object(result_path, "competition result_record", errors)
            if result_path is not None
            else None
        )
        if result_data is not None:
            errors.extend(
                f"result_record Schema: {issue}"
                for issue in _schema_errors(result_data, "result_record.schema.json")
            )
            result_bindings = {
                "run_id": evidence.get("run_id"),
                "profile": profile_id,
                "runtime_version": evidence.get("runtime_version"),
                "runtime_pack_manifest": evidence.get("runtime_pack_manifest"),
                "runtime_pack_manifest_sha256": evidence.get(
                    "runtime_pack_manifest_sha256"
                ),
            }
            if run_outcome is not None:
                result_bindings["problem_id"] = run_outcome.identity.get("problem_id")
            for field_name, expected in result_bindings.items():
                if result_data.get(field_name) != expected:
                    errors.append(
                        f"competition result_record.{field_name} 与运行证据不一致"
                    )
            if result_data.get("result") != "pass":
                errors.append("competition result_record 未通过")
            if runtime_data is not None:
                runtime_patch_ids = {
                    item.get("patch_id")
                    for item in runtime_data.get("patches", [])
                    if isinstance(item, Mapping)
                }
                if result_data.get("target_patch") not in runtime_patch_ids:
                    errors.append("competition result_record.target_patch 不在运行包 Patch 集合中")
            if run_dir is not None:
                automatic_path = run_dir / "automatic_evaluation.json"
                automatic = _load_object(
                    automatic_path,
                    "competition automatic_evaluation",
                    errors,
                )
                if automatic_path.is_file():
                    actual_automatic_sha = hashlib.sha256(
                        automatic_path.read_bytes()
                    ).hexdigest()
                    if result_data.get("automatic_evaluation_sha256") != actual_automatic_sha:
                        errors.append(
                            "competition result_record.automatic_evaluation_sha256 与运行现场不一致"
                        )
                if automatic is not None:
                    expected_summary = {
                        field_name: automatic.get(field_name)
                        for field_name in (
                            "result",
                            "errors",
                            "response_sha256",
                            "case_sha256",
                            "evaluator_version",
                        )
                    }
                    if result_data.get("automatic_evaluation_summary") != expected_summary:
                        errors.append(
                            "competition result_record.automatic_evaluation_summary 与运行现场不一致"
                        )
        return EvidenceOutcome(
            not errors,
            errors,
            {
                "run_id": evidence.get("run_id"),
                "competition_id": evidence.get("competition_id"),
                "evidence_key": f"competition:{evidence.get('competition_id')}",
            },
            evidence,
        )

    return EvidenceOutcome(False, ["未知 validation record kind"])


def validate_formal_patch(
    patch: Mapping[str, Any],
    matrix_entry: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_status: str | None = None,
    enforce_recorded_status: bool = True,
) -> EvidenceOutcome:
    """验证 Patch 的当前状态或指定晋级目标是否由现场证据支持。"""
    status = patch.get("status")
    if status not in {"regression_verified", "competition_evidenced"}:
        return EvidenceOutcome(True)
    target_status = expected_status or status
    if target_status not in {"regression_verified", "competition_evidenced"}:
        return EvidenceOutcome(False, [f"不支持的正式 Patch 目标状态：{target_status}"])
    errors: list[str] = []
    from promotion_engine import evaluate_status_eligibility

    if not matrix_entry:
        return EvidenceOutcome(False, ["正式 Patch 在 v2 控制矩阵中没有记录"])
    entry = json.loads(json.dumps(matrix_entry))
    entry["_matrix_version"] = "2.0.0"
    for control_type in ("positive", "boundary", "negative"):
        control = entry.get(control_type)
        if not isinstance(control, dict):
            errors.append(f"缺少 {control_type} 控制记录")
            continue
        outcome = validate_control_evidence(
            str(patch.get("patch_id")), control_type, control, policy, root=root
        )
        control["_derived_result"] = outcome.result
        errors.extend(f"{control_type}: {error}" for error in outcome.errors)
    working_patch = dict(patch)
    source = patch.get("source", {})
    card_path = _resolve(root, source.get("knowledge_card"), "knowledge_card", errors)
    if card_path is None or not card_path.is_file():
        errors.append("正式 Patch 引用的知识卡片不存在")
    else:
        card = _load_object(card_path, "knowledge_card", errors)
        card_source = card.get("source", {}) if card is not None else {}
        claim_ids = source.get("claim_ids", [])
        if card_source.get("verification_status") != "verified" or not claim_ids:
            errors.append("正式 Patch 必须引用已验证 Claim ID")
        card_claim_ids = {
            claim.get("claim_id")
            for claim in card_source.get("claims", [])
            if isinstance(claim, Mapping) and isinstance(claim.get("claim_id"), str)
        }
        missing_claim_ids = (
            set(claim_ids) - card_claim_ids if isinstance(claim_ids, list) else set()
        )
        if missing_claim_ids:
            errors.append(
                "正式 Patch 引用的 Claim ID 不存在于知识卡片："
                + ", ".join(sorted(str(item) for item in missing_claim_ids))
            )
    if not patch.get("validation_records"):
        errors.append("正式 Patch 缺少 validation_records")

    patch_path = _resolve(root, patch.get("file"), "Patch 文件", errors)
    if patch_path is None or not patch_path.is_file():
        errors.append("正式 Patch 文件不存在")
    else:
        working_patch["_resolved_patch_sha256"] = hashlib.sha256(
            patch_path.read_bytes()
        ).hexdigest()

    stable_errors: list[str] = []
    inner_hashes: dict[str, str] = {}
    stable = patch.get("stable_evidence")
    if isinstance(stable, Mapping):
        negative_runs = stable.get("negative_control_runs", [])
        if not isinstance(negative_runs, list):
            stable_errors.append("stable_evidence.negative_control_runs 必须是数组")
            negative_runs = []
        for index, item in enumerate(negative_runs):
            if not isinstance(item, Mapping):
                stable_errors.append(f"stable 负控 #{index + 1} 必须是对象")
                continue
            baseline = _resolve(
                root, item.get("baseline_run"), "stable baseline_run", stable_errors
            )
            treatment = _resolve(
                root, item.get("treatment_run"), "stable treatment_run", stable_errors
            )
            review_path = _resolve(
                root, item.get("comparison_review"), "stable comparison_review", stable_errors
            )
            if baseline is None or treatment is None or review_path is None:
                continue
            baseline_manifest = baseline / "run_evidence_manifest.json"
            treatment_manifest = treatment / "run_evidence_manifest.json"
            if not baseline_manifest.is_file() or not treatment_manifest.is_file():
                stable_errors.append(f"stable 负控 #{index + 1} 缺少 Evidence Manifest")
                continue
            baseline_sha = hashlib.sha256(baseline_manifest.read_bytes()).hexdigest()
            treatment_sha = hashlib.sha256(treatment_manifest.read_bytes()).hexdigest()
            inner_hashes[
                f"negative_control_runs/{index}/baseline/run_evidence_manifest.json"
            ] = baseline_sha
            inner_hashes[
                f"negative_control_runs/{index}/treatment/run_evidence_manifest.json"
            ] = treatment_sha
            if review_path.is_file():
                inner_hashes[f"negative_control_runs/{index}/comparison_review"] = (
                    hashlib.sha256(review_path.read_bytes()).hexdigest()
                )
            control = {
                "case": item.get("case"),
                "evidence": {
                    "baseline_run": item.get("baseline_run"),
                    "treatment_run": item.get("treatment_run"),
                    "comparison_review": item.get("comparison_review"),
                    "baseline_evidence_manifest_sha256": baseline_sha,
                    "treatment_evidence_manifest_sha256": treatment_sha,
                },
            }
            outcome = validate_control_evidence(
                str(patch.get("patch_id")),
                "negative",
                control,
                policy,
                root=root,
            )
            stable_errors.extend(
                f"stable 负控 #{index + 1}: {error}" for error in outcome.errors
            )
            if outcome.result != "pass":
                stable_errors.append(
                    f"stable 负控 #{index + 1} 现场结论不是 pass：{outcome.result}"
                )

        retests = stable.get("failure_fix_retests", [])
        if not isinstance(retests, list):
            stable_errors.append("stable_evidence.failure_fix_retests 必须是数组")
            retests = []
        for index, item in enumerate(retests):
            if not isinstance(item, Mapping):
                stable_errors.append(f"失败修复重测 #{index + 1} 必须是对象")
                continue
            failure_id = item.get("failure_id")
            if not isinstance(failure_id, str) or not failure_id.strip():
                stable_errors.append(f"失败修复重测 #{index + 1} failure_id 不能为空")
                failure_id = ""
            semantic_records: dict[str, dict[str, Any]] = {}
            record_hashes: dict[str, str] = {}
            for key in ("failure_record", "fix_record", "review_record"):
                path = _resolve(root, item.get(key), key, stable_errors)
                if path is None or not path.is_file():
                    stable_errors.append(f"失败修复重测 #{index + 1} 的 {key} 不存在")
                else:
                    record_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                    record_hashes[key] = record_sha
                    inner_hashes[f"failure_fix_retests/{index}/{key}"] = record_sha
                    if path.suffix.lower() != ".json":
                        stable_errors.append(
                            f"失败修复重测 #{index + 1} 的 {key} 必须是结构化 JSON"
                        )
                    else:
                        record_data = _load_object(
                            path, f"失败修复重测 #{index + 1} {key}", stable_errors
                        )
                        if record_data is not None:
                            semantic_records[key] = record_data
                            if record_data.get("failure_id") != failure_id:
                                stable_errors.append(
                                    f"失败修复重测 #{index + 1} 的 {key}.failure_id 不一致"
                                )
                            if record_data.get("target_patch") != patch.get("patch_id"):
                                stable_errors.append(
                                    f"失败修复重测 #{index + 1} 的 {key} 绑定到其他 Patch"
                                )
            failure_record = semantic_records.get("failure_record", {})
            if not any(
                key in failure_record
                for key in (
                    "failure_label",
                    "failure_labels",
                    "original_failure",
                    "original_failure_snapshot",
                    "failure",
                    "issue_description",
                )
            ):
                stable_errors.append(
                    f"失败修复重测 #{index + 1} failure_record 缺少原失败描述或标签"
                )
            fix_record = semantic_records.get("fix_record", {})
            fix_descriptions = [
                value
                for key in ("fix_description", "fix", "changes")
                if isinstance((value := fix_record.get(key)), str)
            ]
            if not any(value.strip() for value in fix_descriptions):
                stable_errors.append(
                    f"失败修复重测 #{index + 1} fix_record 缺少修复内容"
                )
            review_record = semantic_records.get("review_record", {})
            if review_record.get("decision") not in {"approved", "pass"}:
                stable_errors.append(
                    f"失败修复重测 #{index + 1} review_record 必须批准重测"
                )
            reviewer = review_record.get("reviewer")
            if not isinstance(reviewer, str) or not reviewer.strip():
                stable_errors.append(
                    f"失败修复重测 #{index + 1} review_record.reviewer 不能为空"
                )
            retest = _resolve(root, item.get("retest_run"), "retest_run", stable_errors)
            retest_run_id: str | None = None
            retest_manifest_sha: str | None = None
            if retest is not None:
                outcome = validate_full_run(
                    retest,
                    policy,
                    expected_target_patch=str(patch.get("patch_id")),
                    expected_role="patch_only",
                )
                stable_errors.extend(
                    f"失败修复重测 #{index + 1}: {error}" for error in outcome.errors
                )
                actual_run_id = outcome.identity.get("run_id")
                if isinstance(actual_run_id, str) and actual_run_id.strip():
                    retest_run_id = actual_run_id
                else:
                    stable_errors.append(
                        f"失败修复重测 #{index + 1} 无法从重测证据派生 run_id"
                    )
                retest_manifest = retest / "run_evidence_manifest.json"
                if retest_manifest.is_file():
                    retest_manifest_sha = hashlib.sha256(
                        retest_manifest.read_bytes()
                    ).hexdigest()
                    inner_hashes[
                        f"failure_fix_retests/{index}/retest_evidence_manifest.json"
                    ] = retest_manifest_sha

            if retest_run_id is not None:
                for key, record_data in semantic_records.items():
                    if record_data.get("retest_run_id") != retest_run_id:
                        stable_errors.append(
                            f"失败修复重测 #{index + 1} 的 {key}.retest_run_id 与现场重测不一致"
                        )
            if review_record.get("fix_record_sha256") != record_hashes.get("fix_record"):
                stable_errors.append(
                    f"失败修复重测 #{index + 1} review_record.fix_record_sha256 不匹配"
                )
            if (
                failure_id
                and retest_run_id is not None
                and retest_manifest_sha is not None
                and "failure_record" in record_hashes
                and "fix_record" in record_hashes
            ):
                expected_digest = failure_fix_evidence_digest(
                    failure_id=failure_id,
                    target_patch=str(patch.get("patch_id")),
                    retest_run_id=retest_run_id,
                    failure_record_sha256=record_hashes["failure_record"],
                    fix_record_sha256=record_hashes["fix_record"],
                    retest_evidence_manifest_sha256=retest_manifest_sha,
                )
                if review_record.get("evidence_digest") != expected_digest:
                    stable_errors.append(
                        f"失败修复重测 #{index + 1} review_record.evidence_digest 不匹配"
                    )

        competitions = stable.get("competition_validation_records", [])
        if not isinstance(competitions, list):
            stable_errors.append(
                "stable_evidence.competition_validation_records 必须是数组"
            )
            competitions = []
        for index, item in enumerate(competitions):
            if not isinstance(item, Mapping):
                stable_errors.append(f"比赛验证 #{index + 1} 必须是对象")
                continue
            manifest_path = _resolve(
                root,
                item.get("runtime_pack_manifest"),
                "runtime_pack_manifest",
                stable_errors,
            )
            result_path = _resolve(
                root, item.get("result_record"), "result_record", stable_errors
            )
            manifest = None
            if manifest_path is None or not manifest_path.is_file():
                stable_errors.append(f"比赛验证 #{index + 1} Runtime Pack Manifest 不存在")
            else:
                manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                inner_hashes[
                    f"competition_validation_records/{index}/runtime_pack_manifest"
                ] = manifest_sha
                if item.get("runtime_pack_manifest_sha256") != manifest_sha:
                    stable_errors.append(f"比赛验证 #{index + 1} manifest SHA-256 不匹配")
                manifest = _load_object(
                    manifest_path, f"比赛验证 #{index + 1} manifest", stable_errors
                )
                if manifest is not None:
                    stable_errors.extend(
                        f"比赛验证 #{index + 1} manifest Schema: {issue}"
                        for issue in _schema_errors(
                            manifest, "runtime_pack_manifest.schema.json"
                        )
                    )
                    matching = [
                        entry_item
                        for entry_item in manifest.get("patches", [])
                        if isinstance(entry_item, Mapping)
                        and entry_item.get("patch_id") == patch.get("patch_id")
                    ]
                    if len(matching) != 1:
                        stable_errors.append(
                            f"比赛验证 #{index + 1} 必须恰好包含当前 Patch"
                        )
                    elif (
                        matching[0].get("path") != patch.get("file")
                        or matching[0].get("sha256")
                        != working_patch.get("_resolved_patch_sha256")
                        or matching[0].get("status") != "regression_verified"
                        or manifest.get("validation_target_status")
                        != "competition_evidenced"
                    ):
                        stable_errors.append(
                            f"比赛验证 #{index + 1} Patch 当前状态、路径、哈希或晋级目标不一致"
                        )
            if result_path is None or not result_path.is_file():
                stable_errors.append(f"比赛验证 #{index + 1} result_record 不存在")
            else:
                inner_hashes[
                    f"competition_validation_records/{index}/result_record"
                ] = hashlib.sha256(result_path.read_bytes()).hexdigest()
                result = _load_object(
                    result_path, f"比赛验证 #{index + 1} result_record", stable_errors
                )
                if result is not None:
                    stable_errors.extend(
                        f"比赛验证 #{index + 1} result Schema: {issue}"
                        for issue in _schema_errors(result, "result_record.schema.json")
                    )
                    if result.get("result") != "pass":
                        stable_errors.append(f"比赛验证 #{index + 1} 结果不是 pass")
                    if result.get("target_patch") != patch.get("patch_id"):
                        stable_errors.append(
                            f"比赛验证 #{index + 1} result_record.target_patch 与当前 Patch 不一致"
                        )
                    if result.get("runtime_pack_manifest") != item.get(
                        "runtime_pack_manifest"
                    ):
                        stable_errors.append(
                            f"比赛验证 #{index + 1} result_record 指向其他运行包"
                        )
                    if (
                        manifest_path is not None
                        and manifest_path.is_file()
                        and result.get("runtime_pack_manifest_sha256")
                        != hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    ):
                        stable_errors.append(
                            f"比赛验证 #{index + 1} result_record manifest SHA-256 不一致"
                        )

    working_patch["_resolved_inner_sha256s"] = dict(sorted(inner_hashes.items()))
    regression = evaluate_status_eligibility(
        working_patch, entry, dict(policy), "regression_verified"
    )
    competition = evaluate_status_eligibility(
        working_patch, entry, dict(policy), "competition_evidenced"
    )
    prerequisites_valid = not errors
    regression_valid = prerequisites_valid and regression.eligible
    competition_valid = (
        prerequisites_valid
        and isinstance(stable, Mapping)
        and not stable_errors
        and competition.eligible
    )
    derived_status = (
        "competition_evidenced"
        if competition_valid
        else "regression_verified"
        if regression_valid
        else "review_ready"
    )
    if derived_status != target_status:
        errors.append(
            f"Patch 目标状态 {target_status} 与现场证据派生状态 {derived_status} 不一致"
        )
    if enforce_recorded_status and status != derived_status:
        errors.append(
            f"Patch 记录状态 {status} 与现场证据派生状态 {derived_status} 不一致"
        )
    if target_status == "competition_evidenced":
        errors.extend(stable_errors)
        errors.extend(competition.gaps)
    elif target_status == "regression_verified":
        errors.extend(regression.gaps)
    return EvidenceOutcome(not errors, errors, {"derived_status": derived_status})


def derive_validated_formal_patch_ids(
    patches: list[dict[str, Any]],
    policy: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> tuple[set[str], list[str]]:
    """深验证所有声明为正式状态的 Patch，返回可信 ID 集合与闭锁错误。"""
    formal = [
        patch
        for patch in patches
        if patch.get("status") in {"regression_verified", "competition_evidenced"}
    ]
    if not formal:
        return set(), []

    errors: list[str] = []
    matrix_path = root / "tests" / "prompt_regression" / "patch_negative_control_matrix.json"
    matrix = _load_object(matrix_path, "patch_negative_control_matrix.json", errors)
    if matrix is None:
        return set(), errors
    if matrix.get("matrix_version") != "2.0.0":
        errors.append("正式 Patch 深验证必须使用 control matrix v2")
        return set(), errors

    matrix_by_id = {
        item.get("patch_id"): item
        for item in matrix.get("patches", [])
        if isinstance(item, dict) and isinstance(item.get("patch_id"), str)
    }
    validated: set[str] = set()
    for patch in formal:
        patch_id = str(patch.get("patch_id", "<unknown>"))
        outcome = validate_formal_patch(
            patch,
            matrix_by_id.get(patch_id, {}),
            policy,
            root=root,
        )
        if outcome.valid:
            validated.add(patch_id)
        else:
            errors.extend(f"正式 Patch {patch_id}: {error}" for error in outcome.errors)
    return validated, errors
