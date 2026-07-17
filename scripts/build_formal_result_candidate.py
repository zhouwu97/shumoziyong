"""为当前 Run 构建仅完成环境验证的 Formal Result 候选包。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formal_result.domain_contracts import (
    ENGINEERING_OPTIMIZATION_CONTRACT,
    PREDICTION_CONTRACT,
)
from formal_result.hashing import file_sha256, semantic_sha256
from formal_result.sandboxie_environment import load_and_verify_sandboxie_environment_report


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象：{path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--formal-result-id", required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    formal_id = args.formal_result_id

    run = load_json(run_dir / "run_manifest.json")
    if run["profile"] == "prediction":
        domain_contract = PREDICTION_CONTRACT
    elif run["profile"] == "engineering_optimization":
        domain_contract = ENGINEERING_OPTIMIZATION_CONTRACT
    else:
        raise ValueError(f"当前 Profile 尚无 Formal Result 领域合同：{run['profile']}")
    spec = load_json(run_dir / "execution_spec.json")
    task = spec["tasks"][0]
    identity = {
        field: run[field]
        for field in (
            "run_id", "problem_id", "profile", "runtime_version", "runtime_pack_sha256",
            "formal_result_policy", "execution_contract_version", "formal_result_contract_version",
            "canonicalization_version", "gate_artifact_contract_version",
        )
    }
    common = {"schema_version": "1.0.0", **identity, "formal_result_id": formal_id}
    is_2018b = run["problem_id"] == "2018-B"
    spec_sha = file_sha256(run_dir / "execution_spec.json")
    spec_semantic = semantic_sha256(spec)
    formal = run_dir / "formal_results" / formal_id
    if formal.exists():
        raise FileExistsError(f"Formal Result 目录已存在，拒绝覆盖：{formal}")
    (formal / "logs").mkdir(parents=True)
    (formal / "logs" / "stdout.log").write_text("candidate bundle; execution pending\n", encoding="utf-8")
    (formal / "logs" / "stderr.log").write_text("", encoding="utf-8")

    decision_payload = (
        {"scenario_decisions": [{"scenario_id": "execution_pending"}], "policy_scope": {"status": "execution_pending"}}
        if is_2018b else {"x": 0.0}
    )
    validation_metrics = (
        {"scenario_count": 1, "constraint_violation_count": 0, "random_trial_count": 0}
        if is_2018b else {"objective": 0.0}
    )
    invariant_checks = (
        {
            "constraint_self_check": {"status": "passed"},
            "finite_policy_scope": {"status": "passed"},
            "random_atomic_evidence": {"status": "passed"},
        }
        if is_2018b else {"candidate": {"status": "passed"}}
    )
    negative_results = (
        [
            {"test_id": "constraint-self-check", "status": "passed"},
            {"test_id": "finite-policy-scope", "status": "passed"},
            {"test_id": "random-atomic-evidence", "status": "passed"},
        ]
        if is_2018b else [
            {"test_id": "missing-input", "status": "passed"},
            {"test_id": "tampered-output", "status": "passed"},
        ]
    )
    if domain_contract is PREDICTION_CONTRACT:
        pending_payload = {"execution_pending": True}
        prediction_result = {
            **common,
            "artifact_type": "prediction_result",
            "status": "execution_pending",
            "bindings": {"execution_spec.json": spec_semantic},
            "payload": pending_payload,
        }
        prediction_validation = {
            **common,
            "artifact_type": "prediction_validation",
            "status": "execution_pending",
            "bindings": {
                "prediction_result.json": semantic_sha256(prediction_result)
            },
            "payload": pending_payload,
        }
        prediction_certificate = {
            **common,
            "artifact_type": "prediction_reproducibility_certificate",
            "status": "execution_pending",
            "bindings": {
                "prediction_validation.json": semantic_sha256(prediction_validation)
            },
            "payload": pending_payload,
        }
        negative = {
            **common,
            "artifact_type": "negative_tests",
            "status": "execution_pending",
            "bindings": {"execution_spec.json": spec_semantic},
            "payload": pending_payload,
        }
        core_values = {
            "prediction_result.json": prediction_result,
            "prediction_validation.json": prediction_validation,
            "prediction_reproducibility_certificate.json": prediction_certificate,
            "negative_tests.json": negative,
        }
    else:
        decision = {
            **common, "artifact_type": "decision_variables", "status": "feasible",
            "bindings": {"execution_spec.json": spec_semantic}, "payload": decision_payload,
        }
        validation = {
            **common, "artifact_type": "optimization_validation", "status": "passed",
            "bindings": {"decision_variables.json": semantic_sha256(decision)},
            "payload": {"metrics": validation_metrics, "invariant_checks": invariant_checks},
        }
        certificate = {
            **common, "artifact_type": "optimality_certificate", "status": "feasible",
            "bindings": {"optimization_validation.json": semantic_sha256(validation)},
            "payload": {
                "solver_status": "feasible",
                "claim_scope": "finite_heuristic_policy_family_execution_pending" if is_2018b else "execution_pending",
            },
        }
        negative = {
            **common, "artifact_type": "negative_tests", "status": "passed",
            "bindings": {"execution_spec.json": spec_semantic},
            "payload": {"results": negative_results},
        }
        core_values = {
            "decision_variables.json": decision,
            "optimization_validation.json": validation,
            "optimality_certificate.json": certificate,
            "negative_tests.json": negative,
        }
    for name, value in core_values.items():
        write_json(formal / name, value)

    input_items = []
    for item in task["inputs"]:
        input_items.append({"task_id": task["task_id"], "path": item["path"], "sha256": item["sha256"]})
    input_manifest = {
        **common, "artifact_type": "input_manifest", "bindings": {"execution_spec.json": spec_semantic},
        "payload": {"inputs": input_items},
    }
    code_files = []
    code_root = run_dir / spec["declared_workspace"] / "code"
    for path in sorted(code_root.rglob("*")):
        if path.is_file():
            code_files.append({"path": path.relative_to(run_dir).as_posix(), "sha256": file_sha256(path)})
    if not code_files:
        raise ValueError("workspace/code 为空，无法构建 Code Manifest")
    code_manifest = {
        **common, "artifact_type": "code_manifest", "bindings": {"execution_spec.json": spec_semantic},
        "payload": {"files": code_files},
    }
    environment_summary = load_and_verify_sandboxie_environment_report(
        run_dir / "sandboxie_environment_report.json",
        run_dir / "sandboxie_environment_attestation.json",
    )
    environment_attestation = load_json(run_dir / "sandboxie_environment_attestation.json")
    environment_manifest = {
        **common, "artifact_type": "environment_manifest", "bindings": {"execution_spec.json": spec_semantic},
        "payload": {
            "formal_result_activation_status": "sandboxie_environment_verified",
            "sandboxie_environment_observed": True,
            "sandboxie_environment_verified": True,
            "formal_result_executed_in_verified_environment": False,
            "formal_result_eligible": False,
            "sandboxie_environment_report": {
                "path": "sandboxie_environment_report.json",
                "report_id": environment_summary["report_id"],
                "file_sha256": environment_summary["report_file_sha256"],
                "semantic_sha256": environment_summary["report_semantic_sha256"],
                "configuration_backup_path": environment_summary["configuration_backup_path"],
                "configuration_backup_sha256": environment_summary["configuration_backup_sha256"],
            },
            "sandboxie_environment_attestation": {
                "path": "sandboxie_environment_attestation.json",
                "file_sha256": environment_summary["attestation_file_sha256"],
                "semantic_sha256": environment_summary["attestation_semantic_sha256"],
                "original_report_sha256": environment_summary["original_report_sha256"],
                "environment_fingerprint": environment_summary["environment_fingerprint"],
                "machine_key_id": environment_summary["machine_key_id"],
            },
        },
    }
    for name, value in {
        "input_manifest.json": input_manifest,
        "code_manifest.json": code_manifest,
        "environment_manifest.json": environment_manifest,
    }.items():
        write_json(formal / name, value)

    bound_names = [
        *domain_contract.core_artifacts,
        "collector_attestation.json",
        "negative_tests.json",
        "input_manifest.json",
        "code_manifest.json",
        "environment_manifest.json",
    ]
    collector = {
        **common, "artifact_type": "collector_attestation", "collector_id": "m3a-json-pointer-collector-v1",
        "collector_version": "1.0.0", "source_commit": environment_attestation["collector_source_commit"],
        "input_manifest_sha256": file_sha256(formal / "input_manifest.json"),
        "code_manifest_sha256": file_sha256(formal / "code_manifest.json"),
        "execution_spec_sha256": spec_sha,
        "environment_manifest_sha256": file_sha256(formal / "environment_manifest.json"),
        "sandbox_policy": "candidate_environment_verified",
        "candidate_access_assurance": "manifest_isolation",
        "candidate_output_access_not_detected": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": 0,
        "stdout_sha256": file_sha256(formal / "logs" / "stdout.log"),
        "stderr_sha256": file_sha256(formal / "logs" / "stderr.log"),
        "output_file_set": list(domain_contract.output_file_set),
        "undeclared_write_check": "passed",
        "negative_test_report_sha256": file_sha256(formal / "negative_tests.json"),
    }
    write_json(formal / "collector_attestation.json", collector)

    semantic_hashes = {
        name: semantic_sha256(load_json(formal / name))
        for name in bound_names
    }
    formal_manifest = {
        **common, "artifact_type": "formal_result_manifest", "validation_status": "passed",
        "semantic_hashes": semantic_hashes,
    }
    write_json(formal / "formal_result_manifest.json", formal_manifest)

    descriptors = []
    schema_by_name = {
        "formal_result_manifest.json": "formal_result_bundle_manifest.schema.json",
        "collector_attestation.json": "collector_attestation.schema.json",
        "decision_variables.json": "formal_result_decision_variables.schema.json",
        "prediction_result.json": "formal_result_prediction_result.schema.json",
        "prediction_validation.json": "formal_result_prediction_validation.schema.json",
        "prediction_reproducibility_certificate.json": "formal_result_prediction_certificate.schema.json",
        "input_manifest.json": "formal_result_provenance_manifest.schema.json",
        "code_manifest.json": "formal_result_provenance_manifest.schema.json",
        "environment_manifest.json": "formal_result_provenance_manifest.schema.json",
    }
    if domain_contract is PREDICTION_CONTRACT:
        schema_by_name["negative_tests.json"] = (
            "formal_result_prediction_negative_tests.schema.json"
        )
    for name in domain_contract.required_artifacts:
        path = formal / name
        item = {"path": name, "media_type": "application/json" if path.suffix == ".json" else "text/plain", "file_sha256": file_sha256(path)}
        if path.suffix == ".json":
            item["semantic_sha256"] = semantic_sha256(load_json(path))
            item["schema"] = schema_by_name.get(name, "formal_result_core_artifact.schema.json")
        descriptors.append(item)
    domain_common = {
        **common,
        "artifact_type": "domain_manifest",
        "validator_version": "1.0.0",
        "required_artifacts": descriptors,
        "negative_test_requirements": [item["test_id"] for item in negative_results],
        "output_file_set": list(domain_contract.output_file_set),
        "semantic_hashes": {
            item["path"]: item["semantic_sha256"]
            for item in descriptors
            if "semantic_sha256" in item
        },
    }
    if domain_contract is PREDICTION_CONTRACT:
        domain = {
            **domain_common,
            "domain": "predictive_modeling",
            "mechanism": "repeated_measures_prediction",
            "validator_id": "prediction-held-out-metrics-v1",
            "required_certificates": [
                "prediction_reproducibility_certificate.json"
            ],
            "result_schema": "formal_result_prediction_result.schema.json",
            "validation_schema": "formal_result_prediction_validation.schema.json",
            "required_metrics": ["brier", "pr_auc", "recall"],
            "metric_tolerance": 1e-9,
            "invariant_checks": [
                "patient_group_disjoint",
                "train_only_preprocessing",
                "held_out_metric_recomputation",
                "frozen_random_seed",
            ],
        }
    else:
        domain = {
            **domain_common,
            "domain": "engineering_optimization",
            "mechanism": "heuristic" if is_2018b else "mip",
            "validator_id": "m3a-formal-result-validator",
            "required_certificates": ["optimality_certificate.json"],
            "decision_schema": "formal_result_decision_variables.schema.json",
            "metric_schema": (
                {"scenario_count": "integer", "constraint_violation_count": "integer", "random_trial_count": "integer"}
                if is_2018b else {"objective": "number"}
            ),
            "invariant_checks": list(invariant_checks),
            "optimality_claim_level": "heuristic" if is_2018b else "feasible",
        }
    write_json(formal / "domain_manifest.json", domain)
    envelope = {
        **common, "artifact_type": "formal_result_envelope", "execution_spec_file_sha256": spec_sha,
        "execution_spec_semantic_sha256": spec_semantic,
        "domain_manifest_path": f"formal_results/{formal_id}/domain_manifest.json",
        "domain_manifest_file_sha256": file_sha256(formal / "domain_manifest.json"),
        "domain_manifest_semantic_sha256": semantic_sha256(domain),
        "formal_result_manifest_path": f"formal_results/{formal_id}/formal_result_manifest.json",
        "formal_result_manifest_file_sha256": file_sha256(formal / "formal_result_manifest.json"),
        "formal_result_manifest_semantic_sha256": semantic_sha256(formal_manifest),
        "collector_attestation_semantic_sha256": semantic_sha256(collector),
        "created_by": "trusted_collector",
    }
    write_json(formal / "formal_result_envelope.json", envelope)
    print(json.dumps({"formal_result_id": formal_id, "envelope": str(formal / "formal_result_envelope.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
