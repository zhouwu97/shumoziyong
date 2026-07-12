"""正式结果的不可变运行身份。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import FormalResultVerificationError


FORMAL_RESULT_POLICY_REQUIRED = "required_v1"
FORMAL_RESULT_POLICY_LEGACY = "legacy_read_only_v1"
CONTRACT_VERSION = "1.0.0"
IMMUTABLE_IDENTITY_FIELDS = (
    "run_id",
    "problem_id",
    "profile",
    "runtime_version",
    "runtime_pack_sha256",
    "formal_result_policy",
    "execution_contract_version",
    "formal_result_contract_version",
    "canonicalization_version",
    "gate_artifact_contract_version",
)


def immutable_identity(manifest: Mapping[str, Any]) -> dict[str, str]:
    identity: dict[str, str] = {}
    for field in IMMUTABLE_IDENTITY_FIELDS:
        value = manifest.get(field)
        if not isinstance(value, str) or not value:
            raise FormalResultVerificationError(f"run_manifest.{field} 缺失或非法")
        identity[field] = value
    return identity


def assert_identity(actual: Mapping[str, Any], expected: Mapping[str, str], label: str) -> None:
    for field, expected_value in expected.items():
        if actual.get(field) != expected_value:
            raise FormalResultVerificationError(f"{label}.{field} 与当前 Run 不可变身份不一致")
