"""正式结果 Bundle 的统一、失败即关闭验证器。"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from .domain_contracts import DomainContract, domain_contract_for_manifest
from .errors import FormalResultVerificationError
from .hashing import file_sha256, semantic_sha256
from .identity import FORMAL_RESULT_POLICY_REQUIRED, assert_identity, immutable_identity
from .path_safety import (
    validate_contract_id,
    validate_contract_relative_path,
    validate_execution_command_bindings,
    validate_execution_spec_paths,
)
from .schema import validate_schema
from .prediction_validation import verify_prediction_domain_contract
from .trusted_local import trusted_local_eligibility_scope
from .sandboxie_environment import load_and_verify_sandboxie_environment_report
from .run_execution_attestation import (
    ATTESTATION_FILENAME as RUN_ATTESTATION_FILENAME,
    verify_run_execution_attestation,
)


OPTIMALITY_STATUS_BY_CLAIM = {
    "optimal": "optimal",
    "feasible": "feasible",
    "heuristic": "feasible",
}

EXPECTED_PROVENANCE_ARTIFACTS = {
    "input_manifest.json": "input_manifest",
    "code_manifest.json": "code_manifest",
    "environment_manifest.json": "environment_manifest",
}

def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FormalResultVerificationError(f"{label} 不存在") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormalResultVerificationError(f"{label} 不是严格 UTF-8 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise FormalResultVerificationError(f"{label} 必须是 JSON 对象")
    return value


def _safe_relative(root: Path, value: str, label: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value or ":" in value:
        raise FormalResultVerificationError(f"{label} 必须是 Run 内安全相对路径")
    path = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise FormalResultVerificationError(f"{label} 禁止符号链接：{value}")
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise FormalResultVerificationError(f"{label} 越出 Run 目录：{value}") from exc
    # POSIX 目录的链接计数会包含自身、父目录及子目录，不能据此判定 hardlink。
    if path.is_file() and os.stat(path, follow_symlinks=False).st_nlink != 1:
        raise FormalResultVerificationError(f"{label} 禁止 hardlink：{value}")
    return path


def _verify_json_artifact(
    path: Path,
    descriptor: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    value = _load_object(path, label)
    schema_name = descriptor.get("schema")
    if not isinstance(schema_name, str):
        raise FormalResultVerificationError(f"{label} 缺少 Schema 绑定")
    validate_schema(value, schema_name, label)
    if descriptor.get("semantic_sha256") != semantic_sha256(value):
        raise FormalResultVerificationError(f"{label} semantic_sha256 不匹配")
    return value


def _matches_declared_type(value: Any, declared_type: str) -> bool:
    """按 JSON 类型而非 Python 的 bool/int 继承关系检查指标。"""
    if declared_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "boolean":
        return isinstance(value, bool)
    return False


def _verify_negative_tests(
    domain: dict[str, Any], values: dict[str, dict[str, Any]]
) -> None:
    """复核所有领域共享的负控集合和状态。"""
    negative_results = values["negative_tests.json"].get("payload", {}).get("results")
    if not isinstance(negative_results, list):
        raise FormalResultVerificationError("negative_tests.payload.results 缺失")
    by_id: dict[str, dict[str, Any]] = {}
    for item in negative_results:
        if isinstance(item, dict) and isinstance(item.get("test_id"), str):
            by_id[item["test_id"]] = item
    required_negative_tests = set(domain["negative_test_requirements"])
    if len(by_id) != len(negative_results) or set(by_id) != required_negative_tests:
        raise FormalResultVerificationError(
            "negative_test_requirements 与负控结果集合不一致"
        )
    failed_negative_tests = sorted(
        test_id for test_id, result in by_id.items() if result.get("status") != "passed"
    )
    if failed_negative_tests:
        raise FormalResultVerificationError(
            "负控测试未通过：" + ", ".join(failed_negative_tests)
        )


def _verify_optimization_domain_contract(
    domain: dict[str, Any],
    descriptors: list[dict[str, Any]],
    values: dict[str, dict[str, Any]],
    contract: DomainContract,
) -> None:
    """复核工程优化领域专属的证书、指标和不变量。"""
    descriptor_by_path = {item["path"]: item for item in descriptors}
    decision_descriptor = descriptor_by_path["decision_variables.json"]
    if decision_descriptor.get("schema") != domain["decision_schema"]:
        raise FormalResultVerificationError(
            "decision_variables.json 的 descriptor.schema 未绑定 domain.decision_schema"
        )
    if set(domain["output_file_set"]) != set(contract.output_file_set):
        raise FormalResultVerificationError(
            "domain.output_file_set 不符合工程优化 v1 固定正式输出集合"
        )

    actual_certificates = sorted(
        path
        for path, value in values.items()
        if value.get("artifact_type") == "optimality_certificate"
    )
    if sorted(domain["required_certificates"]) != actual_certificates:
        raise FormalResultVerificationError("required_certificates 与实际证书文件集不一致")

    certificate = values["optimality_certificate.json"]
    expected_certificate_status = OPTIMALITY_STATUS_BY_CLAIM[domain["optimality_claim_level"]]
    if certificate.get("status") != expected_certificate_status:
        raise FormalResultVerificationError(
            "optimality_certificate.status 与 optimality_claim_level 不一致"
        )

    validation_payload = values["optimization_validation.json"].get("payload", {})
    metrics = validation_payload.get("metrics")
    if not isinstance(metrics, dict):
        raise FormalResultVerificationError("optimization_validation.payload.metrics 缺失")
    for metric_name, metric_type in domain["metric_schema"].items():
        if metric_name not in metrics or not _matches_declared_type(metrics[metric_name], metric_type):
            raise FormalResultVerificationError(
                f"optimization_validation 未按 metric_schema 提供指标：{metric_name}"
            )

    invariant_results = validation_payload.get("invariant_checks")
    if not isinstance(invariant_results, dict):
        raise FormalResultVerificationError(
            "optimization_validation.payload.invariant_checks 缺失"
        )
    if set(invariant_results) != set(domain["invariant_checks"]):
        raise FormalResultVerificationError("invariant_checks 与验证结果集合不一致")
    for invariant_name, result in invariant_results.items():
        if not isinstance(result, dict) or result.get("status") != "passed":
            raise FormalResultVerificationError(f"领域不变量未通过：{invariant_name}")



def _verify_domain_contract(
    domain: dict[str, Any],
    descriptors: list[dict[str, Any]],
    values: dict[str, dict[str, Any]],
    contract: DomainContract,
) -> None:
    """按已注册领域合同复核文件类型、状态和领域语义。"""
    for relative, (artifact_type, allowed_statuses) in contract.expected_artifacts.items():
        value = values[relative]
        if value.get("artifact_type") != artifact_type:
            raise FormalResultVerificationError(
                f"{relative}.artifact_type 必须为 {artifact_type}"
            )
        if value.get("status") not in allowed_statuses:
            allowed = ", ".join(sorted(allowed_statuses))
            raise FormalResultVerificationError(f"{relative}.status 必须为 {allowed}")
    if contract.domain == "engineering_optimization":
        _verify_optimization_domain_contract(domain, descriptors, values, contract)
    elif contract.domain == "predictive_modeling":
        verify_prediction_domain_contract(domain, descriptors, values, contract)
    else:  # pragma: no cover - 注册表和分派必须同步
        raise FormalResultVerificationError(f"领域验证器未实现：{contract.domain}")
    if values["negative_tests.json"].get("status") == "passed":
        _verify_negative_tests(domain, values)


def _verify_provenance_manifests(
    run_root: Path,
    execution_spec: dict[str, Any],
    execution_spec_semantic_sha256: str,
    values: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """复核 Attestation 所引用的输入、代码和环境来源清单。"""
    expected_binding = {"execution_spec.json": execution_spec_semantic_sha256}
    for relative, artifact_type in EXPECTED_PROVENANCE_ARTIFACTS.items():
        manifest = values[relative]
        if manifest.get("artifact_type") != artifact_type:
            raise FormalResultVerificationError(
                f"{relative}.artifact_type 必须为 {artifact_type}"
            )
        if manifest.get("bindings") != expected_binding:
            raise FormalResultVerificationError(f"{relative}.bindings 未绑定 Execution Spec")

    expected_inputs = [
        {"task_id": task["task_id"], "path": item["path"], "sha256": item["sha256"]}
        for task in execution_spec["tasks"]
        for item in task["inputs"]
    ]
    if values["input_manifest.json"].get("payload", {}).get("inputs") != expected_inputs:
        raise FormalResultVerificationError(
            "input_manifest.json 未精确绑定 Execution Spec 输入集合"
        )
    for item in expected_inputs:
        input_path = _safe_relative(run_root, item["path"], "Execution Spec 输入路径")
        if not input_path.is_file():
            raise FormalResultVerificationError(f"Execution Spec 输入不存在：{item['path']}")
        if file_sha256(input_path) != item["sha256"]:
            raise FormalResultVerificationError(f"Execution Spec 输入文件哈希不匹配：{item['path']}")

    code_files = values["code_manifest.json"].get("payload", {}).get("files")
    if not isinstance(code_files, list):
        raise FormalResultVerificationError("code_manifest.json.payload.files 缺失")
    code_by_path: dict[str, dict[str, Any]] = {}
    for item in code_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise FormalResultVerificationError("code_manifest.json 包含非法文件引用")
        path_text = item["path"]
        workspace_root = execution_spec["declared_workspace"].split("/", 1)[0]
        try:
            validate_contract_relative_path(path_text, workspace_root, "Code Manifest 路径")
        except ValueError as exc:
            raise FormalResultVerificationError(str(exc)) from exc
        code_path = _safe_relative(run_root, path_text, "Code Manifest 路径")
        if not code_path.is_file() or item.get("sha256") != file_sha256(code_path):
            raise FormalResultVerificationError(f"Code Manifest 文件哈希不匹配：{path_text}")
        if path_text in code_by_path:
            raise FormalResultVerificationError(f"Code Manifest 路径重复：{path_text}")
        code_by_path[path_text] = item
    expected_entrypoints = {
        f"{execution_spec['declared_workspace']}/{task['entrypoint']}"
        for task in execution_spec["tasks"]
    }
    if not expected_entrypoints.issubset(code_by_path):
        raise FormalResultVerificationError("Code Manifest 未覆盖全部 Execution Spec 入口文件")
    code_root = _safe_relative(
        run_root,
        f"{execution_spec['declared_workspace']}/code",
        "完整代码目录",
    )
    for path in code_root.rglob("*"):
        is_junction = getattr(path, "is_junction", lambda: False)
        if path.is_symlink() or is_junction():
            raise FormalResultVerificationError(f"Code Manifest 禁止 symlink 或 junction：{path}")
    actual_code_files = {
        path.relative_to(run_root).as_posix()
        for path in code_root.rglob("*")
        if path.is_file()
    }
    if set(code_by_path) != actual_code_files:
        raise FormalResultVerificationError(
            f"Code Manifest 未精确覆盖完整代码目录：声明 {sorted(code_by_path)}，实际 {sorted(actual_code_files)}"
        )

    environment_payload = values["environment_manifest.json"].get("payload", {})
    activation_status = environment_payload.get("formal_result_activation_status")
    eligible = environment_payload.get("formal_result_eligible")
    observed = environment_payload.get("sandboxie_environment_observed")
    verified = environment_payload.get("sandboxie_environment_verified")
    executed = environment_payload.get("formal_result_executed_in_verified_environment")
    if activation_status == "code_complete_candidate":
        if eligible is not False or observed is not False or verified is not False or executed is not False:
            raise FormalResultVerificationError(
                "Environment Manifest 在 Sandboxie 激活前必须保持环境验证和 eligibility 为 false"
            )
        if {
            "sandboxie_environment_report",
            "sandboxie_environment_attestation",
        } & set(environment_payload):
            raise FormalResultVerificationError("未激活 Environment Manifest 禁止引用 Sandboxie 环境证据")
        return {
            "formal_result_activation_status": activation_status,
            "sandboxie_environment_observed": False,
            "sandboxie_environment_verified": False,
            "formal_result_executed_in_verified_environment": False,
            "formal_result_eligible": False,
        }
    if activation_status not in {"sandboxie_environment_verified", "run_execution_verified"}:
        raise FormalResultVerificationError("Environment Manifest 的 Sandboxie 激活状态非法")
    expected_run_verified = activation_status == "run_execution_verified"
    if (
        observed is not True
        or verified is not True
        or executed is not expected_run_verified
        or eligible is not expected_run_verified
    ):
        raise FormalResultVerificationError("Environment Manifest 的 Sandboxie 激活状态组合非法")

    binding = environment_payload.get("sandboxie_environment_report")
    if not isinstance(binding, dict) or binding.get("path") != "sandboxie_environment_report.json":
        raise FormalResultVerificationError("Environment Manifest 缺少固定 Sandboxie 报告路径绑定")
    attestation_binding = environment_payload.get("sandboxie_environment_attestation")
    if (
        not isinstance(attestation_binding, dict)
        or attestation_binding.get("path") != "sandboxie_environment_attestation.json"
    ):
        raise FormalResultVerificationError("Environment Manifest 缺少固定机器签名 Attestation 绑定")
    report_path = _safe_relative(run_root, str(binding["path"]), "Sandboxie 环境报告路径")
    attestation_path = _safe_relative(
        run_root,
        str(attestation_binding["path"]),
        "Sandboxie Attestation 路径",
    )
    summary = load_and_verify_sandboxie_environment_report(report_path, attestation_path)
    expected = {
        "path": "sandboxie_environment_report.json",
        "report_id": summary["report_id"],
        "file_sha256": summary["report_file_sha256"],
        "semantic_sha256": summary["report_semantic_sha256"],
        "configuration_backup_path": summary["configuration_backup_path"],
        "configuration_backup_sha256": summary["configuration_backup_sha256"],
    }
    if binding != expected:
        raise FormalResultVerificationError("Environment Manifest 的 Sandboxie 报告绑定不匹配")
    expected_attestation = {
        "path": "sandboxie_environment_attestation.json",
        "file_sha256": summary["attestation_file_sha256"],
        "semantic_sha256": summary["attestation_semantic_sha256"],
        "original_report_sha256": summary["original_report_sha256"],
        "environment_fingerprint": summary["environment_fingerprint"],
        "machine_key_id": summary["machine_key_id"],
    }
    if attestation_binding != expected_attestation:
        raise FormalResultVerificationError("Environment Manifest 的机器签名 Attestation 绑定不匹配")
    if expected_run_verified:
        run_binding = environment_payload.get("sandboxie_run_execution_attestation")
        if not isinstance(run_binding, dict) or run_binding.get("path") != RUN_ATTESTATION_FILENAME:
            raise FormalResultVerificationError("Environment Manifest 缺少 Run 专属执行证明绑定")
        run_summary = verify_run_execution_attestation(run_root, str(execution_spec.get("formal_result_id", "")) or str(values["environment_manifest.json"]["formal_result_id"]))
        expected_run_binding = {
            "path": RUN_ATTESTATION_FILENAME,
            "file_sha256": run_summary["run_attestation_file_sha256"],
            "semantic_sha256": run_summary["run_attestation_semantic_sha256"],
            "execution_id": run_summary["execution_id"],
        }
        if run_binding != expected_run_binding:
            raise FormalResultVerificationError("Environment Manifest 的 Run 执行证明绑定不匹配")
        return {
            **summary,
            **run_summary,
            "report_path": "sandboxie_environment_report.json",
            "attestation_path": "sandboxie_environment_attestation.json",
            "run_attestation_path": RUN_ATTESTATION_FILENAME,
        }
    return {
        **summary,
        "report_path": "sandboxie_environment_report.json",
        "attestation_path": "sandboxie_environment_attestation.json",
    }


def verify_formal_result_bundle(run_dir: Path, envelope_path: str | Path) -> dict[str, Any]:
    """
    验证 Envelope、领域 Manifest、精确文件集、哈希链和当前 Run 身份。

    返回值只是已验证证据摘要，不代表通用数学正确性。
    """
    run_root = run_dir.resolve()
    run_manifest = _load_object(run_root / "run_manifest.json", "run_manifest.json")
    if run_manifest.get("formal_result_policy") != FORMAL_RESULT_POLICY_REQUIRED:
        raise FormalResultVerificationError("仅 required_v1 Run 可以生成或验证新正式结果")
    identity = immutable_identity(run_manifest)

    envelope_candidate = Path(envelope_path)
    envelope_relative = envelope_candidate.as_posix()
    if envelope_candidate.is_absolute() or envelope_candidate.exists():
        try:
            envelope_relative = envelope_candidate.resolve().relative_to(run_root).as_posix()
        except ValueError as exc:
            raise FormalResultVerificationError("Envelope 不在当前 Run 目录内") from exc
    envelope_file = _safe_relative(run_root, envelope_relative, "Envelope 路径")
    envelope = _load_object(envelope_file, "formal_result_envelope.json")
    validate_schema(envelope, "formal_result_envelope.schema.json", "formal_result_envelope.json")
    assert_identity(envelope, identity, "formal_result_envelope")

    formal_result_id = envelope["formal_result_id"]
    try:
        validate_contract_id(formal_result_id, "formal_result_id")
    except ValueError as exc:
        raise FormalResultVerificationError(str(exc)) from exc
    formal_root_relative = f"formal_results/{formal_result_id}"
    expected_envelope_path = f"{formal_root_relative}/formal_result_envelope.json"
    if envelope_relative != expected_envelope_path:
        raise FormalResultVerificationError("Envelope 路径必须与 formal_result_id 一致")
    formal_root = _safe_relative(run_root, formal_root_relative, "Formal Result 根目录")

    execution_spec_path = _safe_relative(run_root, "execution_spec.json", "Execution Spec 路径")
    execution_spec = _load_object(execution_spec_path, "execution_spec.json")
    validate_schema(execution_spec, "execution_spec.schema.json", "execution_spec.json")
    try:
        validate_execution_spec_paths(execution_spec)
        validate_execution_command_bindings(execution_spec, run_root)
    except ValueError as exc:
        raise FormalResultVerificationError(f"execution_spec 路径合同无效：{exc}") from exc
    assert_identity(execution_spec, identity, "execution_spec")
    if envelope["execution_spec_file_sha256"] != file_sha256(execution_spec_path):
        raise FormalResultVerificationError("Envelope 的 execution_spec_file_sha256 不匹配")
    if envelope["execution_spec_semantic_sha256"] != semantic_sha256(execution_spec):
        raise FormalResultVerificationError("Envelope 的 execution_spec_semantic_sha256 不匹配")

    domain_path = _safe_relative(run_root, envelope["domain_manifest_path"], "Domain Manifest 路径")
    formal_manifest_path = _safe_relative(
        run_root, envelope["formal_result_manifest_path"], "Formal Result Manifest 路径"
    )
    if domain_path != formal_root / "domain_manifest.json":
        raise FormalResultVerificationError("Domain Manifest 不在当前 Formal Result 目录")
    if formal_manifest_path != formal_root / "formal_result_manifest.json":
        raise FormalResultVerificationError("Formal Result Manifest 路径非法")

    domain = _load_object(domain_path, "domain_manifest.json")
    contract = domain_contract_for_manifest(domain)
    validate_schema(domain, contract.manifest_schema, "domain_manifest.json")
    assert_identity(domain, identity, "domain_manifest")
    if domain.get("formal_result_id") != formal_result_id:
        raise FormalResultVerificationError("domain_manifest.formal_result_id 不匹配")
    if envelope["domain_manifest_file_sha256"] != file_sha256(domain_path):
        raise FormalResultVerificationError("Domain Manifest 文件哈希不匹配")
    if envelope["domain_manifest_semantic_sha256"] != semantic_sha256(domain):
        raise FormalResultVerificationError("Domain Manifest 语义哈希不匹配")

    descriptors = domain["required_artifacts"]
    descriptor_paths = [item["path"] for item in descriptors]
    if descriptor_paths != list(contract.required_artifacts):
        raise FormalResultVerificationError("Domain Manifest 核心文件集或顺序不符合 required_v1 合同")
    actual_files = sorted(
        path.relative_to(formal_root).as_posix()
        for path in formal_root.rglob("*")
        if path.is_file()
    )
    expected_files = sorted(
        ("formal_result_envelope.json", "domain_manifest.json", *contract.required_artifacts)
    )
    if actual_files != expected_files:
        raise FormalResultVerificationError(
            f"Formal Result 精确文件集不匹配：期望 {expected_files}，实际 {actual_files}"
        )

    verified: dict[str, dict[str, Any]] = {}
    values: dict[str, dict[str, Any]] = {}
    for descriptor in descriptors:
        relative = descriptor["path"]
        artifact_path = _safe_relative(formal_root, relative, f"正式结果文件 {relative}")
        if not artifact_path.is_file():
            raise FormalResultVerificationError(f"正式结果文件缺失：{relative}")
        actual_file_sha = file_sha256(artifact_path)
        if descriptor["file_sha256"] != actual_file_sha:
            raise FormalResultVerificationError(f"{relative} file_sha256 不匹配")
        item = {"path": artifact_path.relative_to(run_root).as_posix(), "file_sha256": actual_file_sha}
        if descriptor["media_type"] == "application/json":
            value = _verify_json_artifact(artifact_path, descriptor, relative)
            assert_identity(value, identity, relative)
            if value.get("formal_result_id") != formal_result_id:
                raise FormalResultVerificationError(f"{relative}.formal_result_id 不匹配")
            values[relative] = value
            item["semantic_sha256"] = descriptor["semantic_sha256"]
        verified[relative] = item

    _verify_domain_contract(domain, descriptors, values, contract)
    environment_summary = _verify_provenance_manifests(
        run_root,
        execution_spec,
        envelope["execution_spec_semantic_sha256"],
        values,
    )

    formal_manifest = values["formal_result_manifest.json"]
    if envelope["formal_result_manifest_file_sha256"] != file_sha256(formal_manifest_path):
        raise FormalResultVerificationError("Formal Result Manifest 文件哈希不匹配")
    if envelope["formal_result_manifest_semantic_sha256"] != semantic_sha256(formal_manifest):
        raise FormalResultVerificationError("Formal Result Manifest 语义哈希不匹配")
    attestation = values["collector_attestation.json"]
    if envelope["collector_attestation_semantic_sha256"] != semantic_sha256(attestation):
        raise FormalResultVerificationError("Collector Attestation 语义哈希不匹配")
    attestation_hashes = {
        "input_manifest_sha256": verified["input_manifest.json"]["file_sha256"],
        "code_manifest_sha256": verified["code_manifest.json"]["file_sha256"],
        "execution_spec_sha256": file_sha256(execution_spec_path),
        "environment_manifest_sha256": verified["environment_manifest.json"]["file_sha256"],
        "stdout_sha256": verified["logs/stdout.log"]["file_sha256"],
        "stderr_sha256": verified["logs/stderr.log"]["file_sha256"],
        "negative_test_report_sha256": verified["negative_tests.json"]["file_sha256"],
    }
    for field, expected in attestation_hashes.items():
        if attestation.get(field) != expected:
            raise FormalResultVerificationError(f"collector_attestation.{field} 不匹配")
    if attestation.get("candidate_output_access_not_detected") is not True:
        raise FormalResultVerificationError(
            "collector_attestation.candidate_output_access_not_detected 必须为 true"
        )
    if sorted(attestation.get("output_file_set", [])) != sorted(domain["output_file_set"]):
        raise FormalResultVerificationError(
            "collector_attestation.output_file_set 与 Domain Manifest 不一致"
        )

    expected_semantic = {
        path: descriptor.get("semantic_sha256")
        for path, descriptor in zip(descriptor_paths, descriptors, strict=True)
        if descriptor["media_type"] == "application/json"
    }
    chain_bindings = {}
    for relative, source in contract.chain_bindings.items():
        source_hash = (
            envelope["execution_spec_semantic_sha256"]
            if source == "execution_spec.json"
            else expected_semantic[source]
        )
        chain_bindings[relative] = {source: source_hash}
    for relative, expected_bindings in chain_bindings.items():
        if values[relative].get("bindings") != expected_bindings:
            raise FormalResultVerificationError(f"{relative}.bindings 未形成固定语义哈希链")

    if domain["semantic_hashes"] != expected_semantic:
        raise FormalResultVerificationError("Domain Manifest semantic_hashes 未精确绑定所有结构化核心文件")
    manifest_bound_semantic = {
        path: value for path, value in expected_semantic.items() if path != "formal_result_manifest.json"
    }
    if formal_manifest.get("semantic_hashes") != manifest_bound_semantic:
        raise FormalResultVerificationError("Formal Result Manifest 未反向绑定完整语义哈希集")

    summary = {
        "formal_result_id": formal_result_id,
        "formal_result_domain": contract.domain,
        "execution_spec_file_sha256": file_sha256(execution_spec_path),
        "execution_spec_semantic_sha256": semantic_sha256(execution_spec),
        "envelope_path": expected_envelope_path,
        "envelope_file_sha256": file_sha256(envelope_file),
        "envelope_semantic_sha256": semantic_sha256(envelope),
        "domain_manifest_path": domain_path.relative_to(run_root).as_posix(),
        "domain_manifest_file_sha256": file_sha256(domain_path),
        "domain_manifest_semantic_sha256": semantic_sha256(domain),
        "formal_result_activation_status": environment_summary[
            "formal_result_activation_status"
        ],
        "sandboxie_environment_verified": environment_summary[
            "sandboxie_environment_verified"
        ],
        "sandboxie_environment_observed": environment_summary[
            "sandboxie_environment_observed"
        ],
        "formal_result_executed_in_verified_environment": environment_summary[
            "formal_result_executed_in_verified_environment"
        ],
        "formal_result_eligible": environment_summary["formal_result_eligible"],
        "sandboxie_environment": environment_summary,
        "artifacts": verified,
        "identity": identity,
    }
    summary.update(trusted_local_eligibility_scope(environment_summary))
    return summary
