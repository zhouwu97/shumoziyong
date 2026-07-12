"""正式结果 Bundle 的统一、失败即关闭验证器。"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import FormalResultVerificationError
from .hashing import file_sha256, semantic_sha256
from .identity import FORMAL_RESULT_POLICY_REQUIRED, assert_identity, immutable_identity
from .schema import validate_schema


CORE_RELATIVE_PATHS = (
    "formal_result_manifest.json",
    "decision_variables.json",
    "optimization_validation.json",
    "optimality_certificate.json",
    "collector_attestation.json",
    "negative_tests.json",
    "logs/stdout.log",
    "logs/stderr.log",
)


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

    envelope_relative = Path(envelope_path).as_posix()
    if Path(envelope_path).is_absolute():
        try:
            envelope_relative = Path(envelope_path).resolve().relative_to(run_root).as_posix()
        except ValueError as exc:
            raise FormalResultVerificationError("Envelope 不在当前 Run 目录内") from exc
    envelope_file = _safe_relative(run_root, envelope_relative, "Envelope 路径")
    envelope = _load_object(envelope_file, "formal_result_envelope.json")
    validate_schema(envelope, "formal_result_envelope.schema.json", "formal_result_envelope.json")
    assert_identity(envelope, identity, "formal_result_envelope")

    formal_result_id = envelope["formal_result_id"]
    formal_root_relative = f"formal_results/{formal_result_id}"
    expected_envelope_path = f"{formal_root_relative}/formal_result_envelope.json"
    if envelope_relative != expected_envelope_path:
        raise FormalResultVerificationError("Envelope 路径必须与 formal_result_id 一致")
    formal_root = _safe_relative(run_root, formal_root_relative, "Formal Result 根目录")

    execution_spec_path = run_root / "execution_spec.json"
    execution_spec = _load_object(execution_spec_path, "execution_spec.json")
    validate_schema(execution_spec, "execution_spec.schema.json", "execution_spec.json")
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
    validate_schema(domain, "domain_manifest.schema.json", "domain_manifest.json")
    assert_identity(domain, identity, "domain_manifest")
    if domain.get("formal_result_id") != formal_result_id:
        raise FormalResultVerificationError("domain_manifest.formal_result_id 不匹配")
    if envelope["domain_manifest_file_sha256"] != file_sha256(domain_path):
        raise FormalResultVerificationError("Domain Manifest 文件哈希不匹配")
    if envelope["domain_manifest_semantic_sha256"] != semantic_sha256(domain):
        raise FormalResultVerificationError("Domain Manifest 语义哈希不匹配")

    descriptors = domain["required_artifacts"]
    descriptor_paths = [item["path"] for item in descriptors]
    if descriptor_paths != list(CORE_RELATIVE_PATHS):
        raise FormalResultVerificationError("Domain Manifest 核心文件集或顺序不符合 required_v1 合同")
    actual_files = sorted(
        path.relative_to(formal_root).as_posix()
        for path in formal_root.rglob("*")
        if path.is_file()
    )
    expected_files = sorted(("formal_result_envelope.json", "domain_manifest.json", *CORE_RELATIVE_PATHS))
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

    formal_manifest = values["formal_result_manifest.json"]
    if envelope["formal_result_manifest_file_sha256"] != file_sha256(formal_manifest_path):
        raise FormalResultVerificationError("Formal Result Manifest 文件哈希不匹配")
    if envelope["formal_result_manifest_semantic_sha256"] != semantic_sha256(formal_manifest):
        raise FormalResultVerificationError("Formal Result Manifest 语义哈希不匹配")
    attestation = values["collector_attestation.json"]
    if envelope["collector_attestation_semantic_sha256"] != semantic_sha256(attestation):
        raise FormalResultVerificationError("Collector Attestation 语义哈希不匹配")

    expected_semantic = {
        path: descriptor.get("semantic_sha256")
        for path, descriptor in zip(descriptor_paths, descriptors, strict=True)
        if descriptor["media_type"] == "application/json"
    }
    chain_bindings = {
        "decision_variables.json": {
            "execution_spec.json": envelope["execution_spec_semantic_sha256"]
        },
        "optimization_validation.json": {
            "decision_variables.json": expected_semantic["decision_variables.json"]
        },
        "optimality_certificate.json": {
            "optimization_validation.json": expected_semantic["optimization_validation.json"]
        },
        "negative_tests.json": {
            "execution_spec.json": envelope["execution_spec_semantic_sha256"]
        },
    }
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

    return {
        "formal_result_id": formal_result_id,
        "execution_spec_file_sha256": file_sha256(execution_spec_path),
        "execution_spec_semantic_sha256": semantic_sha256(execution_spec),
        "envelope_path": expected_envelope_path,
        "envelope_file_sha256": file_sha256(envelope_file),
        "envelope_semantic_sha256": semantic_sha256(envelope),
        "artifacts": verified,
        "identity": identity,
    }
