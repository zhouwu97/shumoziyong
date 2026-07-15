"""M3A 受信 Collector 与唯一派生合同策略。"""

from __future__ import annotations

import hashlib
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonicalization import canonical_bytes
from .errors import FormalResultVerificationError


COLLECTOR_ID = "m3a-json-pointer-collector-v1"
COLLECTOR_SCRIPT_PATH = "scripts/run_in_verified_sandbox.py"
DERIVATION_CONTRACT_ID = "m3a-engineering-objective-v1"
RGV_2018B_DERIVATION_CONTRACT_ID = "m3a-2018b-rgv-heuristic-v1"

TRUSTED_DERIVATION_CONTRACT: dict[str, Any] = {
    "contract_version": "1.0.0",
    "raw_output_path": "result.json",
    "mappings": [
        {
            "source_pointer": "/objective",
            "target_artifact": "decision_variables.json",
            "target_pointer": "/payload/x",
        },
        {
            "source_pointer": "/objective",
            "target_artifact": "optimization_validation.json",
            "target_pointer": "/payload/metrics/objective",
        },
        {
            "source_pointer": "/solver_status",
            "target_artifact": "optimality_certificate.json",
            "target_pointer": "/status",
        },
        {
            "source_pointer": "/solver_status",
            "target_artifact": "optimality_certificate.json",
            "target_pointer": "/payload/solver_status",
        },
        {
            "source_pointer": "/negative_tests_status",
            "target_artifact": "negative_tests.json",
            "target_pointer": "/status",
        },
        {
            "source_pointer": "/negative_tests/0/test_id",
            "target_artifact": "negative_tests.json",
            "target_pointer": "/payload/results/0/test_id",
        },
        {
            "source_pointer": "/negative_tests/0/status",
            "target_artifact": "negative_tests.json",
            "target_pointer": "/payload/results/0/status",
        },
        {
            "source_pointer": "/negative_tests/1/test_id",
            "target_artifact": "negative_tests.json",
            "target_pointer": "/payload/results/1/test_id",
        },
        {
            "source_pointer": "/negative_tests/1/status",
            "target_artifact": "negative_tests.json",
            "target_pointer": "/payload/results/1/status",
        },
    ],
}

TRUSTED_DOMAIN_POLICY: dict[str, Any] = {
    "policy_version": "1.0.0",
    "profile": "engineering_optimization",
    "objective_source_pointer": "/objective",
    "solver_status_source_pointer": "/solver_status",
    "allowed_solver_statuses": ["feasible", "optimal"],
    "negative_tests_status_source_pointer": "/negative_tests_status",
    "required_negative_tests": ["missing-input", "tampered-output"],
    "required_negative_test_status": "passed",
}

RGV_2018B_DERIVATION_CONTRACT: dict[str, Any] = {
    "contract_version": "1.0.0",
    "raw_output_path": "result.json",
    "mappings": [
        {
            "source_pointer": "/scenario_decisions",
            "target_artifact": "decision_variables.json",
            "target_pointer": "/payload/scenario_decisions",
        },
        {
            "source_pointer": "/policy_scope",
            "target_artifact": "decision_variables.json",
            "target_pointer": "/payload/policy_scope",
        },
        {
            "source_pointer": "/validation_metrics",
            "target_artifact": "optimization_validation.json",
            "target_pointer": "/payload/metrics",
        },
        {
            "source_pointer": "/invariant_checks",
            "target_artifact": "optimization_validation.json",
            "target_pointer": "/payload/invariant_checks",
        },
        {
            "source_pointer": "/solver_status",
            "target_artifact": "optimality_certificate.json",
            "target_pointer": "/status",
        },
        {
            "source_pointer": "/solver_status",
            "target_artifact": "optimality_certificate.json",
            "target_pointer": "/payload/solver_status",
        },
        {
            "source_pointer": "/claim_scope",
            "target_artifact": "optimality_certificate.json",
            "target_pointer": "/payload/claim_scope",
        },
        {
            "source_pointer": "/negative_tests_status",
            "target_artifact": "negative_tests.json",
            "target_pointer": "/status",
        },
        {
            "source_pointer": "/negative_tests",
            "target_artifact": "negative_tests.json",
            "target_pointer": "/payload/results",
        },
    ],
}

RGV_2018B_DOMAIN_POLICY: dict[str, Any] = {
    "policy_version": "1.0.0",
    "profile": "engineering_optimization",
    "solver_status_source_pointer": "/solver_status",
    "allowed_solver_statuses": ["feasible"],
    "negative_tests_status_source_pointer": "/negative_tests_status",
    "required_negative_tests": [
        "constraint-self-check",
        "finite-policy-scope",
        "random-atomic-evidence",
    ],
    "required_negative_test_status": "passed",
}

TRUSTED_DERIVATION_CONTRACTS = {
    DERIVATION_CONTRACT_ID: TRUSTED_DERIVATION_CONTRACT,
    RGV_2018B_DERIVATION_CONTRACT_ID: RGV_2018B_DERIVATION_CONTRACT,
}

TRUSTED_DOMAIN_POLICIES = {
    DERIVATION_CONTRACT_ID: TRUSTED_DOMAIN_POLICY,
    RGV_2018B_DERIVATION_CONTRACT_ID: RGV_2018B_DOMAIN_POLICY,
}


def trusted_derivation_contract(contract_id: str) -> dict[str, Any]:
    """按受信 ID 返回合同副本，未知 ID 必须失败关闭。"""
    if contract_id not in TRUSTED_DERIVATION_CONTRACTS:
        raise FormalResultVerificationError(f"未批准的派生合同 ID：{contract_id}")
    return deepcopy(TRUSTED_DERIVATION_CONTRACTS[contract_id])


def trusted_domain_policy(contract_id: str) -> dict[str, Any]:
    """返回与派生合同成对冻结的领域策略。"""

    if contract_id not in TRUSTED_DOMAIN_POLICIES:
        raise FormalResultVerificationError(f"未批准的领域策略合同 ID：{contract_id}")
    return deepcopy(TRUSTED_DOMAIN_POLICIES[contract_id])


def derivation_contract_sha256(contract_id: str = DERIVATION_CONTRACT_ID) -> str:
    return hashlib.sha256(canonical_bytes(trusted_derivation_contract(contract_id))).hexdigest()


def domain_policy_sha256(contract_id: str = DERIVATION_CONTRACT_ID) -> str:
    return hashlib.sha256(canonical_bytes(trusted_domain_policy(contract_id))).hexdigest()


def collector_script_at_commit(source_commit: str, script_path: str) -> bytes:
    """从 Git 对象库读取 Collector；不接受工作树内容代替受信来源。"""
    if script_path != COLLECTOR_SCRIPT_PATH:
        raise FormalResultVerificationError(f"未批准的 Collector 路径：{script_path}")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "show", f"{source_commit}:{script_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise FormalResultVerificationError("无法从 collector_source_commit 读取受信 Collector")
    return result.stdout


def collector_script_sha256_at_commit(source_commit: str, script_path: str) -> str:
    return hashlib.sha256(collector_script_at_commit(source_commit, script_path)).hexdigest()


def bound_collector_source_commit() -> tuple[str, str]:
    """只允许已提交且与当前执行脚本逐字节一致的 Collector 生成证明。"""
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    source_commit = commit.stdout.strip()
    if commit.returncode != 0 or len(source_commit) != 40:
        raise RuntimeError("无法确定 Collector source commit")
    committed = collector_script_at_commit(source_commit, COLLECTOR_SCRIPT_PATH)
    working = (root / COLLECTOR_SCRIPT_PATH).read_bytes()
    if committed != working:
        raise RuntimeError("Collector 脚本存在未提交漂移，拒绝生成机器证明")
    return source_commit, hashlib.sha256(committed).hexdigest()
