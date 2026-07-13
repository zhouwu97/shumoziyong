import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from validators.problem_boundary_v2.validate import expected_tables


def _load_validator_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate_a092_formal_run.py"
    spec = spec_from_file_location("validate_a092_formal_run", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR_MODULE = _load_validator_module()
audit_isolation = VALIDATOR_MODULE.audit_isolation


def _write_events(run_dir: Path, events: list[dict[str, object]]) -> None:
    run_dir.mkdir(parents=True)
    text = "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"
    (run_dir / "runner_events.jsonl").write_text(text, encoding="utf-8")


def test_isolation_audit_accepts_own_run_reference(tmp_path: Path) -> None:
    run_dir = tmp_path / "a092_confirmatory_v1" / "R01"
    _write_events(run_dir, [{"command": str(run_dir / "results" / "formal_result.json")}])

    report = audit_isolation(run_dir)

    assert report["valid"] is True
    assert report["forbidden_reference_count"] == 0


def test_isolation_audit_rejects_other_run_reference(tmp_path: Path) -> None:
    run_dir = tmp_path / "a092_confirmatory_v1" / "R01"
    _write_events(run_dir, [{"command": "type a092_confirmatory_v1/R02/results/formal_result.json"}])

    report = audit_isolation(run_dir)

    assert report["valid"] is False
    assert report["forbidden_reference_count"] == 1


def test_v2_isolation_audit_accepts_own_attempt_and_rejects_other_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "a092_confirmatory_v2" / "R01"
    _write_events(
        run_dir,
        [
            {"command": "type a092_confirmatory_v2/attempts/R01/attempt-1/result.json"},
            {"command": "type a092_confirmatory_v2/runs/R02/result.json"},
        ],
    )

    report = audit_isolation(run_dir, "v2")

    assert report["valid"] is False
    assert report["forbidden_reference_count"] == 1


def test_v3_isolation_audit_requires_frozen_claude_engine_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "a092_confirmatory_v3" / "R01"
    _write_events(run_dir, [{"command": "python solve.py"}])
    (run_dir / "runner_metadata.json").write_text(
        json.dumps(
            {
                "execution_engine": "Claude Code",
                "cli_version_observed": "2.1.207",
                "model_observed": "claude-opus-4-8[1m]",
                "engine_valid": True,
            }
        ),
        encoding="utf-8",
    )

    report = audit_isolation(run_dir, "v3")

    assert report["valid"] is True
    assert report["engine_findings"] == []


def test_v2_boundary_validation_writes_external_artifacts_without_optimization_claims(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "a092_confirmatory_v2" / "R05"
    (run_dir / "materials" / "problem").mkdir(parents=True)
    (run_dir / "materials" / "problem" / "B题.pdf").write_bytes(b"pilot fixture")
    (run_dir / "results").mkdir()
    (run_dir / "results" / "formal_result.json").write_text(
        json.dumps(expected_tables(), ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "runner_events.jsonl").write_text(
        json.dumps({"command": "python solve.py"}) + "\n", encoding="utf-8"
    )
    (run_dir / "solve.py").write_text("print('candidate')\n", encoding="utf-8")

    report = VALIDATOR_MODULE.validate(run_dir, "2023-B", "v2")
    attestation = VALIDATOR_MODULE.build_v2_external_artifacts(
        run_dir, "2023-B", report
    )

    assert attestation["candidate_disposition"] == "accepted"
    assert not any(attestation["claim_permissions"].values())
    assert (run_dir / "artifacts" / "a092" / "data_contract_audit.json").is_file()
    assert (
        run_dir / "artifacts" / "a092" / "external_validator_attestation.json"
    ).is_file()
