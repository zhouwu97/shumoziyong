"""Sandbox raw output 到 Formal Result core 的可执行派生合同。"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .collector_policy import (
    COLLECTOR_ID,
    COLLECTOR_SCRIPT_PATH,
    DERIVATION_CONTRACT_ID,
    TRUSTED_DOMAIN_POLICY,
    collector_script_sha256_at_commit,
    derivation_contract_sha256,
    domain_policy_sha256,
    trusted_derivation_contract,
)
from .errors import FormalResultVerificationError
from .hashing import file_sha256, semantic_sha256
from .schema import validate_schema


CORE_ARTIFACTS = (
    "decision_variables.json",
    "optimization_validation.json",
    "optimality_certificate.json",
    "negative_tests.json",
)
PAYLOAD_MANIFEST_FILENAME = "formal_result_payload_manifest.json"
DERIVATION_ATTESTATION_FILENAME = "collector_derivation_attestation.json"


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormalResultVerificationError(f"{label} 无法读取：{exc}") from exc
    if not isinstance(value, dict):
        raise FormalResultVerificationError(f"{label} 必须是 JSON 对象")
    return value


def _pointer(value: Any, pointer: str, label: str) -> Any:
    current = value
    for raw_part in pointer.removeprefix("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise FormalResultVerificationError(f"{label} JSON Pointer 不存在：{pointer}")
    return current


def core_semantic_hashes(formal_root: Path) -> dict[str, str]:
    return {name: semantic_sha256(_load(formal_root / name, name)) for name in CORE_ARTIFACTS}


def _trusted_raw_output(
    run_root: Path, contract: Mapping[str, Any], output_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    raw_name = str(contract["raw_output_path"])
    pure = PurePosixPath(raw_name)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in raw_name
        or not re.fullmatch(r"[A-Za-z0-9._/-]+\.json", raw_name)
    ):
        raise FormalResultVerificationError("派生合同 raw_output_path 不是安全 POSIX 相对路径")
    output_root = (run_root / "workspace" / "output").resolve()
    raw_path = output_root.joinpath(*pure.parts).resolve()
    try:
        raw_path.relative_to(output_root)
    except ValueError as exc:
        raise FormalResultVerificationError("派生合同 raw_output_path 越出 output") from exc
    entries = {
        str(item.get("path")): item
        for item in output_manifest.get("files", [])
        if isinstance(item, Mapping)
    }
    entry = entries.get(raw_name)
    if entry is None:
        raise FormalResultVerificationError("派生 raw output 不属于 Run Output Manifest")
    if entry.get("sha256") != file_sha256(raw_path):
        raise FormalResultVerificationError("派生 raw output SHA 与 Run Output Manifest 不一致")
    return _load(raw_path, "Sandbox raw output")


def verify_formal_result_derivation(
    run_root: Path, formal_result_id: str
) -> dict[str, Any]:
    formal_root = run_root / "formal_results" / formal_result_id
    payload_path = run_root / PAYLOAD_MANIFEST_FILENAME
    derivation_path = run_root / DERIVATION_ATTESTATION_FILENAME
    output_manifest_path = run_root / "run_output_manifest.json"
    payload = _load(payload_path, PAYLOAD_MANIFEST_FILENAME)
    derivation = _load(derivation_path, DERIVATION_ATTESTATION_FILENAME)
    validate_schema(payload, "formal_result_payload_manifest.schema.json", PAYLOAD_MANIFEST_FILENAME)
    validate_schema(
        derivation,
        "collector_derivation_attestation.schema.json",
        DERIVATION_ATTESTATION_FILENAME,
    )
    expected_identity = {
        "run_id": _load(run_root / "run_manifest.json", "run_manifest.json")["run_id"],
        "formal_result_id": formal_result_id,
    }
    for field, expected in expected_identity.items():
        if payload[field] != expected or derivation[field] != expected:
            raise FormalResultVerificationError(f"Formal Result 派生身份不匹配：{field}")
    if payload["execution_id"] != derivation["execution_id"]:
        raise FormalResultVerificationError("Formal Result 派生 execution_id 不匹配")
    output_manifest = _load(output_manifest_path, "run_output_manifest.json")
    output_sha = file_sha256(output_manifest_path)
    if payload["run_output_manifest_sha256"] != output_sha or derivation[
        "run_output_manifest_sha256"
    ] != output_sha:
        raise FormalResultVerificationError("Formal Result 派生未绑定 Run Output Manifest")
    hashes = core_semantic_hashes(formal_root)
    core_digest = semantic_sha256(hashes)
    for document in (payload, derivation):
        if document["formal_core_semantic_sha256"] != hashes:
            raise FormalResultVerificationError("Formal Result core 语义哈希与派生证明不一致")
        if document["formal_result_core_digest"] != core_digest:
            raise FormalResultVerificationError("Formal Result core digest 不匹配")
    if payload["collector_derivation_attestation_sha256"] != file_sha256(derivation_path):
        raise FormalResultVerificationError("Payload Manifest 未绑定 Collector Derivation Attestation")
    if derivation["collector_id"] != COLLECTOR_ID:
        raise FormalResultVerificationError("Collector ID 未被 M3A 策略批准")
    if derivation["collector_script_path"] != COLLECTOR_SCRIPT_PATH:
        raise FormalResultVerificationError("Collector 脚本路径未被 M3A 策略批准")
    source_commit = str(derivation["collector_source_commit"])
    expected_script_sha = collector_script_sha256_at_commit(
        source_commit, str(derivation["collector_script_path"])
    )
    if derivation["collector_script_sha256"] != expected_script_sha:
        raise FormalResultVerificationError("Collector 脚本 SHA 与 source commit 不一致")
    contract_id = str(derivation["derivation_contract_id"])
    trusted_contract = trusted_derivation_contract(contract_id)
    if derivation["derivation_contract_sha256"] != derivation_contract_sha256():
        raise FormalResultVerificationError("派生合同 SHA 未绑定受信合同")
    if derivation["domain_policy_sha256"] != domain_policy_sha256():
        raise FormalResultVerificationError("Domain policy SHA 未绑定受信策略")
    contract = payload["result_derivation_contract"]
    if derivation["result_derivation_contract"] != contract:
        raise FormalResultVerificationError("Collector 与 Payload 的派生合同不一致")
    if contract != trusted_contract:
        raise FormalResultVerificationError("产物自带派生合同不等于受信工程合同")
    raw = _trusted_raw_output(run_root, contract, output_manifest)
    if raw.get("solver_status") not in TRUSTED_DOMAIN_POLICY["allowed_solver_statuses"]:
        raise FormalResultVerificationError("raw output solver_status 未被 Domain policy 批准")
    if raw.get("negative_tests_status") != TRUSTED_DOMAIN_POLICY[
        "required_negative_test_status"
    ]:
        raise FormalResultVerificationError("raw output 未证明负控整体通过")
    negative_tests = raw.get("negative_tests")
    if not isinstance(negative_tests, list) or [
        item.get("test_id") for item in negative_tests if isinstance(item, Mapping)
    ] != TRUSTED_DOMAIN_POLICY["required_negative_tests"] or any(
        not isinstance(item, Mapping)
        or item.get("status") != TRUSTED_DOMAIN_POLICY["required_negative_test_status"]
        for item in negative_tests
    ):
        raise FormalResultVerificationError("raw output 未按固定 Domain policy 提供负控证据")
    core_values = {name: _load(formal_root / name, name) for name in CORE_ARTIFACTS}
    for mapping in contract["mappings"]:
        source = _pointer(raw, mapping["source_pointer"], "Sandbox raw output")
        target = _pointer(
            core_values[mapping["target_artifact"]],
            mapping["target_pointer"],
            mapping["target_artifact"],
        )
        if source != target:
            raise FormalResultVerificationError(
                "Sandbox raw output 与 Formal Result 不一致："
                f"{mapping['source_pointer']} != {mapping['target_artifact']}#{mapping['target_pointer']}"
            )
    return {
        "payload_manifest_sha256": file_sha256(payload_path),
        "payload_manifest_semantic_sha256": semantic_sha256(payload),
        "collector_derivation_attestation_sha256": file_sha256(derivation_path),
        "collector_derivation_attestation_semantic_sha256": semantic_sha256(derivation),
        "formal_result_core_digest": core_digest,
        "execution_id": payload["execution_id"],
        "collector_source_commit": derivation["collector_source_commit"],
    }
