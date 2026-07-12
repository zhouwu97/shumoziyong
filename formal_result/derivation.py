"""Sandbox raw output 到 Formal Result core 的可执行派生合同。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

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
    contract = payload["result_derivation_contract"]
    if derivation["result_derivation_contract"] != contract:
        raise FormalResultVerificationError("Collector 与 Payload 的派生合同不一致")
    raw_path = run_root / "workspace" / "output" / str(contract["raw_output_path"])
    raw = _load(raw_path, "Sandbox raw output")
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
    }
