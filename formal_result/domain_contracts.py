"""Formal Result 领域合同注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import FormalResultVerificationError


COMMON_PROVENANCE_PATHS = (
    "formal_result_manifest.json",
    "collector_attestation.json",
    "negative_tests.json",
    "input_manifest.json",
    "code_manifest.json",
    "environment_manifest.json",
    "logs/stdout.log",
    "logs/stderr.log",
)


@dataclass(frozen=True)
class DomainContract:
    """一个领域专属且精确的 Formal Result 文件合同。"""

    domain: str
    profile: str
    manifest_schema: str
    core_artifacts: tuple[str, ...]
    output_file_set: tuple[str, ...]
    expected_artifacts: Mapping[str, tuple[str, frozenset[str]]]
    chain_bindings: Mapping[str, str]

    @property
    def required_artifacts(self) -> tuple[str, ...]:
        ordered = ["formal_result_manifest.json", *self.core_artifacts]
        ordered.extend(COMMON_PROVENANCE_PATHS[1:])
        return tuple(ordered)


ENGINEERING_OPTIMIZATION_CONTRACT = DomainContract(
    domain="engineering_optimization",
    profile="engineering_optimization",
    manifest_schema="domain_manifest.schema.json",
    core_artifacts=(
        "decision_variables.json",
        "optimization_validation.json",
        "optimality_certificate.json",
    ),
    output_file_set=(
        "decision_variables.json",
        "optimization_validation.json",
        "optimality_certificate.json",
    ),
    expected_artifacts={
        "decision_variables.json": ("decision_variables", frozenset({"feasible", "optimal"})),
        "optimization_validation.json": ("optimization_validation", frozenset({"passed"})),
        "optimality_certificate.json": ("optimality_certificate", frozenset({"feasible", "optimal"})),
        "negative_tests.json": ("negative_tests", frozenset({"passed"})),
    },
    chain_bindings={
        "decision_variables.json": "execution_spec.json",
        "optimization_validation.json": "decision_variables.json",
        "optimality_certificate.json": "optimization_validation.json",
        "negative_tests.json": "execution_spec.json",
    },
)


PREDICTION_CONTRACT = DomainContract(
    domain="predictive_modeling",
    profile="prediction",
    manifest_schema="prediction_domain_manifest.schema.json",
    core_artifacts=(
        "prediction_result.json",
        "prediction_validation.json",
        "prediction_reproducibility_certificate.json",
    ),
    output_file_set=(
        "prediction_result.json",
        "prediction_validation.json",
        "prediction_reproducibility_certificate.json",
    ),
    expected_artifacts={
        "prediction_result.json": (
            "prediction_result",
            frozenset({"execution_pending", "collected"}),
        ),
        "prediction_validation.json": (
            "prediction_validation",
            frozenset({"execution_pending", "passed"}),
        ),
        "prediction_reproducibility_certificate.json": (
            "prediction_reproducibility_certificate",
            frozenset({"execution_pending", "passed"}),
        ),
        "negative_tests.json": (
            "negative_tests",
            frozenset({"execution_pending", "passed"}),
        ),
    },
    chain_bindings={
        "prediction_result.json": "execution_spec.json",
        "prediction_validation.json": "prediction_result.json",
        "prediction_reproducibility_certificate.json": "prediction_validation.json",
        "negative_tests.json": "execution_spec.json",
    },
)


DOMAIN_CONTRACTS = {
    (contract.domain, contract.profile): contract
    for contract in (ENGINEERING_OPTIMIZATION_CONTRACT, PREDICTION_CONTRACT)
}


def domain_contract_for_manifest(domain: Mapping[str, Any]) -> DomainContract:
    """按领域和 Profile 精确选择合同，未知组合失败关闭。"""
    key = (str(domain.get("domain")), str(domain.get("profile")))
    contract = DOMAIN_CONTRACTS.get(key)
    if contract is None:
        raise FormalResultVerificationError(
            f"未注册的 Formal Result 领域合同：domain={key[0]!r}, profile={key[1]!r}"
        )
    return contract
