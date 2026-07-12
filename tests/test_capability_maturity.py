from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from derive_capability_maturity import derive_maturity, validate_evidence  # noqa: E402
from executor_core import execute_spec  # noqa: E402


def _evidence() -> dict[str, object]:
    sha = "a" * 64
    return {
        "schema_version": "1.0.0",
        "evidence_id": "engineering-optimization-qualification",
        "scope": "profile",
        "profile": "engineering_optimization",
        "foundation_documents": ["vision", "architecture", "roadmap"],
        "contracts": [
            {"contract_id": contract_id, "schema_path": schema_path, "sha256": sha}
            for contract_id, schema_path in [
                ("diagnosis_v2", "schemas/diagnosis.schema.json"),
                ("model_route_v2", "schemas/model_route_v2.schema.json"),
                ("execution_spec_v1", "schemas/execution_spec.schema.json"),
                ("executor_handoff_v1", "schemas/executor_handoff.schema.json"),
                ("executor_blocker_v1", "schemas/executor_blocker.schema.json"),
            ]
        ],
        "runtime_verifications": [
            {"run_id": "run-1", "evidence_ref": "runs/run-1/seal_record.json", "status": "passed"}
        ],
        "execution_cycles": [
            {
                "cycle_id": "cycle-1",
                "candidate_execution_ref": "runs/run-1/execution_record.json",
                "collector_report_ref": "runs/run-1/collector_report.json",
                "formal_result_ref": "runs/run-1/formal_result_manifest.json",
                "status": "passed",
                "fabrication_detected": False,
            }
        ],
        "qualification_cases": [
            {
                "case_id": "case-1",
                "year": 2023,
                "mechanism": "linear_optimization",
                "formal_replay_status": "passed",
                "fabrication_detected": False,
                "fatal_math_error": False,
                "reviewers": [{"reviewer_id": "reviewer-a", "shared_p0": False}],
            },
            {
                "case_id": "case-2",
                "year": 2024,
                "mechanism": "heuristic_optimization",
                "formal_replay_status": "passed",
                "fabrication_detected": False,
                "fatal_math_error": False,
                "reviewers": [{"reviewer_id": "reviewer-b", "shared_p0": False}],
            },
            {
                "case_id": "case-3",
                "year": 2024,
                "mechanism": "linear_optimization",
                "formal_replay_status": "passed",
                "fabrication_detected": False,
                "fatal_math_error": False,
                "reviewers": [{"reviewer_id": "reviewer-a", "shared_p0": False}],
            },
        ],
        "benchmark": {
            "protocol_registered": True,
            "blind_cases": [
                {"case_id": f"blind-{index}", "blind": True, "formal_replay_status": "passed"}
                for index in range(6)
            ],
            "average_score": 82,
        },
        "simulations": [
            {"simulation_id": "sim-1", "duration_hours": 72, "reproducible_delivery": True, "status": "passed"},
            {"simulation_id": "sim-2", "duration_hours": 70, "reproducible_delivery": True, "status": "passed"},
        ],
        "independent_reviews": [
            {"reviewer_id": "expert-a", "blind": True, "score": 81},
            {"reviewer_id": "expert-b", "blind": True, "score": 83},
        ],
        "formal_national_award": False,
    }


def _policy() -> dict[str, object]:
    return json.loads((ROOT / "policies" / "capability_maturity_policy.json").read_text("utf-8"))


def test_capability_evidence_rejects_manual_maturity_field() -> None:
    evidence = _evidence()
    evidence["maturity"] = "national_award_competitive"
    with pytest.raises(ValueError, match="不符合 Schema"):
        validate_evidence(evidence)


def test_maturity_is_derived_from_complete_evidence() -> None:
    evidence = _evidence()
    validate_evidence(evidence)
    result = derive_maturity(evidence, _policy())
    assert result["derived_maturity"] == "national_award_competitive"
    assert result["next_status"] is None


def test_fabrication_blocks_executor_and_higher_maturity() -> None:
    evidence = copy.deepcopy(_evidence())
    execution_cycles = evidence["execution_cycles"]
    assert isinstance(execution_cycles, list)
    execution_cycles[0]["fabrication_detected"] = True
    result = derive_maturity(evidence, _policy())
    assert result["derived_maturity"] == "contract_ready"
    assert result["next_status"] == "executor_validated"
    assert "伪造" in result["missing_requirements"][0]


def test_execution_spec_contract_forbids_network_access() -> None:
    schema = json.loads((ROOT / "schemas" / "execution_spec.schema.json").read_text("utf-8"))
    spec = {
        "schema_version": "1.0.0",
        "artifact_type": "execution_spec",
        "run_id": "run-1",
        "problem_id": "2024-C",
        "profile": "engineering_optimization",
        "runtime_pack_sha256": "a" * 64,
        "execution_mode": "trusted_local",
        "declared_workspace": "workspace",
        "network_access": False,
        "declared_writable_paths": ["workspace/code", "workspace/output"],
        "approved_by": "reviewer-a",
        "approved_at": "2026-07-12T10:00:00Z",
        "tasks": [
            {
                "task_id": "Q1_BASELINE",
                "entrypoint": "code/q1_baseline.py",
                "argv": ["python", "code/q1_baseline.py"],
                "working_directory": "workspace",
                "inputs": [],
                "required_outputs": [{"path": "workspace/output/result.json", "media_type": "application/json"}],
                "depends_on": [],
                "timeout_seconds": 600,
                "seed_policy": {"deterministic_expected": True, "seeds": [0]},
                "acceptance_checks": [{"check_id": "result", "kind": "file_exists", "expectation": "输出存在"}],
                "fallback": "emit_blocker",
            }
        ],
    }
    assert not list(Draft202012Validator(schema).iter_errors(spec))
    spec["network_access"] = True
    assert list(Draft202012Validator(schema).iter_errors(spec))


def test_executor_runs_candidate_and_requires_collector(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    script = workspace / "code" / "task.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "from pathlib import Path\n"
        "Path('output').mkdir(exist_ok=True)\n"
        "Path('output/result.json').write_text('{\"score\": 1}', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (run_dir / "run_manifest.json").write_text('{"run_id": "run-1"}', encoding="utf-8")
    spec = {
        "schema_version": "1.0.0",
        "artifact_type": "execution_spec",
        "run_id": "run-1",
        "problem_id": "2024-C",
        "profile": "engineering_optimization",
        "runtime_pack_sha256": "a" * 64,
        "execution_mode": "trusted_local",
        "declared_workspace": "workspace",
        "network_access": False,
        "declared_writable_paths": ["workspace/code", "workspace/output"],
        "approved_by": "reviewer-a",
        "approved_at": "2026-07-12T10:00:00Z",
        "tasks": [
            {
                "task_id": "Q1_BASELINE",
                "entrypoint": "code/task.py",
                "argv": [sys.executable, "code/task.py"],
                "working_directory": "workspace",
                "inputs": [],
                "required_outputs": [{"path": "workspace/output/result.json", "media_type": "application/json"}],
                "depends_on": [],
                "timeout_seconds": 60,
                "seed_policy": {"deterministic_expected": True, "seeds": [0]},
                "acceptance_checks": [{"check_id": "result", "kind": "file_exists", "expectation": "output/result.json"}],
                "fallback": "emit_blocker",
            }
        ],
    }
    spec_path = run_dir / "execution_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    record = execute_spec(spec_path, run_dir, "test-executor")

    assert record["status"] == "completed"
    assert record["formal_result_authority"] == "collector_required"
    assert (run_dir / "candidate_execution_record.json").is_file()
    assert not (run_dir / "executor_blocker.json").exists()
