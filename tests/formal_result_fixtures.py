"""测试专用的最小 required_v1 正式结果 Bundle 构造器。"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from formal_result.hashing import file_sha256, semantic_sha256
from formal_result.sandboxie_environment import (
    ATTESTATION_FILENAME,
    NEGATIVE_CONTROL_IDS,
    load_and_validate_sandboxie_fixture_report,
    load_and_verify_sandboxie_environment_report,
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_sandboxie_environment_report(directory: Path) -> Path:
    """生成只能用于 Schema/接线测试、永不授予资格的 Fixture 报告。"""
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / "sandboxie_config_backup.txt"
    backup.write_text("[GlobalSettings]\nTemplate=Test\n", encoding="utf-8")
    report_path = directory / "sandboxie_environment_report.json"
    sha = "a" * 64
    components = [
        {
            "role": role,
            "path": rf"C:\\Program Files\\Sandboxie-Plus\\{filename}",
            "file_sha256": sha,
            "size_bytes": 1,
            "file_version": "1.0.0",
            "signature": {
                "status": "Valid",
                "subject": "CN=Sandboxie Test Signer",
                "issuer": "CN=Sandboxie Test Issuer",
                "certificate_thumbprint": "b" * 40,
                "not_before": "2026-07-01T00:00:00Z",
                "not_after": "2027-07-01T00:00:00Z",
                "chain_status": "Valid",
            },
        }
        for role, filename in (
            ("start_exe", "Start.exe"),
            ("service_exe", "SbieSvc.exe"),
            ("driver_sys", "SbieDrv.sys"),
        )
    ]
    controls = [
        {
            "control_id": control_id,
            "status": "passed",
            "expected": "operation denied",
            "observed": "sandbox operation denied as expected",
            "target": "fixture-target",
            "probe_sha256": sha,
            "command_sha256": sha,
            "started_at": "2026-07-12T11:59:00+08:00",
            "completed_at": "2026-07-12T11:59:01+08:00",
            "exit_code": 0,
            "stdout_sha256": sha,
            "stderr_sha256": sha,
        }
        for control_id in sorted(NEGATIVE_CONTROL_IDS)
    ]
    settings = [
        "Enabled=y",
        "AutoDelete=n",
        "DropAdminRights=y",
        "BlockNetworkFiles=y",
        "NotifyInternetAccessDenied=n",
        "ClosedFilePath=C:\\protected",
        "ClosedKeyPath=HKEY_CURRENT_USER\\Software\\Test",
        "ClosedFilePath=\\Device\\Afd*",
        "ClosedFilePath=\\Device\\Tcp*",
        "ClosedFilePath=\\Device\\RawIp",
    ]
    report = {
        "schema_version": "2.0.0",
        "report_kind": "fixture_report",
        "report_id": "sandboxie-env-20260712T120000p0800-test",
        "generated_at": "2026-07-12T12:00:00+08:00",
        "valid_until": "2026-07-13T12:00:00+08:00",
        "probe_started_at": "2026-07-12T11:58:00+08:00",
        "probe_completed_at": "2026-07-12T11:59:30+08:00",
        "verification_status": "passed",
        "sandboxie_environment_verified": False,
        "formal_result_executed_in_verified_environment": False,
        "collector": {
            "tool_id": "verify_sandboxie_environment.py",
            "source_commit": "a" * 40,
            "probe_script_sha256": sha,
            "challenge_nonce": "c" * 64,
            "machine_key_id": "sandboxie-host-0123456789abcdef",
            "environment_fingerprint": sha,
            "redaction_policy_version": "none",
        },
        "platform": {
            "system": "Windows",
            "caption": "Windows Test",
            "version": "10.0.26200",
            "build": "26200",
            "architecture": "x64",
        },
        "installation": {
            "product": "Sandboxie-Plus",
            "product_version": "1.17.9",
            "install_root": "C:\\Program Files\\Sandboxie-Plus",
            "origin": "preexisting",
            "components": components,
            "service": {
                "name": "SbieSvc",
                "state": "Running",
                "start_mode": "Auto",
                "path": "C:\\Program Files\\Sandboxie-Plus\\SbieSvc.exe",
            },
            "driver": {
                "name": "SbieDrv",
                "state": "Running",
                "start_mode": "Manual",
                "path": "C:\\Program Files\\Sandboxie-Plus\\SbieDrv.sys",
            },
        },
        "configuration_backup": {
            "method": "sbieini_export",
            "path": backup.name,
            "file_sha256": file_sha256(backup),
            "size_bytes": backup.stat().st_size,
            "preexisting_sections": ["GlobalSettings"],
        },
        "sandbox": {
            "box_name": "ShumoM2TestBox01",
            "start_exit_code": 0,
            "start_exe_sha256": sha,
            "start_command_sha256": sha,
            "settings": settings,
            "settings_sha256": hashlib.sha256("\n".join(settings).encode()).hexdigest(),
            "sandbox_marker_detected": True,
            "protected_host_state_intact": True,
        },
        "negative_controls": controls,
        "network_probes": {
            "minimum_successful_dns": 2,
            "minimum_successful_tcp": 2,
            "dns": [
                {"endpoint": f"dns-{index}.example", "status": "passed", "latency_ms": 1, "observed": "127.0.0.1"}
                for index in range(3)
            ],
            "tcp": [
                {"endpoint": f"tcp-{index}.example:443", "status": "passed", "latency_ms": 1, "observed": "connected"}
                for index in range(3)
            ],
        },
        "cleanup": {
            "terminate_exit_code": 0,
            "delete_exit_code": 0,
            "box_processes_before": [],
            "box_processes_after": [],
            "sandbox_content_path": "C:\\Sandbox\\test\\ShumoM2TestBox01",
            "sandbox_content_exists_after": False,
            "preexisting_controller_pids": [],
            "new_controller_pids_after": [],
            "processes_terminated": True,
            "new_controller_processes_terminated": True,
            "sandbox_content_deleted": True,
            "box_configuration_removed": True,
            "preexisting_configuration_restored": True,
        },
    }
    _write_json(report_path, report)
    load_and_validate_sandboxie_fixture_report(report_path)
    return report_path


def write_formal_result_bundle(
    run_dir: Path,
    formal_result_id: str = "formal-test-001",
    sandboxie_report: Path | None = None,
) -> Path:
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
            "argv": ["python", "code/solve.py", "--mode", "validated"], "working_directory": "workspace",
            "inputs": [{"path": "problem/input.txt", "sha256": file_sha256(input_path)}],
            "required_outputs": [{"path": "workspace/output/result.json", "media_type": "application/json"}],
            "depends_on": [], "timeout_seconds": 60,
            "seed_policy": {"deterministic_expected": True, "seeds": [0]},
            "acceptance_checks": [{"check_id": "result", "kind": "file_exists", "expectation": "output/result.json"}],
            "fallback": "emit_blocker"
        }]
    }
    _write_json(run_dir / "execution_spec.json", execution_spec)
    code_path = run_dir / "workspace" / "code" / "solve.py"
    code_path.parent.mkdir(parents=True, exist_ok=True)
    code_path.write_text(
        "import argparse\n"
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--mode', required=True, choices=['validated'])\n"
        "args = parser.parse_args()\n"
        "source = Path('input/input.txt')\n"
        "if not source.is_file():\n"
        "    source = Path('../problem/input.txt')\n"
        "Path('output').mkdir(exist_ok=True)\n"
        "Path('output/result.json').write_text(json.dumps({'objective': len(source.read_text(encoding='utf-8'))}) + '\\n', encoding='utf-8')\n"
        "Path('output/execution_challenge.json').write_text(json.dumps({'challenge_nonce': os.environ['SHUMO_EXECUTION_CHALLENGE'], 'run_id': os.environ['SHUMO_RUN_ID'], 'execution_id': os.environ['SHUMO_EXECUTION_ID']}) + '\\n', encoding='utf-8')\n"
        "print('formal test')\n",
        encoding="utf-8",
    )

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
    environment_payload: dict[str, Any] = {
        "formal_result_activation_status": "code_complete_candidate",
        "sandboxie_environment_observed": False,
        "sandboxie_environment_verified": False,
        "formal_result_executed_in_verified_environment": False,
        "formal_result_eligible": False,
    }
    if sandboxie_report is not None:
        target_report = run_dir / "sandboxie_environment_report.json"
        target_attestation = run_dir / ATTESTATION_FILENAME
        target_backup = run_dir / "sandboxie_config_backup.txt"
        if sandboxie_report.resolve() != target_report.resolve():
            report = json.loads(sandboxie_report.read_text(encoding="utf-8"))
            source_backup = sandboxie_report.parent / report["configuration_backup"]["path"]
            source_attestation = sandboxie_report.parent / ATTESTATION_FILENAME
            shutil.copyfile(sandboxie_report, target_report)
            shutil.copyfile(source_attestation, target_attestation)
            shutil.copyfile(source_backup, target_backup)
        summary = load_and_verify_sandboxie_environment_report(
            target_report,
            target_attestation,
        )
        environment_payload = {
            "formal_result_activation_status": "sandboxie_environment_verified",
            "sandboxie_environment_observed": True,
            "sandboxie_environment_verified": True,
            "formal_result_executed_in_verified_environment": False,
            "formal_result_eligible": False,
            "sandboxie_environment_report": {
                "path": "sandboxie_environment_report.json",
                "report_id": summary["report_id"],
                "file_sha256": summary["report_file_sha256"],
                "semantic_sha256": summary["report_semantic_sha256"],
                "configuration_backup_path": summary["configuration_backup_path"],
                "configuration_backup_sha256": summary["configuration_backup_sha256"],
            },
            "sandboxie_environment_attestation": {
                "path": ATTESTATION_FILENAME,
                "file_sha256": summary["attestation_file_sha256"],
                "semantic_sha256": summary["attestation_semantic_sha256"],
                "original_report_sha256": summary["original_report_sha256"],
                "environment_fingerprint": summary["environment_fingerprint"],
                "machine_key_id": summary["machine_key_id"],
            },
        }
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
            "payload": environment_payload,
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
