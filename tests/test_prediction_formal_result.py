"""Prediction Formal Result 的领域隔离和攻击回归。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from formal_result.domain_contracts import PREDICTION_CONTRACT  # noqa: E402
import formal_result.derivation as derivation_module  # noqa: E402
from formal_result.collector_policy import (  # noqa: E402
    PREDICTION_DERIVATION_CONTRACT_ID,
)
from formal_result.derivation import verify_formal_result_derivation  # noqa: E402
from formal_result.errors import FormalResultVerificationError  # noqa: E402
from formal_result.hashing import file_sha256, semantic_sha256  # noqa: E402
from formal_result.verifier import verify_formal_result_bundle  # noqa: E402
from formal_result_fixtures import write_formal_result_bundle  # noqa: E402
from test_repository_tooling import _v2_gate_0_run  # noqa: E402
from run_in_verified_sandbox import _derive_formal_result  # noqa: E402


M3A_FIXTURE = ROOT / "tests" / "fixtures" / "m3a_verified_run"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _replace_identity_profile(value: dict[str, Any]) -> None:
    if "profile" in value:
        value["profile"] = "prediction"


def _prediction_bundle(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = _v2_gate_0_run(tmp_path)
    old_envelope = write_formal_result_bundle(run_dir)
    formal = old_envelope.parent

    run_manifest = _load(run_dir / "run_manifest.json")
    run_manifest["profile"] = "prediction"
    _write(run_dir / "run_manifest.json", run_manifest)

    execution_path = run_dir / "execution_spec.json"
    execution = _load(execution_path)
    execution["profile"] = "prediction"
    _write(execution_path, execution)
    execution_semantic = semantic_sha256(execution)

    for name in (
        "decision_variables.json",
        "optimization_validation.json",
        "optimality_certificate.json",
    ):
        (formal / name).unlink()

    common = {
        "schema_version": "1.0.0",
        **{
            field: run_manifest[field]
            for field in (
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
        },
        "formal_result_id": formal.name,
    }
    prediction_result = {
        **common,
        "artifact_type": "prediction_result",
        "status": "collected",
        "bindings": {"execution_spec.json": execution_semantic},
        "payload": {
            "group_key": "pregnant_woman_id",
            "random_seed": 2025,
            "split_assignments": [
                {"sample_id": "train-1", "group_id": "P000", "split": "train"},
                {"sample_id": "eval-1", "group_id": "P001", "split": "test"},
                {"sample_id": "eval-2", "group_id": "P002", "split": "test"},
                {"sample_id": "eval-3", "group_id": "P003", "split": "test"},
                {"sample_id": "eval-4", "group_id": "P004", "split": "test"},
            ],
            "fit_audits": [
                {
                    "stage": "imputer_scaler_classifier",
                    "fit_scope": "training_only",
                    "training_data_sha256": "a" * 64,
                }
            ],
            "tasks": [
                {
                    "task_id": "female_fetal_abnormality",
                    "task_type": "binary_classification",
                    "threshold": 0.5,
                    "predictions": [
                        {"sample_id": "eval-1", "y_true": 1, "y_score": 0.9},
                        {"sample_id": "eval-2", "y_true": 0, "y_score": 0.8},
                        {"sample_id": "eval-3", "y_true": 1, "y_score": 0.7},
                        {"sample_id": "eval-4", "y_true": 0, "y_score": 0.1},
                    ],
                }
            ],
        },
    }
    prediction_validation = {
        **common,
        "artifact_type": "prediction_validation",
        "status": "passed",
        "bindings": {"prediction_result.json": semantic_sha256(prediction_result)},
        "payload": {
            "patient_split_check": {"status": "passed", "overlap_group_count": 0},
            "fit_scope_checks": [
                {"stage": "imputer_scaler_classifier", "status": "passed"}
            ],
            "tasks": [
                {
                    "task_id": "female_fetal_abnormality",
                    "status": "passed",
                    "metrics": {
                        "brier": 0.1875,
                        "pr_auc": 5 / 6,
                        "roc_auc": 0.75,
                        "recall": 1.0,
                        "precision": 2 / 3,
                        "positive_rate": 0.5,
                    },
                }
            ],
        },
    }
    certificate = {
        **common,
        "artifact_type": "prediction_reproducibility_certificate",
        "status": "passed",
        "bindings": {"prediction_validation.json": semantic_sha256(prediction_validation)},
        "payload": {
            "claim_scope": "held_out_predictive_performance",
            "random_seed": 2025,
            "grouping_key": "pregnant_woman_id",
            "preprocessing_scope": "training_only",
            "screening_only": True,
            "causal_claims_supported": False,
        },
    }
    for name, value in {
        "prediction_result.json": prediction_result,
        "prediction_validation.json": prediction_validation,
        "prediction_reproducibility_certificate.json": certificate,
    }.items():
        _write(formal / name, value)

    for name in (
        "negative_tests.json",
        "input_manifest.json",
        "code_manifest.json",
        "environment_manifest.json",
        "collector_attestation.json",
    ):
        value = _load(formal / name)
        _replace_identity_profile(value)
        if name in {"negative_tests.json", "input_manifest.json", "code_manifest.json", "environment_manifest.json"}:
            value["bindings"] = {"execution_spec.json": execution_semantic}
        _write(formal / name, value)

    _close_prediction_hash_chain(run_dir, formal)
    return run_dir, formal / "formal_result_envelope.json"


def _close_prediction_hash_chain(run_dir: Path, formal: Path) -> None:
    """测试攻击重绑外层哈希，迫使领域重算器检查语义。"""
    result = _load(formal / "prediction_result.json")
    validation = _load(formal / "prediction_validation.json")
    validation["bindings"] = {"prediction_result.json": semantic_sha256(result)}
    _write(formal / "prediction_validation.json", validation)
    certificate = _load(formal / "prediction_reproducibility_certificate.json")
    certificate["bindings"] = {"prediction_validation.json": semantic_sha256(validation)}
    _write(formal / "prediction_reproducibility_certificate.json", certificate)

    negative = _load(formal / "negative_tests.json")
    execution = _load(run_dir / "execution_spec.json")
    negative["bindings"] = {"execution_spec.json": semantic_sha256(execution)}
    _write(formal / "negative_tests.json", negative)

    attestation = _load(formal / "collector_attestation.json")
    attestation["profile"] = "prediction"
    attestation["execution_spec_sha256"] = file_sha256(run_dir / "execution_spec.json")
    attestation["input_manifest_sha256"] = file_sha256(formal / "input_manifest.json")
    attestation["code_manifest_sha256"] = file_sha256(formal / "code_manifest.json")
    attestation["environment_manifest_sha256"] = file_sha256(
        formal / "environment_manifest.json"
    )
    attestation["negative_test_report_sha256"] = file_sha256(formal / "negative_tests.json")
    attestation["output_file_set"] = list(PREDICTION_CONTRACT.output_file_set)
    _write(formal / "collector_attestation.json", attestation)

    schema_by_name = {
        "formal_result_manifest.json": "formal_result_bundle_manifest.schema.json",
        "prediction_result.json": "formal_result_prediction_result.schema.json",
        "prediction_validation.json": "formal_result_prediction_validation.schema.json",
        "prediction_reproducibility_certificate.json": (
            "formal_result_prediction_certificate.schema.json"
        ),
        "collector_attestation.json": "collector_attestation.schema.json",
        "negative_tests.json": "formal_result_prediction_negative_tests.schema.json",
        "input_manifest.json": "formal_result_provenance_manifest.schema.json",
        "code_manifest.json": "formal_result_provenance_manifest.schema.json",
        "environment_manifest.json": "formal_result_provenance_manifest.schema.json",
    }
    semantic_names = [
        name for name in PREDICTION_CONTRACT.required_artifacts if name.endswith(".json")
    ]
    manifest = _load(formal / "formal_result_manifest.json")
    manifest["profile"] = "prediction"
    manifest["semantic_hashes"] = {
        name: semantic_sha256(_load(formal / name))
        for name in semantic_names
        if name != "formal_result_manifest.json"
    }
    _write(formal / "formal_result_manifest.json", manifest)

    descriptors: list[dict[str, Any]] = []
    for name in PREDICTION_CONTRACT.required_artifacts:
        path = formal / name
        descriptor: dict[str, Any] = {
            "path": name,
            "media_type": "application/json" if name.endswith(".json") else "text/plain",
            "file_sha256": file_sha256(path),
        }
        if name.endswith(".json"):
            descriptor["semantic_sha256"] = semantic_sha256(_load(path))
            descriptor["schema"] = schema_by_name[name]
        descriptors.append(descriptor)
    domain = {
        "schema_version": "1.0.0",
        **{
            field: _load(run_dir / "run_manifest.json")[field]
            for field in (
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
        },
        "formal_result_id": formal.name,
        "artifact_type": "domain_manifest",
        "domain": "predictive_modeling",
        "mechanism": "repeated_measures_prediction",
        "validator_id": "prediction-held-out-metrics-v1",
        "validator_version": "1.0.0",
        "required_artifacts": descriptors,
        "required_certificates": ["prediction_reproducibility_certificate.json"],
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
        "negative_test_requirements": ["missing-input", "tampered-output"],
        "output_file_set": list(PREDICTION_CONTRACT.output_file_set),
        "semantic_hashes": {
            item["path"]: item["semantic_sha256"]
            for item in descriptors
            if "semantic_sha256" in item
        },
    }
    _write(formal / "domain_manifest.json", domain)

    envelope = _load(formal / "formal_result_envelope.json")
    envelope["profile"] = "prediction"
    envelope["execution_spec_file_sha256"] = file_sha256(run_dir / "execution_spec.json")
    envelope["execution_spec_semantic_sha256"] = semantic_sha256(execution)
    envelope["domain_manifest_file_sha256"] = file_sha256(formal / "domain_manifest.json")
    envelope["domain_manifest_semantic_sha256"] = semantic_sha256(domain)
    envelope["formal_result_manifest_file_sha256"] = file_sha256(
        formal / "formal_result_manifest.json"
    )
    envelope["formal_result_manifest_semantic_sha256"] = semantic_sha256(manifest)
    envelope["collector_attestation_semantic_sha256"] = semantic_sha256(attestation)
    _write(formal / "formal_result_envelope.json", envelope)


def test_prediction_bundle_accepts_weak_but_reproducible_metrics(tmp_path: Path) -> None:
    run_dir, envelope = _prediction_bundle(tmp_path)

    summary = verify_formal_result_bundle(run_dir, envelope)

    assert summary["formal_result_domain"] == "predictive_modeling"
    assert summary["formal_result_eligible"] is False


def test_prediction_bundle_rejects_patient_group_leakage_after_hash_rebind(
    tmp_path: Path,
) -> None:
    run_dir, envelope = _prediction_bundle(tmp_path)
    result = _load(envelope.parent / "prediction_result.json")
    result["payload"]["split_assignments"][0]["group_id"] = "P001"
    _write(envelope.parent / "prediction_result.json", result)
    _close_prediction_hash_chain(run_dir, envelope.parent)

    with pytest.raises(FormalResultVerificationError, match="训练/评估重叠"):
        verify_formal_result_bundle(run_dir, envelope)


def test_prediction_bundle_rejects_metric_tampering_after_hash_rebind(
    tmp_path: Path,
) -> None:
    run_dir, envelope = _prediction_bundle(tmp_path)
    validation = _load(envelope.parent / "prediction_validation.json")
    validation["payload"]["tasks"][0]["metrics"]["pr_auc"] = 0.99
    _write(envelope.parent / "prediction_validation.json", validation)
    _close_prediction_hash_chain(run_dir, envelope.parent)

    with pytest.raises(FormalResultVerificationError, match="PR-AUC|pr_auc"):
        verify_formal_result_bundle(run_dir, envelope)


def test_prediction_bundle_rejects_unregistered_domain_profile_pair(tmp_path: Path) -> None:
    run_dir, envelope = _prediction_bundle(tmp_path)
    domain = _load(envelope.parent / "domain_manifest.json")
    domain["profile"] = "general"
    _write(envelope.parent / "domain_manifest.json", domain)
    envelope_value = _load(envelope)
    envelope_value["domain_manifest_file_sha256"] = file_sha256(
        envelope.parent / "domain_manifest.json"
    )
    envelope_value["domain_manifest_semantic_sha256"] = semantic_sha256(domain)
    _write(envelope, envelope_value)

    with pytest.raises(FormalResultVerificationError, match="未注册"):
        verify_formal_result_bundle(run_dir, envelope)


def test_native_candidate_builder_emits_prediction_pending_bundle(tmp_path: Path) -> None:
    run_dir = tmp_path / "prediction-run"
    shutil.copytree(M3A_FIXTURE, run_dir)
    for relative in ("run_manifest.json", "execution_spec.json"):
        value = _load(run_dir / relative)
        value["profile"] = "prediction"
        _write(run_dir / relative, value)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_formal_result_candidate.py"),
            "--run-dir",
            str(run_dir),
            "--formal-result-id",
            "formal-prediction-pending-001",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    envelope = (
        run_dir
        / "formal_results"
        / "formal-prediction-pending-001"
        / "formal_result_envelope.json"
    )
    summary = verify_formal_result_bundle(run_dir, envelope)
    result = _load(envelope.parent / "prediction_result.json")
    negative = _load(envelope.parent / "negative_tests.json")
    assert summary["formal_result_domain"] == "predictive_modeling"
    assert summary["formal_result_eligible"] is False
    assert result["status"] == "execution_pending"
    assert negative["status"] == "execution_pending"


def test_prediction_raw_output_is_derived_and_recomputed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "prediction-derivation"
    shutil.copytree(M3A_FIXTURE, run_dir)
    for relative in ("run_manifest.json", "execution_spec.json"):
        value = _load(run_dir / relative)
        value["profile"] = "prediction"
        _write(run_dir / relative, value)
    formal_id = "formal-prediction-derived-001"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_formal_result_candidate.py"),
            "--run-dir",
            str(run_dir),
            "--formal-result-id",
            formal_id,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    raw = {
        "derivation_contract_id": PREDICTION_DERIVATION_CONTRACT_ID,
        "group_key": "pregnant_woman_id",
        "random_seed": 2025,
        "split_assignments": [
            {"sample_id": "train-1", "group_id": "P000", "split": "train"},
            {"sample_id": "eval-1", "group_id": "P001", "split": "test"},
            {"sample_id": "eval-2", "group_id": "P002", "split": "test"},
            {"sample_id": "eval-3", "group_id": "P003", "split": "test"},
            {"sample_id": "eval-4", "group_id": "P004", "split": "test"},
        ],
        "fit_audits": [
            {
                "stage": "imputer_scaler_classifier",
                "fit_scope": "training_only",
                "training_data_sha256": "a" * 64,
            }
        ],
        "tasks": [
            {
                "task_id": "female_fetal_abnormality",
                "task_type": "binary_classification",
                "threshold": 0.5,
                "predictions": [
                    {"sample_id": "eval-1", "y_true": 1, "y_score": 0.9},
                    {"sample_id": "eval-2", "y_true": 0, "y_score": 0.8},
                    {"sample_id": "eval-3", "y_true": 1, "y_score": 0.7},
                    {"sample_id": "eval-4", "y_true": 0, "y_score": 0.1},
                ],
            }
        ],
        "negative_tests_status": "passed",
        "negative_tests": [
            {"test_id": "missing-input", "status": "passed"},
            {"test_id": "tampered-output", "status": "passed"},
        ],
    }
    output_root = run_dir / "workspace" / "output"
    output_root.mkdir(parents=True, exist_ok=True)
    _write(output_root / "result.json", raw)
    _write(
        run_dir / "run_output_manifest.json",
        {
            "files": [
                {
                    "path": "result.json",
                    "sha256": file_sha256(output_root / "result.json"),
                }
            ]
        },
    )
    source_sha = "b" * 64
    _derive_formal_result(
        run_dir,
        formal_id,
        "prediction-execution-001",
        "2026-07-17T12:00:00+08:00",
        "a" * 40,
        source_sha,
    )

    formal = run_dir / "formal_results" / formal_id
    validation = _load(formal / "prediction_validation.json")
    assert validation["payload"]["tasks"][0]["metrics"]["brier"] == pytest.approx(
        0.1875
    )
    assert validation["payload"]["tasks"][0]["metrics"]["pr_auc"] == pytest.approx(
        5 / 6
    )
    monkeypatch.setattr(
        derivation_module,
        "collector_script_sha256_at_commit",
        lambda _commit, _path: source_sha,
    )
    derivation = verify_formal_result_derivation(run_dir, formal_id)
    assert derivation["formal_result_core_digest"]

    _close_prediction_hash_chain(run_dir, formal)
    summary = verify_formal_result_bundle(
        run_dir,
        formal / "formal_result_envelope.json",
    )
    assert summary["formal_result_domain"] == "predictive_modeling"
