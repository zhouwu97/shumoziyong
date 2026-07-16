from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import workspace_orchestrator as orchestrator


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_run(root: Path, *, completed_gate: int | None = None) -> Path:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "run_workflow.py").write_text("# fixture\n", encoding="utf-8")
    run = root / "runs" / "run-001"
    run.mkdir(parents=True)
    manifest = {
        "run_id": "run-001",
        "workflow": "full_replay",
        "mode": "standard",
        "promotion_evidence": False,
    }
    write_json(run / "run_manifest.json", manifest)
    write_json(run / "runtime_pack.manifest.json", {"runtime_pack_sha256": "a" * 64})
    write_json(run / "runtime_profile.snapshot.json", {"profile": "engineering_optimization"})
    write_json(run / "problem_manifest.json", {"problem_id": "测试-A"})
    (run / "runtime_pack.md").write_text("runtime\n", encoding="utf-8")
    first = {
        "state": "started_gate_0",
        "next_gate": 0,
        "completed_gate": None,
        "event_sha256": "1" * 64,
    }
    entries = [first]
    if completed_gate is not None:
        for gate in range(completed_gate + 1):
            entries.append(
                {
                    "state": f"completed_gate_{gate}",
                    "next_gate": gate + 1,
                    "completed_gate": gate,
                    "event_sha256": f"{gate + 2:064x}"[-64:],
                }
            )
    (run / "transitions.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in entries), encoding="utf-8"
    )
    return run


def fake_git_value(_engine_home: Path, *args: str) -> str:
    if args[:2] == ("rev-parse", "HEAD"):
        return "a" * 40
    if args[:2] == ("rev-parse", "--abbrev-ref"):
        return "training/test"
    if args[:2] == ("config", "--get"):
        return "https://example.invalid/shumo.git"
    raise AssertionError(args)


def fake_run_command(command: list[str], **_kwargs: object) -> object:
    stdout = "a" * 40 + "\n" if command[:3] == ["git", "rev-parse", "HEAD"] else ""
    return type("Result", (), {"stdout": stdout, "stderr": "", "returncode": 0})()


def test_discover_is_read_only_and_supports_chinese_space_path(tmp_path: Path) -> None:
    root = tmp_path / "中文 题目"
    problem = root / "problem"
    problem.mkdir(parents=True)
    (problem / "官方题面.pdf").write_bytes(b"pdf")
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

    result = orchestrator.discover_workspace(root)

    after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    assert before == after
    assert result["materials"][0]["category"] == "official_problem"
    assert not (root / ".shumo").exists()


def test_material_solution_is_blocked_and_override_is_hashed(tmp_path: Path) -> None:
    problem = tmp_path / "problem"
    problem.mkdir()
    (problem / "参考答案.pdf").write_bytes(b"answer")
    materials = orchestrator.list_materials(problem)
    assert orchestrator.material_decision(materials)[0] == "BLOCKED"

    overridden = orchestrator.apply_material_overrides(
        materials,
        [
            {
                "path": "problem/参考答案.pdf",
                "category": "official_problem",
                "reviewer": "human",
                "reason": "已与官方发布清单核对",
            }
        ],
    )
    assert overridden[0]["override"]["override_hash"]
    assert orchestrator.material_decision(overridden)[0] == "READY"


def test_medium_confidence_solution_requires_human_checkpoint(tmp_path: Path) -> None:
    problem = tmp_path / "problem"
    problem.mkdir()
    (problem / "建模思路.pdf").write_bytes(b"possible answer")

    materials = orchestrator.list_materials(problem)

    assert materials[0]["confidence"] == 0.65
    assert orchestrator.material_decision(materials)[0] == "HUMAN_CHECKPOINT"


def test_preflight_writes_only_reports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    problem = tmp_path / "problem"
    problem.mkdir()
    (problem / "题面.pdf").write_bytes(b"pdf")
    monkeypatch.setattr(
        orchestrator,
        "repository_preflight",
        lambda _engine: {
            "engine_commit": "a" * 40,
            "dirty": False,
            "offline_ready": True,
            "checks": [{"name": "repo", "passed": True, "detail": "ok"}],
            "passed": True,
        },
    )

    report = orchestrator.preflight_workspace(tmp_path, [])

    assert report["decision"] == "READY"
    assert (tmp_path / ".shumo" / "PREFLIGHT_REPORT.json").is_file()
    assert (tmp_path / ".shumo" / "PREFLIGHT_REPORT.md").is_file()
    assert not (tmp_path / ".shumo" / "runs").exists()
    assert not (tmp_path / ".shumo" / "engine").exists()


def test_lock_allows_only_one_active_attempt(tmp_path: Path) -> None:
    lock_path = tmp_path / "orchestrator.lock"
    with orchestrator.OrchestratorLock(lock_path, "attempt-a"):
        with pytest.raises(ValueError, match="active orchestrator lock"):
            with orchestrator.OrchestratorLock(lock_path, "attempt-b"):
                pass
    assert not lock_path.exists()


def test_stale_lock_recovery_requires_audit_identity_and_reason(tmp_path: Path) -> None:
    lock = tmp_path / ".shumo" / "locks" / "orchestrator.lock"
    write_json(
        lock,
        {
            "attempt_id": "attempt_dead",
            "pid": 2_000_000_000,
            "owner": "test",
            "created_at": "2026-07-15T17:00:00+08:00",
        },
    )
    with pytest.raises(orchestrator.HumanCheckpointRequired, match="reviewer 和 reason"):
        orchestrator.recover_stale_lock(tmp_path, reviewer=None, reason=None)

    result = orchestrator.recover_stale_lock(
        tmp_path, reviewer="human-operator", reason="确认原进程已经退出"
    )

    assert result is not None
    assert not lock.exists()
    recovery = Path(result["record"])
    assert read_json(recovery)["reviewer"] == "human-operator"


def test_compatibility_bootstrap_is_idempotent_and_non_qualifying(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "requirements.lock").write_text("locked\n", encoding="utf-8")
    run = make_run(engine)
    workspace_root = tmp_path / "sidecar"
    monkeypatch.setattr(orchestrator, "find_git_root", lambda _path: engine)
    monkeypatch.setattr(orchestrator, "git_value", fake_git_value)
    monkeypatch.setattr(
        orchestrator,
        "run_command",
        fake_run_command,
    )
    before = orchestrator.snapshot_identity(run)

    first = orchestrator.bootstrap_compatibility(workspace_root, run)
    second = orchestrator.bootstrap_compatibility(workspace_root, run)

    assert first["workspace_id"] == second["workspace_id"]
    assert first["qualification_eligible"] is False
    assert first["promotion_evidence"] is False
    assert first["original_run_unchanged"] is True
    assert orchestrator.snapshot_identity(run) == before
    assert len(list((workspace_root / ".shumo" / "attempts").iterdir())) == 1
    assert orchestrator.check_workspace(workspace_root)["valid"] is True


def test_bootstrap_refuses_second_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "requirements.lock").write_text("locked\n", encoding="utf-8")
    first_run = make_run(engine)
    other_root = engine / "other"
    second_run = make_run(other_root)
    workspace_root = tmp_path / "sidecar"
    monkeypatch.setattr(orchestrator, "find_git_root", lambda _path: engine)
    monkeypatch.setattr(orchestrator, "git_value", fake_git_value)
    monkeypatch.setattr(
        orchestrator,
        "run_command",
        fake_run_command,
    )
    orchestrator.bootstrap_compatibility(workspace_root, first_run)

    with pytest.raises(ValueError, match="禁止重复创建第二个 Run"):
        orchestrator.bootstrap_compatibility(workspace_root, second_run)


def test_markdown_or_digest_drift_blocks_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "requirements.lock").write_text("locked\n", encoding="utf-8")
    run = make_run(engine)
    workspace_root = tmp_path / "sidecar"
    monkeypatch.setattr(orchestrator, "find_git_root", lambda _path: engine)
    monkeypatch.setattr(orchestrator, "git_value", fake_git_value)
    monkeypatch.setattr(
        orchestrator,
        "run_command",
        fake_run_command,
    )
    orchestrator.bootstrap_compatibility(workspace_root, run)
    markdown = workspace_root / ".shumo" / "NEXT_TASK.md"
    markdown.write_text(markdown.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")

    report = orchestrator.check_workspace(workspace_root)

    assert report["valid"] is False
    assert any("NEXT_TASK.md" in item for item in report["errors"])


def test_run_transition_can_advance_without_identity_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "requirements.lock").write_text("locked\n", encoding="utf-8")
    run = make_run(engine)
    workspace_root = tmp_path / "sidecar"
    monkeypatch.setattr(orchestrator, "find_git_root", lambda _path: engine)
    monkeypatch.setattr(orchestrator, "git_value", fake_git_value)
    monkeypatch.setattr(
        orchestrator,
        "run_command",
        fake_run_command,
    )
    orchestrator.bootstrap_compatibility(workspace_root, run)
    with (run / "transitions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "state": "completed_gate_0",
                    "next_gate": 1,
                    "completed_gate": 0,
                    "event_sha256": "2" * 64,
                }
            )
            + "\n"
        )

    task = orchestrator.next_task(workspace_root)

    assert task["stage_id"] == "executor_gate_1"
    assert orchestrator.check_workspace(workspace_root)["valid"] is True


def test_reviewer_package_is_fixed_whitelist(tmp_path: Path) -> None:
    run = make_run(tmp_path, completed_gate=4)
    write_json(run / "paper_claim_map.json", {"claims": []})
    write_json(run / "result_report.json", {"result": "ok"})
    (run / "logs").mkdir()
    (run / "logs" / "private.log").write_text("private", encoding="utf-8")
    (run / "executor_private.txt").write_text("private", encoding="utf-8")
    (run / "paper").mkdir()
    (run / "paper" / "paper.md").write_text("paper", encoding="utf-8")

    package = orchestrator.build_reviewer_package(tmp_path / "sidecar", run)

    assert not orchestrator.verify_reviewer_package(package)
    assert not (package / "logs").exists()
    assert not (package / "executor_private.txt").exists()
    manifest = read_json(package / "review_manifest.json")
    assert manifest["executor_private_material_included"] is False


def test_finalize_requires_independent_reviewer_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "requirements.lock").write_text("locked\n", encoding="utf-8")
    run = make_run(engine, completed_gate=4)
    workspace_root = tmp_path / "sidecar"
    monkeypatch.setattr(orchestrator, "find_git_root", lambda _path: engine)
    monkeypatch.setattr(orchestrator, "git_value", fake_git_value)
    monkeypatch.setattr(
        orchestrator,
        "run_command",
        fake_run_command,
    )
    orchestrator.bootstrap_compatibility(workspace_root, run)

    with pytest.raises(ValueError, match="approved review_outcome"):
        orchestrator.finalize_workspace(workspace_root, "reviewer-new-session")


def test_changes_required_forces_new_executor_and_new_reviewer_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "requirements.lock").write_text("locked\n", encoding="utf-8")
    run = make_run(engine, completed_gate=4)
    result_report = run / "result_report.json"
    result_report.write_text('{"version": 1}\n', encoding="utf-8")
    workspace_root = tmp_path / "sidecar"
    monkeypatch.setattr(orchestrator, "find_git_root", lambda _path: engine)
    monkeypatch.setattr(orchestrator, "git_value", fake_git_value)
    monkeypatch.setattr(orchestrator, "run_command", fake_run_command)
    orchestrator.bootstrap_compatibility(workspace_root, run)
    package_manifest = (
        workspace_root / "handoffs" / "reviewer" / "package" / "review_manifest.json"
    )
    workspace = read_json(workspace_root / ".shumo" / "workspace.json")
    outcome_path = tmp_path / "review_outcome.json"
    write_json(
        outcome_path,
        {
            "schema_version": "1.0.0",
            "run_id": workspace["run_id"],
            "workspace_id": workspace["workspace_id"],
            "package_manifest_sha256": orchestrator.sha256_file(package_manifest),
            "reviewer_session_id": "reviewer-session-001",
            "reviewer": "independent-reviewer",
            "reviewed_at": "2026-07-15T17:00:00+08:00",
            "decision": "changes_required",
            "findings": [
                {
                    "finding_id": "F-route",
                    "priority": "P1",
                    "gate": 2,
                    "summary": "代码计划与冻结模型目标不一致",
                    "evidence": ["code_plan.json", "model_route.json"],
                }
            ],
            "affected_gates": [2],
            "required_actions": ["修正代码计划并重跑受影响验证"],
            "gate_5_review_sha256": None,
        },
    )

    registered = orchestrator.register_review_outcome(workspace_root, outcome_path)

    assert registered["stage"] == "remediation_executor"
    assert registered["stop_condition"] == "NEW_SESSION_REQUIRED"
    assert orchestrator.check_workspace(workspace_root)["valid"] is True
    revision = read_json(orchestrator.active_revision_path(workspace_root))
    before = orchestrator.sha256_file(result_report)
    result_report.write_text('{"version": 2}\n', encoding="utf-8")
    after = orchestrator.sha256_file(result_report)
    evidence_path = tmp_path / "remediation_evidence.json"
    write_json(
        evidence_path,
        {
            "schema_version": "1.0.0",
            "revision_id": revision["revision_id"],
            "run_id": workspace["run_id"],
            "executor_session_id": "executor-session-002",
            "completed_at": "2026-07-15T17:30:00+08:00",
            "affected_gates": [2],
            "artifacts": [
                {
                    "root": "run",
                    "path": "result_report.json",
                    "before_sha256": before,
                    "after_sha256": after,
                    "reason": "修正结果与模型目标的绑定",
                }
            ],
            "validators_rerun": ["gate_2_contract", "gate_3_validator"],
            "summary": "已修正代码计划并重跑全部受影响验证。",
        },
    )

    handoff = orchestrator.remediation_handoff(workspace_root, evidence_path)

    assert handoff["stage"] == "final_recheck_reviewer"
    assert handoff["stop_condition"] == "NEW_SESSION_REQUIRED"
    assert orchestrator.check_workspace(workspace_root)["valid"] is True
    repeated_outcome = read_json(outcome_path)
    repeated_outcome["package_manifest_sha256"] = handoff["package_manifest_sha256"]
    write_json(outcome_path, repeated_outcome)
    with pytest.raises(ValueError, match="新的 Reviewer 会话"):
        orchestrator.register_review_outcome(workspace_root, outcome_path)


def test_gate_3_task_keeps_three_validation_dimensions() -> None:
    workspace = {
        "workspace_id": "ws_" + "a" * 16,
        "attempt_id": "attempt_test",
        "workspace_root": "C:/题目",
        "run_id": "run",
        "run_dir": "C:/题目/run",
        "workflow": "full_replay",
        "execution_mode": "autonomous_rehearsal",
        "engine_commit": "a" * 40,
    }
    task = orchestrator.task_contract(
        workspace,
        {
            "stage": "executor_gate_3",
            "role": "executor",
            "gate": 3,
            "run_transition_hash": "b" * 64,
        },
        None,
    )
    assert {
        "validation_dimension:implementation_correctness",
        "validation_dimension:model_validity",
        "validation_dimension:competition_value",
    }.issubset(task["required_outputs"])


def test_gate_1_task_exposes_problem_specific_modeling_contract() -> None:
    workspace = {
        "workspace_id": "ws_" + "a" * 16,
        "attempt_id": "attempt_test",
        "workspace_root": "C:/题目",
        "run_id": "run",
        "run_dir": "C:/题目/run",
        "workflow": "new_problem",
        "execution_mode": "standard",
        "engine_commit": "a" * 40,
    }
    task = orchestrator.task_contract(
        workspace,
        {"stage": "executor_gate_1", "role": "executor", "gate": 1, "run_transition_hash": "b" * 64},
        None,
    )
    assert "modeling_field:mechanism_chain" in task["required_outputs"]
    assert "modeling_field:problem_specific_insight" in task["required_outputs"]
    assert "modeling_field:dimension_reduction_basis" in task["required_outputs"]


def test_competition_commit_requires_explicit_approval(tmp_path: Path) -> None:
    with pytest.raises(orchestrator.HumanCheckpointRequired, match="approved tag"):
        orchestrator.select_approved_commit(tmp_path, "competition", None)


def test_material_snapshot_does_not_modify_problem(tmp_path: Path) -> None:
    problem = tmp_path / "problem"
    problem.mkdir()
    source = problem / "官方题面.pdf"
    source.write_bytes(b"official")
    material = orchestrator.classify_material(source, problem)
    shumo = tmp_path / ".shumo"
    write_json(
        shumo / "material_review.json",
        {
            "schema_version": "1.0.0",
            "decision": "READY",
            "materials": [material],
            "blockers": [],
        },
    )
    attempt = shumo / "attempts" / "attempt-test"
    attempt.mkdir(parents=True)
    before = orchestrator.tree_digest(problem)

    snapshot, digest = orchestrator.ensure_material_snapshot(
        tmp_path, attempt, "2026-A"
    )

    assert orchestrator.tree_digest(problem) == before
    assert digest == orchestrator.tree_digest(snapshot)
    manifest = read_json(snapshot / "material_manifest.json")
    assert manifest["problem_id"] == "2026-A"
    assert manifest["categories"]["problem"]["files"][0]["sha256"]


def test_native_attempt_reuses_blocked_transaction(tmp_path: Path) -> None:
    shumo = tmp_path / ".shumo"
    config = {"workflow": "new_problem", "problem_id": "2026-A"}
    first_id, first_path, record = orchestrator.native_attempt(shumo, config)
    record["status"] = "blocked"
    write_json(first_path / "ATTEMPT.json", record)

    second_id, second_path, _record = orchestrator.native_attempt(shumo, config)

    assert first_id == second_id
    assert first_path == second_path
    assert len(list((shumo / "attempts").iterdir())) == 1


def test_native_bootstrap_publishes_once_after_all_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_engine = tmp_path / "source-engine"
    source_engine.mkdir()
    (source_engine / "requirements.lock").write_text("locked\n", encoding="utf-8")
    (source_engine / "scripts").mkdir()
    (source_engine / "scripts" / "run_workflow.py").write_text("# fixture\n", encoding="utf-8")
    workspace_root = tmp_path / "2026-A"
    problem = workspace_root / "problem"
    problem.mkdir(parents=True)
    (problem / "官方题面.pdf").write_bytes(b"official")
    repository = {
        "engine_commit": "a" * 40,
        "dirty": False,
        "offline_ready": True,
        "checks": [{"name": "repo", "passed": True, "detail": "ok"}],
        "passed": True,
    }
    monkeypatch.setattr(orchestrator, "repository_preflight", lambda _engine: repository)
    monkeypatch.setattr(
        orchestrator,
        "select_approved_commit",
        lambda *_args: ("a" * 40, "HEAD"),
    )

    def fake_engine(root: Path, _source: Path, _commit: str, _attempt: Path) -> Path:
        engine = root / ".shumo" / "engine"
        engine.mkdir(parents=True, exist_ok=True)
        (engine / "requirements.lock").write_text("locked\n", encoding="utf-8")
        (engine / "scripts").mkdir(exist_ok=True)
        (engine / "scripts" / "run_workflow.py").write_text("# fixture\n", encoding="utf-8")
        return engine

    def fake_environment(
        _root: Path, _engine: Path, _attempt: Path, mode: str
    ) -> tuple[Path, dict[str, object]]:
        return Path(sys.executable), {
            "python_version": "3.12.0",
            "platform": "test",
            "requirements_lock_sha256": "b" * 64,
            "environment_mode": mode,
            "network_used": False,
            "offline_ready": True,
        }

    def fake_run(
        _python: Path,
        _engine: Path,
        root: Path,
        _materials: Path,
        _config: object,
        _workspace_id: str,
        _attempt: Path,
    ) -> Path:
        return make_run(root / ".shumo")

    monkeypatch.setattr(orchestrator, "ensure_detached_engine", fake_engine)
    monkeypatch.setattr(orchestrator, "ensure_workspace_environment", fake_environment)
    monkeypatch.setattr(orchestrator, "ensure_native_run", fake_run)
    monkeypatch.setattr(orchestrator, "git_value", fake_git_value)

    first = orchestrator.bootstrap_native(
        workspace_root,
        workflow="new_problem",
        execution_mode="standard",
        problem_id="2026-A",
        profile="general",
        release_channel="training",
        approved_ref=None,
        engine_home_override=str(source_engine),
        environment_mode="workspace_venv",
    )
    second = orchestrator.bootstrap_native(
        workspace_root,
        workflow="new_problem",
        execution_mode="standard",
        problem_id="2026-A",
        profile="general",
        release_channel="training",
        approved_ref=None,
        engine_home_override=str(source_engine),
        environment_mode="workspace_venv",
    )

    assert first["workspace_id"] == second["workspace_id"]
    assert first["orchestration_mode"] == "native"
    assert first["qualification_eligible"] is False
    assert (workspace_root / ".shumo" / "NEXT_TASK.json").is_file()
    assert len(list((workspace_root / ".shumo" / "attempts").iterdir())) == 1


def test_workflow_specs_match_schema() -> None:
    schema = read_json(orchestrator.ROOT / "schemas" / "workflow_spec.schema.json")
    for name in (
        "workspace_orchestration_full_replay_v1.json",
        "workspace_orchestration_new_problem_v1.json",
    ):
        spec = read_json(orchestrator.ROOT / "workflow_specs" / name)
        Draft202012Validator(schema).validate(spec)
        assert spec["qualification_policy"]["automatic_maturity_upgrade"] is False


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
