"""测试专用的最小 required_v1 正式结果 Bundle 构造器。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from formal_result.hashing import file_sha256, semantic_sha256


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_formal_result_bundle(run_dir: Path, formal_result_id: str = "formal-test-001") -> Path:
    run = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    identity = {
        field: run[field]
        for field in (
            "run_id", "problem_id", "profile", "runtime_version", "runtime_pack_sha256",
            "formal_result_policy", "execution_contract_version", "formal_result_contract_version",
            "canonicalization_version", "gate_artifact_contract_version",
        )
    }
    input_path = run_dir / "problem" / "input.txt"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text("formal input\n", encoding="utf-8")
    execution_spec = {
        "schema_version": "1.0.0", "artifact_type": "execution_spec", **identity,
        "execution_mode": "trusted_local", "declared_workspace": "workspace", "network_access": False,
        "declared_writable_paths": ["workspace/output"], "approved_by": "test-reviewer",
        "approved_at": "2026-07-12T10:00:00Z",
        "tasks": [{
            "task_id": "FORMAL_TEST", "runner": "python", "entrypoint": "code/solve.py",
            "entrypoint_arg_index": 1,
            "argv": ["python", "code/solve.py"], "working_directory": "workspace",
            "inputs": [{"path": "problem/input.txt", "sha256": file_sha256(input_path)}],
            "required_outputs": [{"path": "workspace/output/result.json", "media_type": "application/json"}],
            "depends_on": [], "timeout_seconds": 60,
            "seed_policy": {"deterministic_expected": True, "seeds": [0]},
            "acceptance_checks": [{"check_id": "result", "kind": "file_exists", "expectation": "result exists"}],
            "fallback": "emit_blocker"
        }]
    }
    _write_json(run_dir / "execution_spec.json", execution_spec)
    code_path = run_dir / "workspace" / "code" / "solve.py"
    code_path.parent.mkdir(parents=True, exist_ok=True)
    code_path.write_text("print('formal test')\n", encoding="utf-8")

    formal = run_dir / "formal_results" / formal_result_id
    (formal / "logs").mkdir(parents=True)
    (formal / "logs" / "stdout.log").write_text("formal test output\n", encoding="utf-8")
    (formal / "logs" / "stderr.log").write_text("", encoding="utf-8")
    common = {"schema_version": "1.0.0", **identity, "formal_result_id": formal_result_id}
    execution_semantic = semantic_sha256(execution_spec)
    decision_value = {
        **common, "artifact_type": "decision_variables", "status": "feasible",
        "bindings": {"execution_spec.json": execution_semantic}, "payload": {"x": 1},
    }
    validation_value = {
        **common, "artifact_type": "optimization_validation", "status": "passed",
        "bindings": {"decision_variables.json": semantic_sha256(decision_value)},
        "payload": {
            "metrics": {"objective": 1.0},
            "invariant_checks": {"capacity": {"status": "passed", "value": 0.0}},
        },
    }
    core_values = {
        "decision_variables.json": decision_value,
        "optimization_validation.json": validation_value,
        "optimality_certificate.json": {
            **common, "artifact_type": "optimality_certificate", "status": "optimal",
            "bindings": {"optimization_validation.json": semantic_sha256(validation_value)},
            "payload": {"solver_status": "optimal"},
        },
        "negative_tests.json": {
            **common, "artifact_type": "negative_tests", "status": "passed",
            "bindings": {"execution_spec.json": execution_semantic},
            "payload": {
                "results": [
                    {"test_id": "missing-input", "status": "passed"},
                    {"test_id": "tampered-output", "status": "passed"},
                ]
            },
        },
    }
    for name, value in core_values.items():
        _write_json(formal / name, value)
    provenance_values = {
        "input_manifest.json": {
            **common,
            "artifact_type": "input_manifest",
            "bindings": {"execution_spec.json": execution_semantic},
            "payload": {
                "inputs": [{
                    "task_id": "FORMAL_TEST",
                    "path": "problem/input.txt",
                    "sha256": file_sha256(input_path),
                }]
            },
        },
        "code_manifest.json": {
            **common,
            "artifact_type": "code_manifest",
            "bindings": {"execution_spec.json": execution_semantic},
            "payload": {
                "files": [
                    {"path": "workspace/code/solve.py", "sha256": file_sha256(code_path)}
                ]
            },
        },
        "environment_manifest.json": {
            **common,
            "artifact_type": "environment_manifest",
            "bindings": {"execution_spec.json": execution_semantic},
            "payload": {
                "formal_result_activation_status": "code_complete_candidate",
                "formal_result_eligible": False,
            },
        },
    }
    for name, value in provenance_values.items():
        _write_json(formal / name, value)
    attestation = {
        **common, "artifact_type": "collector_attestation", "collector_id": "test-collector",
        "collector_version": "1.0.0", "source_commit": "abcdef0",
        "input_manifest_sha256": file_sha256(formal / "input_manifest.json"),
        "code_manifest_sha256": file_sha256(formal / "code_manifest.json"),
        "execution_spec_sha256": file_sha256(run_dir / "execution_spec.json"),
        "environment_manifest_sha256": file_sha256(formal / "environment_manifest.json"),
        "sandbox_policy": "manifest-only-test",
        "candidate_access_assurance": "manifest_isolation", "candidate_output_access_not_detected": True,
        "started_at": "2026-07-12T10:00:00Z", "completed_at": "2026-07-12T10:00:01Z", "exit_code": 0,
        "stdout_sha256": file_sha256(formal / "logs" / "stdout.log"),
        "stderr_sha256": file_sha256(formal / "logs" / "stderr.log"),
        "output_file_set": [
            "decision_variables.json",
            "optimization_validation.json",
            "optimality_certificate.json",
        ],
        "undeclared_write_check": "passed",
        "negative_test_report_sha256": file_sha256(formal / "negative_tests.json"),
    }
    _write_json(formal / "collector_attestation.json", attestation)

    bound_names = [
        "decision_variables.json", "optimization_validation.json", "optimality_certificate.json",
        "collector_attestation.json", "negative_tests.json", "input_manifest.json",
        "code_manifest.json", "environment_manifest.json",
    ]
    bound_semantic = {
        name: semantic_sha256(json.loads((formal / name).read_text(encoding="utf-8")))
        for name in bound_names
    }
    formal_manifest = {
        **common, "artifact_type": "formal_result_manifest", "validation_status": "passed",
        "semantic_hashes": bound_semantic,
    }
    _write_json(formal / "formal_result_manifest.json", formal_manifest)

    descriptors: list[dict[str, Any]] = []
    json_names = ["formal_result_manifest.json", *bound_names]
    for name in json_names:
        value = json.loads((formal / name).read_text(encoding="utf-8"))
        descriptors.append({
            "path": name, "media_type": "application/json", "file_sha256": file_sha256(formal / name),
            "semantic_sha256": semantic_sha256(value),
            "schema": "formal_result_bundle_manifest.schema.json" if name == "formal_result_manifest.json"
            else "collector_attestation.schema.json" if name == "collector_attestation.json"
            else "formal_result_decision_variables.schema.json" if name == "decision_variables.json"
            else "formal_result_provenance_manifest.schema.json" if name in provenance_values
            else "formal_result_core_artifact.schema.json",
        })
    for name in ("logs/stdout.log", "logs/stderr.log"):
        descriptors.append({"path": name, "media_type": "text/plain", "file_sha256": file_sha256(formal / name)})
    semantic_hashes = {item["path"]: item["semantic_sha256"] for item in descriptors if "semantic_sha256" in item}
    domain = {
        **common, "artifact_type": "domain_manifest", "domain": "engineering_optimization", "mechanism": "mip",
        "validator_id": "test-validator", "validator_version": "1.0.0", "required_artifacts": descriptors,
        "required_certificates": ["optimality_certificate.json"],
        "decision_schema": "formal_result_decision_variables.schema.json",
        "metric_schema": {"objective": "number"},
        "invariant_checks": ["capacity"], "optimality_claim_level": "optimal",
        "negative_test_requirements": ["missing-input", "tampered-output"],
        "output_file_set": [
            "decision_variables.json",
            "optimization_validation.json",
            "optimality_certificate.json",
        ],
        "semantic_hashes": semantic_hashes,
    }
    _write_json(formal / "domain_manifest.json", domain)
    envelope = {
        **common, "artifact_type": "formal_result_envelope",
        "execution_spec_file_sha256": file_sha256(run_dir / "execution_spec.json"),
        "execution_spec_semantic_sha256": semantic_sha256(execution_spec),
        "domain_manifest_path": f"formal_results/{formal_result_id}/domain_manifest.json",
        "domain_manifest_file_sha256": file_sha256(formal / "domain_manifest.json"),
        "domain_manifest_semantic_sha256": semantic_sha256(domain),
        "formal_result_manifest_path": f"formal_results/{formal_result_id}/formal_result_manifest.json",
        "formal_result_manifest_file_sha256": file_sha256(formal / "formal_result_manifest.json"),
        "formal_result_manifest_semantic_sha256": semantic_sha256(formal_manifest),
        "collector_attestation_semantic_sha256": semantic_sha256(attestation), "created_by": "trusted_collector",
    }
    _write_json(formal / "formal_result_envelope.json", envelope)
    return formal / "formal_result_envelope.json"
