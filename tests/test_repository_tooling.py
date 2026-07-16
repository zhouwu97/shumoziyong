from __future__ import annotations

import hashlib
import json
import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_prompt_response import evaluate_case  # noqa: E402
from gate3_executor import execute_gate_3_validator  # noqa: E402
from export_runtime_pack import (  # noqa: E402
    RUNTIME_CONTRACTS,
    build_manifest,
    build_pack,
    resolve_profile_for_context,
    select_patch_files,
    select_patches,
)
from run_workflow import (  # noqa: E402
    GATE_5_CHECKLIST_KEYS,
    GATE_NAMES,
    TRANSITION_VERSION,
    VALID_TRANSITIONS,
    advance_run,
    atomic_write_bytes,
    chain_transition_event,
    complete_and_seal_run,
    create_full_replay_run,
    create_new_problem_run,
    create_old_problem_run,
    create_prompt_regression_run,
    fork_profile,
    get_current_gate,
    is_gate_complete,
    mark_run_completed,
    record_transition,
    replay_transition_log,
    verify_gate_artifacts,
    verify_run,
    write_gate_artifact_manifest,
)
from finalize_run_evidence import finalize_run_evidence, validate_evidence_manifest  # noqa: E402
from evidence_validation import validate_full_run  # noqa: E402
from validate_repository import RepositoryValidator  # noqa: E402
from verify_materials import MaterialVerificationResult, sha256_bytes, verify_materials  # noqa: E402
from check_promotion_eligibility import PromotionGap, check_promotion_eligibility  # noqa: E402
from export_runtime_pack import parse_args as parse_export_runtime_pack_args  # noqa: E402
import run_workflow as run_workflow_module  # noqa: E402
from formal_result_fixtures import write_formal_result_bundle  # noqa: E402
from paper_candidate_fixtures import write_valid_paper_candidate  # noqa: E402


def _write_material_manifest(materials: Path, problem_id: str, files: dict[str, list[tuple[str, bytes]]]) -> None:
    """Helper: write a valid material_manifest.json with SHA-256 hashes for the given files."""
    categories: dict[str, dict[str, object]] = {}
    for cat_name, cat_files in files.items():
        cat_entries: list[dict[str, str]] = []
        for fname, fdata in cat_files:
            cat_entries.append({"path": fname, "sha256": hashlib.sha256(fdata).hexdigest()})
        categories[cat_name] = {"required": True, "files": cat_entries}

    manifest = {
        "manifest_version": "1.0.0",
        "problem_id": problem_id,
        "material_root": ".",
        "source": {"kind": "official", "reference": "https://example.com"},
        "contains_answer_or_solution": False,
        "categories": {
            "problem": categories.get("problem", {"required": True, "files": []}),
            "attachments": categories.get("attachments", {"required": False, "files": []}),
            "templates": categories.get("templates", {"required": False, "files": []}),
        },
    }
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")


def _write_minimal_run_binding(
    run_dir: Path,
    *,
    run_id: str = "test_run",
    problem_id: str = "2024-C",
    profile: str = "engineering_optimization",
    runtime_version: str = "0.1.0",
    runtime_pack: bytes = b"test runtime pack",
) -> None:
    """写入 Gate 5 绑定测试所需的最小、真实哈希运行现场。"""
    (run_dir / "runtime_pack.md").write_bytes(runtime_pack)
    runtime_pack_sha = hashlib.sha256(runtime_pack).hexdigest()
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "2.0.0",
                "run_id": run_id,
                "workflow": "full_replay",
                "evidence_purpose": "training_validation",
                "problem_id": problem_id,
                "profile": profile,
                "runtime_version": runtime_version,
                "runtime_pack_sha256": runtime_pack_sha,
                "formal_result_policy": "required_v1",
                "execution_contract_version": "1.0.0",
                "formal_result_contract_version": "1.0.0",
                "canonicalization_version": "1.0.0",
                "gate_artifact_contract_version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "runtime_pack.manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "1.2.0",
                "profile": profile,
                "runtime_version": runtime_version,
                "runtime_pack_sha256": runtime_pack_sha,
                "workflow_context": "full_replay",
                "runtime_contract": {
                    "path": RUNTIME_CONTRACTS["full_replay"],
                    "sha256": hashlib.sha256(
                        (ROOT / RUNTIME_CONTRACTS["full_replay"]).read_bytes()
                    ).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )


def _gate_5_review(run_dir: Path, reviewer: str = "human") -> dict[str, object]:
    """从运行现场生成仅用于测试的完整 Gate 5 审核记录。"""
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    runtime_manifest = json.loads(
        (run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8")
    )
    return {
        "run_id": run_manifest["run_id"],
        "problem_id": run_manifest["problem_id"],
        "profile": run_manifest["profile"],
        "runtime_version": run_manifest["runtime_version"],
        "runtime_pack_sha256": runtime_manifest["runtime_pack_sha256"],
        "target_gate": 5,
        "reviewer": reviewer,
        "reviewed_at": "2026-07-11T00:00:00Z",
        "decision": "approved",
        "final_acceptance": True,
        "reason": "The final Gate 5 review is complete and approved.",
        "checklist": {key: True for key in GATE_5_CHECKLIST_KEYS},
    }


def _write_valid_gate_artifact(run_dir: Path, gate: int) -> None:
    """写入最小但具备业务含义的 Gate 0-4 产物及对应哈希清单。"""
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    runtime_manifest = json.loads(
        (run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8")
    )
    if (
        gate == 3
        and run_manifest.get("formal_result_policy") == "required_v1"
        and not any(run_dir.glob("formal_results/*/formal_result_envelope.json"))
    ):
        write_formal_result_bundle(run_dir)
    binding = {
        "schema_version": "1.0.0",
        "run_id": run_manifest["run_id"],
        "problem_id": run_manifest["problem_id"],
        "profile": run_manifest["profile"],
        "runtime_version": run_manifest["runtime_version"],
        "runtime_pack_sha256": runtime_manifest["runtime_pack_sha256"],
    }
    runtime_pack_sha = runtime_manifest["runtime_pack_sha256"]
    payloads: dict[int, list[tuple[str, dict[str, object]]]] = {
        0: [
            (
                "diagnosis.json",
                {
                    **binding,
                    "artifact_type": "diagnosis",
                    "problem_summary": "This fixture identifies the mathematical task and its evidence boundary.",
                    "material_findings": ["All declared problem materials passed hash checks."],
                    "objectives": ["Produce a reproducible and reviewable mathematical result."],
                    "constraints": ["Use only the frozen input materials."],
                    "risks": ["Unsupported assumptions may invalidate downstream claims."],
                },
            )
        ],
        1: [
            (
                "model_route.json",
                {
                    **binding,
                    "artifact_type": "model_route",
                    "selected_route": "Use a deterministic baseline followed by constrained validation.",
                    "alternatives": ["A stochastic alternative was considered and rejected."],
                    "assumptions": ["The frozen input data is representative of the stated task."],
                    "validation_plan": ["Compare outputs against the declared constraints."],
                },
            )
        ],
        2: [
            (
                "code_plan.json",
                {
                    **binding,
                    "artifact_type": "code_plan",
                    "commands": ["python solve.py --input frozen.json"],
                    "modules": ["solve.py implements the declared model route."],
                    "inputs": ["frozen.json"],
                    "outputs": ["result.json"],
                    "verification_steps": ["Re-run the command and compare output hashes."],
                },
            )
        ],
        3: [
            (
                "result_report.json",
                {
                    **binding,
                    "artifact_type": "result_report",
                    "conclusions": ["The configured fixture checks completed successfully."],
                    "metrics": [
                        {"name": "fixture_score", "value": 1.0, "unit": None, "source": "result.json"}
                    ],
                    "limitations": ["This fixture result is not a universal correctness claim."],
                    "model_contract": {
                        "model_type": "descriptive",
                        "variables": [
                            {
                                "name": "x",
                                "definition": "Fixture decision value.",
                                "unit": "1",
                                "source": "problem statement",
                            }
                        ],
                        "parameters": [
                            {
                                "name": "p",
                                "definition": "Fixture parameter.",
                                "unit": "1",
                                "source": "frozen input",
                            }
                        ],
                        "formulas": [
                            {"formula_id": "F1", "expression": "x + p", "symbols": ["x", "p"]}
                        ],
                        "objectives": ["Explain the fixture result."],
                        "constraints": ["x must remain finite."],
                        "boundary_conditions": ["x equals zero at the fixture boundary."],
                        "unit_checks": [{"expression": "x + p", "compatible": True}],
                        "claim_result_bindings": [
                            {"claim_id": "C001", "metric": "fixture_score"}
                        ],
                        "optimization_checks": {
                            "configured": [],
                            "passed": [],
                            "not_applicable": {},
                        },
                    },
                },
            ),
            (
                "result_manifest.json",
                {
                    **binding,
                    "artifact_type": "result_manifest",
                    "executions": [
                        {
                            "command": "python solve.py --input frozen.json",
                            "exit_code": 0,
                            "outputs": [{"path": "runtime_pack.md", "sha256": runtime_pack_sha}],
                        }
                    ],
                    "inputs": [{"path": "runtime_pack.md", "sha256": runtime_pack_sha}],
                    "outputs": [{"path": "runtime_pack.md", "sha256": runtime_pack_sha}],
                    "environment": {
                        "python": "3.12",
                        "os": "test",
                        "solver": None,
                        "git_sha": "abcdef0",
                        "dependencies": ["jsonschema==4"],
                    },
                    "random_seeds": [0],
                    "tolerances": {"absolute": 0.0},
                    "deterministic_expected": True,
                    "repeated_runs": [
                        {
                            "execution_id": "fixture-repeat-1",
                            "seed": 0,
                            "started_at": "2026-07-11T00:00:00Z",
                            "completed_at": "2026-07-11T00:00:01Z",
                            "exit_code": 0,
                            "output_sha256": runtime_pack_sha,
                            "stdout_sha256": runtime_pack_sha,
                            "environment_sha256": runtime_pack_sha,
                        },
                        {
                            "execution_id": "fixture-repeat-2",
                            "seed": 0,
                            "started_at": "2026-07-11T00:00:02Z",
                            "completed_at": "2026-07-11T00:00:03Z",
                            "exit_code": 0,
                            "output_sha256": runtime_pack_sha,
                            "stdout_sha256": runtime_pack_sha,
                            "environment_sha256": runtime_pack_sha,
                        },
                    ],
                },
            ),
        ],
        4: [
            (
                "paper_claim_map.json",
                {
                    **binding,
                    "artifact_type": "paper_claim_map",
                    "claims": [
                        {
                            "claim_id": "C001",
                            "claim": "The configured fixture execution completed successfully.",
                            "result_refs": ["result_report.json#/conclusions/0"],
                            "evidence_refs": ["result_manifest.json#/executions/0"],
                        }
                    ],
                },
            )
        ],
    }
    for filename, payload in payloads[gate]:
        (run_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
    if gate == 4 and run_manifest.get("paper_pipeline_contract_version") == "1.0.0":
        write_valid_paper_candidate(run_dir)
    if (
        gate == 3
        and run_manifest.get("gate_3_evidence_contract_version") == "1.0.0"
        and run_manifest.get("profile") == "engineering_optimization"
    ):
        _write_gate_3_fixture_evidence(run_dir)
    write_gate_artifact_manifest(run_dir, gate, completed_at="2026-07-11T00:00:00Z")


def _write_gate_3_fixture_evidence(run_dir: Path) -> None:
    """由父进程从当前 Run 固定工件生成输入并真实执行测试 Validator。"""
    execute_gate_3_validator(
        run_dir,
        "validators/gate3_evidence_fixture/gate_3_validator_contract.json",
        {
            "problem_data": ["problem_manifest.json"],
            "candidate_solution": ["result_report.json"],
            "model_parameters": ["runtime_profile.snapshot.json"],
            "solver_log": ["result_manifest.json"],
        },
    )


def _prepare_completed_gate_run(run_dir: Path, reviewer: str = "test_reviewer") -> None:
    """填充最小完整 Gate 0-5 现场，但不执行 Seal，供 workflow 契约测试复用。"""
    request_path = run_dir / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request.update({"prompt": "真实运行提示词", "model": "TestModel", "source": "real_ai_run"})
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    metadata_path = run_dir / "ai_run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update({"status": "completed", "provider": "test", "model": "TestModel"})
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    record_transition(run_dir, None, 0, reviewer, "approved")
    for gate in range(5):
        _write_valid_gate_artifact(run_dir, gate)
        record_transition(run_dir, gate, gate + 1, reviewer, "approved")
    (run_dir / "gate_5_review.json").write_text(
        json.dumps(_gate_5_review(run_dir, reviewer), ensure_ascii=False),
        encoding="utf-8",
    )
    write_gate_artifact_manifest(run_dir, 5, completed_at="2026-07-11T00:00:00Z")
    mark_run_completed(run_dir, reviewer)


def _ready_gate_5_run(
    parent: Path,
    name: str,
    *,
    run_id: str | None = None,
    problem_id: str = "2024-C",
) -> Path:
    """构造已按顺序到达 Gate 5、尚未完成的最小运行。"""
    run_dir = parent / name
    run_dir.mkdir()
    _write_minimal_run_binding(
        run_dir,
        run_id=run_id or name,
        problem_id=problem_id,
    )
    (run_dir / "transitions.jsonl").write_text(
        json.dumps(
            {
                "from": None,
                "to": None,
                "state": "initialized",
                "material_ready": True,
                "max_gate": 5,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for gate in range(6):
        record_transition(run_dir, gate - 1 if gate else None, gate, "human", "approved")
    return run_dir


def _v2_gate_0_run(parent: Path, name: str = "v2_run") -> Path:
    """构造已启动 Gate 0 的 v2 运行，用于语义完成契约负向测试。"""
    run_dir = parent / name
    run_dir.mkdir()
    _write_minimal_run_binding(run_dir, run_id=name)
    (run_dir / "gate_artifacts").mkdir()
    initialized = chain_transition_event(
        {
            "transition_version": TRANSITION_VERSION,
            "from": None,
            "to": None,
            "completed_gate": None,
            "next_gate": 0,
            "state": "initialized",
            "material_ready": True,
            "max_gate": 5,
            **{
                field: json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))[field]
                for field in (
                    "run_id", "problem_id", "profile", "runtime_version", "runtime_pack_sha256",
                    "formal_result_policy", "execution_contract_version", "formal_result_contract_version",
                    "canonicalization_version", "gate_artifact_contract_version",
                )
            },
        },
        None,
    )
    (run_dir / "transitions.jsonl").write_text(
        json.dumps(initialized) + "\n", encoding="utf-8"
    )
    record_transition(run_dir, None, 0, "human", "approved")
    return run_dir


def test_default_pack_excludes_candidate_patches() -> None:
    selected = select_patch_files("engineering_optimization")
    assert selected == []


def test_manifest_hashes_pack_and_records_exclusions() -> None:
    pack = build_pack("engineering_optimization", "full_replay")
    manifest = build_manifest("engineering_optimization", "full_replay", pack)
    assert manifest["runtime_pack_sha256"]
    assert manifest["runtime_contract"]["path"] == RUNTIME_CONTRACTS["full_replay"]
    assert manifest["workflow_context"] == "full_replay"
    assert manifest["validation_target_status"] is None
    assert manifest["patches"] == []
    assert {item["patch_id"] for item in manifest["excluded_patches"]} == {
        "A092", "A127", "B311", "B477"
    }
    # 新增：默认导出不启用实验标记
    assert manifest["candidate_experiment"]["enabled"] is False
    assert manifest["exclusion_experiment"]["enabled"] is False
    validator = RepositoryValidator()
    assert validator.validate_schema(manifest, "runtime_pack_manifest.schema.json", "真实 exporter manifest")


@pytest.mark.parametrize("profile", ["general", "engineering_optimization", "evaluation", "prediction"])
def test_runtime_pack_is_self_contained_and_binds_context_contract(profile: str) -> None:
    """每个 workflow 只编译自己的契约，且运行包不得要求读取仓库相对路径。"""
    for context, contract_path in RUNTIME_CONTRACTS.items():
        pack = build_pack(profile, context)
        manifest = build_manifest(profile, context, pack)
        assert "# ===== 编译版运行契约 =====" in pack
        assert manifest["workflow_context"] == context
        assert manifest["runtime_contract"]["path"] == contract_path
        assert manifest["runtime_contract"]["sha256"] == hashlib.sha256(
            (ROOT / contract_path).read_bytes()
        ).hexdigest()
        for other_path in set(RUNTIME_CONTRACTS.values()) - {contract_path}:
            assert (ROOT / other_path).read_text(encoding="utf-8") not in pack
    for forbidden in (
        "请读取 docs/",
        "请读取 prompt_base/",
        "请读取 prompt_plugins/",
        "请读取当前 plugin",
        "请读取当前 patch",
        "请读取 checklists/",
    ):
        assert forbidden not in pack


def test_hashed_runtime_fixtures_keep_lf_bytes_after_checkout() -> None:
    """Git checkout 不得把受 SHA-256 绑定的运行包改写为 CRLF。"""
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.md text eol=lf" in attributes
    for runtime_pack in (ROOT / "tests" / "fixtures").glob("**/runtime_pack.md"):
        assert b"\r\n" not in runtime_pack.read_bytes(), runtime_pack


def test_build_identity_is_independent_from_generation_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = build_pack("engineering_optimization", "full_replay")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1704067200")
    first = build_manifest("engineering_optimization", "full_replay", pack)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1711929600")
    second = build_manifest("engineering_optimization", "full_replay", pack)

    assert first["generated_at"] != second["generated_at"]
    assert first["build_identity"] == second["build_identity"]
    changed = build_manifest("engineering_optimization", "full_replay", pack + "\nchanged")
    assert changed["build_identity"] != first["build_identity"]


def test_formal_export_rejects_unverified_handwritten_patch_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forged_patch = {
        "patch_id": "A999",
        "status": "regression_verified",
        "file": "prompt_patches/patch_A092_engineering_optimization.md",
        "runtime_profiles": ["engineering_optimization"],
        "validation_records": [],
    }
    monkeypatch.setattr("export_runtime_pack.read_patch_index", lambda: [forged_patch])

    with pytest.raises(ValueError, match="现场证据"):
        select_patches("engineering_optimization")


@pytest.mark.skip(reason="旧 Profile 人工计数契约已由 test_profile_derivation.py 取代")
def test_stable_profile_schema_requires_competition_validation() -> None:
    """Profile 标记 stable 时必须同时声明比赛验证完成。"""
    profile = json.loads((ROOT / "runtime_profiles" / "general.json").read_text(encoding="utf-8"))
    profile.update(
        {
            "maturity": "competition_evidenced",
            "competition_verified": False,
            "validation_level": "cross_mechanism",
        }
    )
    validator = RepositoryValidator()
    assert not validator.validate_schema(profile, "runtime_profile.schema.json", "伪造 stable profile")
    assert any("True was expected" in failure for failure in validator.failures)


@pytest.mark.skip(reason="旧 verified_patches 缓存已删除")
def test_stable_profile_rejects_non_stable_patch() -> None:
    """Stable Profile 只能导入已具备 Stable Evidence 的 patch。"""
    profile = json.loads((ROOT / "runtime_profiles" / "general.json").read_text(encoding="utf-8"))
    profile.update(
        {
            "maturity": "competition_evidenced",
            "competition_verified": True,
            "validation_level": "competition_verified",
            "verified_patches": ["A092"],
        }
    )
    validator = RepositoryValidator()
    real_load = RepositoryValidator().load_json

    def load_json(path: str):
        if str(path).replace("\\", "/") == "runtime_profiles/general.json":
            return profile
        return real_load(path)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(validator, "load_json", load_json)
        validator.validate_profiles()
    assert any("stable profile 只能导入 stable patch" in failure for failure in validator.failures)


@pytest.mark.skip(reason="旧 Profile 人工计数契约已删除")
def test_stable_profile_requires_evidence_level_requirements() -> None:
    """完整状态字段不能替代 Gate、负控、比赛证据和失败清理。"""
    profile = json.loads((ROOT / "runtime_profiles" / "general.json").read_text(encoding="utf-8"))
    profile.update(
        {
            "maturity": "competition_evidenced",
            "competition_verified": True,
            "validation_level": "competition_verified",
            "verified_patches": [],
            "known_failures": ["仍有未关闭问题"],
        }
    )
    profile["validation"].update(
        {
            "gate_0_5": 0,
            "negative_control": 0,
            "evidence": [],
        }
    )
    validator = RepositoryValidator()
    real_load = RepositoryValidator().load_json

    def load_json(path: str):
        if str(path).replace("\\", "/") == "runtime_profiles/general.json":
            return profile
        return real_load(path)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(validator, "load_json", load_json)
        validator.validate_profiles()

    expected_messages = (
        "至少需要 1 个 stable patch",
        "gate_0_5 至少需要",
        "negative_control 至少需要",
        "validation.evidence 不能为空",
        "competition_validation_records 至少需要",
        "known_failures 必须为空",
    )
    for message in expected_messages:
        assert any(message in failure for failure in validator.failures)


def _validate_stable_profile_competition_fixture(
    tmp_path: Path,
    *,
    candidate_patch_ids: list[str] | None = None,
    exclude_patch_ids: list[str] | None = None,
    mutate_manifest=None,
    tamper_result_after_binding: bool = False,
) -> RepositoryValidator:
    """构造 Profile Stable 比赛证据并返回完成校验的 validator。"""
    candidate_patch_ids = candidate_patch_ids or []
    exclude_patch_ids = exclude_patch_ids or []
    pack = build_pack(
        "engineering_optimization", "full_replay", candidate_patch_ids, exclude_patch_ids
    )
    runtime_manifest = build_manifest(
        "engineering_optimization",
        "full_replay",
        pack,
        candidate_patch_ids,
        exclude_patch_ids,
    )
    runtime_manifest["maturity"] = "competition_evidenced"
    for patch_entry in runtime_manifest["patches"]:
        if patch_entry["patch_id"] in {"A092", "A127"}:
            patch_entry["status"] = "competition_evidenced"
    if mutate_manifest is not None:
        mutate_manifest(runtime_manifest)
    runtime_manifest_path = tmp_path / "runtime_pack.manifest.json"
    runtime_manifest_path.write_text(json.dumps(runtime_manifest), encoding="utf-8")
    runtime_manifest_sha = hashlib.sha256(runtime_manifest_path.read_bytes()).hexdigest()
    result_path = tmp_path / "result_record.json"
    result = {
        "result": "pass",
        "runtime_pack_manifest": "fixture/runtime_pack.manifest.json",
        "runtime_pack_manifest_sha256": runtime_manifest_sha,
    }
    result_path.write_text(json.dumps(result), encoding="utf-8")
    result_record_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()

    profile = json.loads(
        (ROOT / "runtime_profiles" / "engineering_optimization.json").read_text(encoding="utf-8")
    )
    profile.update(
        {
            "maturity": "competition_evidenced",
            "competition_verified": True,
            "validation_level": "competition_verified",
            "verified_patches": ["A092", "A127"],
        }
    )
    profile["validation"].update(
        {
            "gate_0_5": 1,
            "negative_control": 2,
            "competition_validation_records": [
                {
                    "runtime_pack_manifest": "fixture/runtime_pack.manifest.json",
                    "runtime_pack_manifest_sha256": runtime_manifest_sha,
                    "result_record": "fixture/result_record.json",
                    "result_record_sha256": result_record_sha,
                }
            ],
        }
    )
    if tamper_result_after_binding:
        result["comments"] = "tampered after profile approval"
        result_path.write_text(json.dumps(result), encoding="utf-8")
    patches = json.loads((ROOT / "prompt_patches" / "patch_index.json").read_text(encoding="utf-8"))
    for patch in patches:
        if patch["patch_id"] in {"A092", "A127"}:
            patch["status"] = "competition_evidenced"

    validator = RepositoryValidator()
    real_load = RepositoryValidator().load_json

    def load_json(path: str):
        normalized = str(path).replace("\\", "/")
        if normalized == "runtime_profiles/engineering_optimization.json":
            return profile
        if normalized == "prompt_patches/patch_index.json":
            return patches
        return real_load(path)

    def resolve_repo_path(self, raw: str) -> Path:
        if raw == "fixture/runtime_pack.manifest.json":
            return runtime_manifest_path
        if raw == "fixture/result_record.json":
            return result_path
        return RepositoryValidator().resolve_repo_path(raw)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(validator, "load_json", load_json)
        monkeypatch.setattr(validator, "resolve_repo_path", resolve_repo_path.__get__(validator))
        validator.validate_profiles()
    return validator


@pytest.mark.skip(reason="比赛证据改由结构化 validation_records 现场派生")
def test_stable_profile_validates_competition_evidence_records(tmp_path: Path) -> None:
    """Stable Profile 的比赛状态必须由真实运行包和通过的结果记录证明。"""
    validator = _validate_stable_profile_competition_fixture(tmp_path)
    assert not validator.failures


@pytest.mark.skip(reason="比赛证据改由结构化 validation_records 现场派生")
def test_stable_profile_rejects_candidate_experiment_and_extra_patch(tmp_path: Path) -> None:
    """包含额外 candidate Patch 的实验包不能证明正式 Stable Profile。"""
    validator = _validate_stable_profile_competition_fixture(
        tmp_path,
        candidate_patch_ids=["B311"],
    )
    assert any("Patch 集合不一致" in failure and "B311" in failure for failure in validator.failures)
    assert any("不得来自 candidate experiment" in failure for failure in validator.failures)


@pytest.mark.skip(reason="比赛证据改由结构化 validation_records 现场派生")
def test_stable_profile_rejects_exclusion_experiment(tmp_path: Path) -> None:
    """排除正式 Patch 的隔离实验不能作为 Stable Profile 比赛证据。"""
    validator = _validate_stable_profile_competition_fixture(
        tmp_path,
        exclude_patch_ids=["A127"],
    )
    assert any("Patch 集合不一致" in failure and "A127" in failure for failure in validator.failures)
    assert any("不得来自 exclusion experiment" in failure for failure in validator.failures)


@pytest.mark.skip(reason="比赛证据改由结构化 validation_records 现场派生")
def test_stable_profile_verifies_manifest_patch_content(tmp_path: Path) -> None:
    """Manifest 中的 Patch 状态、路径和 SHA-256 必须与当前 Stable Patch 一致。"""
    def mutate_manifest(manifest: dict[str, object]) -> None:
        patch_entry = next(
            item for item in manifest["patches"] if item["patch_id"] == "A092"
        )
        patch_entry["status"] = "review_ready"
        patch_entry["path"] = "prompt_patches/patch_A127_engineering_layout_optimization.md"
        patch_entry["sha256"] = "0" * 64

    validator = _validate_stable_profile_competition_fixture(
        tmp_path,
        mutate_manifest=mutate_manifest,
    )
    assert any("Patch A092 status 必须为 stable" in failure for failure in validator.failures)
    assert any("Patch A092 path 与 patch_index.file 不一致" in failure for failure in validator.failures)
    assert any("Patch A092 sha256 与当前文件不一致" in failure for failure in validator.failures)


@pytest.mark.skip(reason="比赛证据改由结构化 validation_records 现场派生")
def test_stable_profile_binds_result_record_sha256(tmp_path: Path) -> None:
    """Profile 批准后改写 result record 必须被内容哈希检测。"""
    validator = _validate_stable_profile_competition_fixture(
        tmp_path,
        tamper_result_after_binding=True,
    )
    assert any("result_record SHA-256 不匹配" in failure for failure in validator.failures)


def test_verified_patches_and_condition_prevents_dangling_verified_export() -> None:
    """regression_verified/stable 但未进入 verified_patches 的 patch 不得进入正式包。
    当前 A092/A127 都在 verified_patches，故默认应包含；本测试确认 AND 条件不误伤已批准 patch。"""
    selected = select_patches("engineering_optimization")
    assert selected == []


def test_candidate_patch_explicit_import() -> None:
    """显式 --candidate-patch B311 才会导入 candidate；不会一次导入全部 candidate。"""
    selected = select_patches("engineering_optimization", candidate_patch_ids=["B311"])
    ids = {p["patch_id"] for p in selected}
    assert "B311" in ids
    assert "B477" not in ids  # 不会一次导入全部 candidate
    assert ids == {"B311"}


def test_exclude_patch_isolation_runs() -> None:
    """隔离实验：baseline / A092-only / A127-only。"""
    baseline = select_patches("engineering_optimization", exclude_patch_ids=["A092", "A127"])
    assert [p["patch_id"] for p in baseline] == []
    assert select_patches("engineering_optimization", exclude_patch_ids=["A127"]) == []
    assert select_patches("engineering_optimization", exclude_patch_ids=["A092"]) == []


def test_prompt_response_evaluator_field_level_forbidden() -> None:
    """字段级 forbidden_values：只检查指定字段，不误判解释/拒绝理由中的禁止词。"""
    case = {
        "expected": {
            "values": {"primary_type": "evaluation"},
            "must_have_paths": ["constraints.budget"],
            "forbidden_values": {
                "selected_models": ["neural_network", "genetic_algorithm"],
                "subproblems": ["空间布局"],
            },
            "patch_not_applicable": {"A092": False, "A127": False},
            "requires_manual_confirmation": True,
        }
    }
    response = {
        "primary_type": "evaluation",
        "subproblems": ["建立评价体系", "排序方案"],
        "selected_models": ["linear_programming"],
        "constraints": {"budget": "不超过 100 万元"},
        "patch_decisions": {
            "A092": {"enabled": False, "applicable": False, "reason": "评价排序题无需工程优化机制"},
            "A127": {"enabled": False, "applicable": False, "reason": "无空间布局需求"},
        },
        "rejected_models": [
            {"model": "neural_network", "reason": "数据不足且无必要"}
        ],
        "manual_confirmation": ["确认评价口径"],
        "free_text": "先定义变量和约束。",
    }
    # 正确拒绝 neural_network（在 rejected_models.reason 中）不应触发失败
    assert evaluate_case(case, response) == []


def test_prompt_response_evaluator_catches_field_forbidden_violation() -> None:
    """forbidden_values 命中指定字段才失败；仍兼容旧 must_not_contain。"""
    case = {
        "expected": {
            "forbidden_values": {"selected_models": ["neural_network"]},
        }
    }
    response = {"selected_models": ["neural_network"]}
    errors = evaluate_case(case, response)
    assert any("selected_models" in e for e in errors)


def test_prompt_response_evaluator_patch_not_applicable_check() -> None:
    """负控题：patch_decisions.A092.applicable 必须为 False 并给出理由。"""
    case = {"expected": {"patch_not_applicable": {"A092": False}}}
    bad = {"patch_decisions": {"A092": {"enabled": False, "applicable": True, "reason": ""}}}
    errors = evaluate_case(case, bad)
    assert any("A092" in e and "不适用" in e for e in errors)


def test_old_problem_cli_creates_traceable_run(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"fake problem pdf"
    xlsx_data = b"fake xlsx"
    (materials / "problem.pdf").write_bytes(pdf_data)
    (materials / "data.xlsx").write_bytes(xlsx_data)
    _write_material_manifest(
        materials,
        "2024-C",
        {"problem": [("problem.pdf", pdf_data)], "attachments": [("data.xlsx", xlsx_data)]},
    )
    args = Namespace(
            run_id="test_run",
            output_root=str(tmp_path / "runs"),
            problem="2024-C",
            profile="engineering_optimization",
            gates="0-2",
            materials=str(materials),
            candidate_patch=[],
            exclude_patch=[],
            material_file=[],
            promotion_evidence=False,
            experiment_group_id=None,
            experiment_role=None,
            target_patch=None
        )
    run_dir, ready = create_old_problem_run(args)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert ready is True
    assert "automatic_stable_update" not in manifest
    assert manifest["experiment_kind"] == "standard"
    assert manifest["manifest_version"] == "2.0.0"
    assert manifest["initial_state"] == "initialized"
    assert (run_dir / "runtime_pack.manifest.json").is_file()
    assert (run_dir / "patch_suggestions.md").is_file()
    # 新增：problem_manifest 记录材料文件哈希
    pm = json.loads((run_dir / "problem_manifest.json").read_text(encoding="utf-8"))
    assert pm["problem_id"] == "2024-C"
    assert len(pm["files"]) == 2
    assert all("sha256" in f and "size" in f for f in pm["files"])
    # 新增：证据文件脚手架
    assert (run_dir / "diagnosis.json").is_file()
    assert (run_dir / "request.json").is_file()
    assert (run_dir / "response.json").is_file()
    assert (run_dir / "automatic_evaluation.json").is_file()
    assert (run_dir / "human_review.md").is_file()
    metadata = json.loads((run_dir / "ai_run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "pending"
    assert metadata["provider"] is None
    validator = RepositoryValidator()
    assert validator.validate_schema(metadata, "ai_run_metadata.schema.json", "pending metadata")
    evidence_manifest = json.loads((run_dir / "run_evidence_manifest.json").read_text(encoding="utf-8"))
    assert validator.validate_schema(evidence_manifest, "run_evidence_manifest.schema.json", "run evidence manifest")
    assert {item["role"] for item in evidence_manifest["artifacts"]} >= {
        "run_manifest", "request", "model_response", "runtime_pack", "runtime_pack_manifest",
        "problem_manifest", "automatic_evaluation", "ai_run_metadata", "human_review", "transitions",
        "gate_5_review", "score", "failure_labels",
    }


def test_new_problem_initialization_uses_competition_artifacts_only(tmp_path: Path) -> None:
    """比赛 Run 共享 Gate 基础产物，但不得混入旧题训练与晋级文件。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"competition problem"
    attachment = b"competition attachment"
    (materials / "problem.pdf").write_bytes(problem)
    (materials / "data.xlsx").write_bytes(attachment)
    _write_material_manifest(
        materials,
        "2026-A",
        {"problem": [("problem.pdf", problem)], "attachments": [("data.xlsx", attachment)]},
    )
    common = {
        "run_id": "competition_run",
        "output_root": str(tmp_path / "runs"),
        "problem": "2026-A",
        "profile": "general",
        "gates": "0-5",
        "materials": str(materials),
        "candidate_patch": [],
        "exclude_patch": [],
        "material_file": [],
        "promotion_evidence": False,
        "experiment_group_id": None,
        "experiment_role": None,
        "target_patch": None,
        "workflow": "new_problem",
        "mode": "standard",
    }
    run_dir, ready = create_new_problem_run(Namespace(**common))

    assert ready is True
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["workflow"] == "new_problem"
    assert manifest["evidence_purpose"] == "competition_execution"
    assert not (run_dir / "score.json").exists()
    assert not (run_dir / "failure_labels.json").exists()
    assert not (run_dir / "patch_suggestions.md").exists()
    assert (run_dir / "competition_process_review.md").is_file()
    for shared in (
        "runtime_pack.md",
        "runtime_pack.manifest.json",
        "runtime_profile.snapshot.json",
        "patch_selection.snapshot.json",
        "problem_manifest.json",
        "transitions.jsonl",
        "ai_run_metadata.json",
        "run_evidence_manifest.json",
    ):
        assert (run_dir / shared).is_file()
    execution_plan = (run_dir / "execution_plan.md").read_text(encoding="utf-8")
    forbidden_training_terms = ("T0", "T4", "M1", "M5", "P1", "P10", "旧题闭环", "晋级计数")
    assert not any(term in execution_plan for term in forbidden_training_terms)
    evidence = json.loads((run_dir / "run_evidence_manifest.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in evidence["artifacts"]}
    assert "competition_process_review" in roles
    assert "score" not in roles
    assert "failure_labels" not in roles


def test_new_problem_seals_without_training_artifacts_and_never_promotes(tmp_path: Path) -> None:
    """比赛运行可独立完整封存，且现场派生的晋级资格恒为 false。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"competition problem"
    (materials / "problem.pdf").write_bytes(problem)
    _write_material_manifest(materials, "2026-B", {"problem": [("problem.pdf", problem)]})
    args = Namespace(
        run_id="sealed_competition",
        output_root=str(tmp_path / "runs"),
        problem="2026-B",
        profile="general",
        gates="0-5",
        materials=str(materials),
        candidate_patch=[],
        exclude_patch=[],
        material_file=[],
        promotion_evidence=False,
        experiment_group_id=None,
        experiment_role=None,
        target_patch=None,
        workflow="new_problem",
        mode="standard",
    )
    run_dir, ready = create_new_problem_run(args)
    assert ready is True
    _prepare_completed_gate_run(run_dir)

    report = complete_and_seal_run(run_dir, "test_reviewer")
    assert report["completed"] is True
    assert report["sealed"] is True
    assert report["eligible_for_promotion"] is False
    assert not (run_dir / "score.json").exists()
    assert not (run_dir / "failure_labels.json").exists()
    assert not (run_dir / "patch_suggestions.md").exists()

    (run_dir / "competition_process_review.md").unlink()
    assert verify_run(run_dir)["sealed"] is False


def test_workflow_and_evidence_purpose_cannot_be_relabelled(tmp_path: Path) -> None:
    """比赛目录即使同时改 workflow 与 evidence_purpose，也缺少训练合同而不能通过 verify。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"competition problem"
    (materials / "problem.pdf").write_bytes(problem)
    _write_material_manifest(materials, "2026-C", {"problem": [("problem.pdf", problem)]})
    args = Namespace(
        run_id="relabeled_competition",
        output_root=str(tmp_path / "runs"),
        problem="2026-C",
        profile="general",
        gates="0-5",
        materials=str(materials),
        candidate_patch=[],
        exclude_patch=[],
        material_file=[],
        promotion_evidence=False,
        experiment_group_id=None,
        experiment_role=None,
        target_patch=None,
        workflow="new_problem",
        mode="standard",
    )
    run_dir, _ready = create_new_problem_run(args)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workflow"] = "full_replay"
    manifest["evidence_purpose"] = "training_validation"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = verify_run(run_dir)
    assert report["sealed"] is False
    assert any("workflow_context" in error for error in report["promotion_readiness_errors"])


def test_full_replay_seal_requires_training_specific_artifacts(tmp_path: Path) -> None:
    """旧题训练运行缺少评分文件时，完成态不得借用比赛合同完成 Seal。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"training problem"
    (materials / "problem.pdf").write_bytes(problem)
    _write_material_manifest(materials, "2024-D", {"problem": [("problem.pdf", problem)]})
    args = Namespace(
        run_id="missing_training_artifact",
        output_root=str(tmp_path / "runs"),
        problem="2024-D",
        profile="general",
        gates="0-5",
        materials=str(materials),
        candidate_patch=[],
        exclude_patch=[],
        material_file=[],
        promotion_evidence=False,
        experiment_group_id=None,
        experiment_role=None,
        target_patch=None,
        workflow="full_replay",
        mode="standard",
    )
    run_dir, ready = create_full_replay_run(args)
    assert ready is True
    _prepare_completed_gate_run(run_dir)
    (run_dir / "score.json").unlink()

    with pytest.raises(ValueError, match="score.json"):
        complete_and_seal_run(run_dir, "test_reviewer")


@pytest.mark.parametrize("workflow", ["full_replay", "new_problem"])
def test_gate_workflows_fail_closed_without_material_manifest(tmp_path: Path, workflow: str) -> None:
    """两个 Gate 流程都必须将缺失的机器材料清单派生为阻断状态。"""
    materials = tmp_path / workflow
    materials.mkdir()
    (materials / "problem.pdf").write_bytes(b"unlisted problem")
    args = Namespace(
        run_id=f"missing_manifest_{workflow}",
        output_root=str(tmp_path / "runs"),
        problem="2026-A",
        profile="general",
        gates="0-5",
        materials=str(materials),
        candidate_patch=[],
        exclude_patch=[],
        material_file=[],
        promotion_evidence=False,
        experiment_group_id=None,
        experiment_role=None,
        target_patch=None,
        workflow=workflow,
        mode="standard",
    )
    creator = create_full_replay_run if workflow == "full_replay" else create_new_problem_run
    run_dir, ready = creator(args)
    assert ready is False
    state = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert state["initial_state"] == "blocked"


def test_automatic_run_id_is_unique_and_new_problem_defaults_to_general(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同秒同题连续创建比赛 Run 时，随机尾缀必须避免覆盖且默认 Profile 为 general。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"competition problem"
    (materials / "problem.pdf").write_bytes(problem)
    _write_material_manifest(materials, "2026-A", {"problem": [("problem.pdf", problem)]})
    monkeypatch.setattr(
        run_workflow_module,
        "_run_id_clock",
        lambda: datetime(2026, 7, 12, 15, 30, 45),
    )
    tokens = iter(("a31f2c", "b42e3d"))
    monkeypatch.setattr(run_workflow_module, "_run_id_token", lambda: next(tokens))
    common = {
        "run_id": None,
        "output_root": str(tmp_path / "runs"),
        "problem": "2026-A",
        "profile": None,
        "gates": "0-5",
        "materials": str(materials),
        "candidate_patch": [],
        "exclude_patch": [],
        "material_file": [],
        "promotion_evidence": False,
        "experiment_group_id": None,
        "experiment_role": None,
        "target_patch": None,
        "workflow": "new_problem",
        "mode": "standard",
    }

    first, first_ready = create_new_problem_run(Namespace(**common))
    second, second_ready = create_new_problem_run(Namespace(**common))
    assert first_ready is True and second_ready is True
    assert first.name == "20260712_153045_2026-A_new_problem_general_a31f2c"
    assert second.name == "20260712_153045_2026-A_new_problem_general_b42e3d"
    assert json.loads((first / "run_manifest.json").read_text(encoding="utf-8"))["profile"] == "general"


def test_profile_requirements_and_explicit_run_id_collisions_fail_closed(tmp_path: Path) -> None:
    """训练与回归必须显式 Profile，重复显式 Run ID 和未知 Profile 均不得覆盖。"""
    with pytest.raises(ValueError, match="full_replay 必须显式提供 --profile"):
        create_full_replay_run(Namespace(profile=None))
    with pytest.raises(ValueError, match="prompt_regression 必须显式提供 --profile"):
        create_prompt_regression_run(Namespace(profile=None))
    with pytest.raises(FileNotFoundError, match="runtime profile"):
        run_workflow_module.resolve_profile_for_workflow(Namespace(profile="unknown"), "new_problem")

    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"competition problem"
    (materials / "problem.pdf").write_bytes(problem)
    _write_material_manifest(materials, "2026-A", {"problem": [("problem.pdf", problem)]})
    args = Namespace(
        run_id="explicit_run",
        output_root=str(tmp_path / "runs"),
        problem="2026-A",
        profile="general",
        gates="0-5",
        materials=str(materials),
        candidate_patch=[],
        exclude_patch=[],
        material_file=[],
        promotion_evidence=False,
        experiment_group_id=None,
        experiment_role=None,
        target_patch=None,
        workflow="new_problem",
        mode="standard",
    )
    create_new_problem_run(args)
    with pytest.raises(FileExistsError, match="运行目录已存在"):
        create_new_problem_run(Namespace(**vars(args)))


@pytest.mark.parametrize("run_id", ["", "../escaped", "nested/run", "C:/absolute-run", "CON"])
def test_explicit_run_id_cannot_escape_output_root(tmp_path: Path, run_id: str) -> None:
    """显式 Run ID 只能是单段安全标识，不能改变输出目录解析结果。"""
    args = Namespace(
        run_id=run_id,
        output_root=str(tmp_path / "runs"),
        problem="2026-A",
        profile="general",
        gates="0-5",
        materials=str(tmp_path / "missing-materials"),
        candidate_patch=[],
        exclude_patch=[],
        material_file=[],
        promotion_evidence=False,
        experiment_group_id=None,
        experiment_role=None,
        target_patch=None,
        workflow="new_problem",
        mode="standard",
    )

    with pytest.raises(ValueError, match="Run ID"):
        create_new_problem_run(args)


def _forkable_general_run(tmp_path: Path) -> Path:
    """构造已进入 Gate 0 且产物已绑定的 general 比赛父 Run。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"competition problem"
    (materials / "problem.pdf").write_bytes(problem)
    _write_material_manifest(materials, "2026-F", {"problem": [("problem.pdf", problem)]})
    parent, ready = create_new_problem_run(
        Namespace(
            run_id="fork_parent",
            output_root=str(tmp_path / "runs"),
            problem="2026-F",
            profile="general",
            gates="0-5",
            materials=str(materials),
            candidate_patch=[],
            exclude_patch=[],
            material_file=[],
            promotion_evidence=False,
            experiment_group_id=None,
            experiment_role=None,
            target_patch=None,
            workflow="new_problem",
            mode="standard",
        )
    )
    assert ready is True
    advance_run(parent, "reviewer")
    _write_valid_gate_artifact(parent, 0)
    return parent


def _interrupt_fork_after_child_move(
    parent: Path,
    monkeypatch: pytest.MonkeyPatch,
    transaction_id: str,
) -> tuple[Path, dict[str, object], Path]:
    """制造子目录已发布但事务状态仍为 prepared 的可恢复现场。"""
    original_write = run_workflow_module._write_fork_transaction

    def interrupt_after_child_move(path, transaction):
        if transaction.get("status") == "child_published":
            raise OSError("模拟子目录发布后的进程中断")
        original_write(path, transaction)

    monkeypatch.setattr(run_workflow_module, "_write_fork_transaction", interrupt_after_child_move)
    with pytest.raises(OSError, match="进程中断"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id=transaction_id,
        )
    monkeypatch.setattr(run_workflow_module, "_write_fork_transaction", original_write)

    transaction_path = parent.parent / ".transactions" / "fork-profile" / f"{transaction_id}.json"
    transaction = json.loads(transaction_path.read_text("utf-8"))
    child = parent.parent / str(transaction["child_run_id"])
    return transaction_path, transaction, child


def _interrupt_fork_before_child_move(
    parent: Path,
    monkeypatch: pytest.MonkeyPatch,
    transaction_id: str,
) -> tuple[Path, dict[str, object], Path, Path]:
    """制造事务已 prepared 但临时子目录尚未发布的可恢复现场。"""
    original_resume = run_workflow_module._resume_fork_transaction

    def interrupt_before_child_move(*_args, **_kwargs):
        raise OSError("模拟 prepared 事务落盘后的进程中断")

    monkeypatch.setattr(run_workflow_module, "_resume_fork_transaction", interrupt_before_child_move)
    with pytest.raises(OSError, match="进程中断"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id=transaction_id,
        )
    monkeypatch.setattr(run_workflow_module, "_resume_fork_transaction", original_resume)

    transaction_path = parent.parent / ".transactions" / "fork-profile" / f"{transaction_id}.json"
    transaction = json.loads(transaction_path.read_text("utf-8"))
    child_id = str(transaction["child_run_id"])
    staged_child = parent.parent / ".tmp" / f"fork-{transaction_id}-{child_id}" / child_id
    final_child = parent.parent / child_id
    return transaction_path, transaction, staged_child, final_child


def _interrupt_fork_after_parent_linked(
    parent: Path,
    monkeypatch: pytest.MonkeyPatch,
    transaction_id: str,
) -> tuple[Path, dict[str, object], Path]:
    """制造父事件与 parent_linked 已落盘、子记录尚未提交的恢复现场。"""
    original_commit = run_workflow_module._commit_child_fork_record

    def interrupt_child_commit(*_args, **_kwargs):
        raise OSError("模拟 parent_linked 后中断")

    monkeypatch.setattr(run_workflow_module, "_commit_child_fork_record", interrupt_child_commit)
    with pytest.raises(OSError, match="parent_linked"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id=transaction_id,
        )
    monkeypatch.setattr(run_workflow_module, "_commit_child_fork_record", original_commit)
    transaction_path = (
        parent.parent / ".transactions" / "fork-profile" / f"{transaction_id}.json"
    )
    transaction = json.loads(transaction_path.read_text("utf-8"))
    child = parent.parent / str(transaction["child_run_id"])
    return transaction_path, transaction, child


def test_fork_profile_commits_cross_bound_lineage_and_supersedes_parent(tmp_path: Path) -> None:
    """Fork 成功后父 Run 停止推进，子 Run 仅在 committed 谱系下可继续。"""
    parent = _forkable_general_run(tmp_path)
    result = fork_profile(
        parent,
        profile="engineering_optimization",
        reviewer="reviewer",
        reason="Gate 0 确认需要工程优化专项 Profile。",
        transaction_id="forktxn01",
    )
    child = Path(result["child_run"])

    assert result["status"] == "committed"
    parent_report = verify_run(parent)
    assert parent_report["lifecycle_status"] == "superseded"
    assert parent_report["superseded_by_run_id"] == child.name
    assert parent_report["current_gate"] == 0
    assert parent_report["advance_allowed"] is False
    assert parent_report["complete_allowed"] is False
    assert json.loads((child / "fork_record.json").read_text("utf-8"))["status"] == "committed"
    assert verify_run(child)["advance_allowed"] is True

    with pytest.raises(ValueError, match="superseded"):
        advance_run(parent, "reviewer")
    advance_run(child, "reviewer")
    assert replay_transition_log(child)["current_gate"] == 0


def test_committed_fork_child_tampering_blocks_reported_progress(tmp_path: Path) -> None:
    """已提交子 Run 的证据漂移必须使完整性与推进状态同时闭锁。"""
    parent = _forkable_general_run(tmp_path)
    result = fork_profile(
        parent,
        profile="engineering_optimization",
        reviewer="reviewer",
        reason="Gate 0 确认需要工程优化专项 Profile。",
        transaction_id="forktxn16",
    )
    child = Path(result["child_run"])
    (child / "diagnosis.json").write_text("{}\n", encoding="utf-8")

    report = verify_run(child)
    assert report["sealed"] is False
    assert report["advance_allowed"] is False
    assert any("diagnosis.json" in error for error in report["promotion_readiness_errors"])


def test_fork_profile_resumes_after_child_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """父事件写入失败后，--resume 必须复用同一子 Run 而非创建第二份。"""
    parent = _forkable_general_run(tmp_path)
    original_append = run_workflow_module._append_profile_fork_event

    def interrupted(*_args, **_kwargs):
        raise ValueError("模拟父事件写入中断")

    monkeypatch.setattr(run_workflow_module, "_append_profile_fork_event", interrupted)
    with pytest.raises(ValueError, match="中断"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn02",
        )
    transaction_path = parent.parent / ".transactions" / "fork-profile" / "forktxn02.json"
    interrupted_transaction = json.loads(transaction_path.read_text("utf-8"))
    assert interrupted_transaction["status"] == "child_published"
    child_before = interrupted_transaction["child_run_id"]
    with pytest.raises(ValueError, match="尚未 committed"):
        advance_run(parent.parent / child_before, "reviewer")

    monkeypatch.setattr(run_workflow_module, "_append_profile_fork_event", original_append)
    resumed = fork_profile(
        parent,
        profile="engineering_optimization",
        reviewer="reviewer",
        reason="Gate 0 确认需要工程优化专项 Profile。",
        transaction_id="forktxn02",
        resume=True,
    )
    assert Path(resumed["child_run"]).name == child_before
    assert resumed["status"] == "committed"


@pytest.mark.parametrize(
    ("tampered_file", "transaction_id", "error_pattern"),
    [
        ("diagnosis.json", "forktxn14_diagnosis", "diagnosis.json"),
        ("runtime_pack.md", "forktxn14_runtime", "runtime_pack.md"),
    ],
)
def test_fork_profile_resume_rejects_tampering_after_child_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tampered_file: str,
    transaction_id: str,
    error_pattern: str,
) -> None:
    """child_published 后子证据漂移时，不得 supersede 父 Run 或提交子 Run。"""
    parent = _forkable_general_run(tmp_path)
    original_append = run_workflow_module._append_profile_fork_event

    def interrupt_parent_link(*_args, **_kwargs):
        raise OSError("模拟 child_published 后中断")

    monkeypatch.setattr(run_workflow_module, "_append_profile_fork_event", interrupt_parent_link)
    with pytest.raises(OSError, match="child_published"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id=transaction_id,
        )
    monkeypatch.setattr(run_workflow_module, "_append_profile_fork_event", original_append)
    transaction_path = (
        parent.parent / ".transactions" / "fork-profile" / f"{transaction_id}.json"
    )
    transaction = json.loads(transaction_path.read_text("utf-8"))
    child = parent.parent / str(transaction["child_run_id"])
    assert transaction["status"] == "child_published"
    (child / tampered_file).write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error_pattern):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id=transaction_id,
            resume=True,
        )

    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "child_published"
    assert json.loads((child / "fork_record.json").read_text("utf-8"))["status"] == "prepared"
    assert child.name == transaction["child_run_id"]


def test_fork_profile_resumes_when_child_move_precedes_transaction_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """子目录已原子发布但状态未落盘时，--resume 必须识别并继续同一事务。"""
    parent = _forkable_general_run(tmp_path)
    _transaction_path, interrupted_transaction, child = _interrupt_fork_after_child_move(
        parent, monkeypatch, "forktxn03"
    )
    assert interrupted_transaction["status"] == "prepared"
    assert child.is_dir()

    resumed = fork_profile(
        parent,
        profile="engineering_optimization",
        reviewer="reviewer",
        reason="Gate 0 确认需要工程优化专项 Profile。",
        transaction_id="forktxn03",
        resume=True,
    )
    assert Path(resumed["child_run"]) == child
    assert resumed["status"] == "committed"


def test_fork_profile_resume_rejects_tampered_staged_child_diagnosis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prepared 临时子 Run 的 Gate 0 诊断被修改后，恢复不得发布它。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, _transaction, staged_child, final_child = (
        _interrupt_fork_before_child_move(parent, monkeypatch, "forktxn09")
    )
    diagnosis_path = staged_child / "diagnosis.json"
    diagnosis = json.loads(diagnosis_path.read_text("utf-8"))
    diagnosis["problem_summary"] = "tampered before publish"
    diagnosis_path.write_text(json.dumps(diagnosis), encoding="utf-8")

    with pytest.raises(ValueError, match="diagnosis.json"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn09",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"
    assert not final_child.exists()


def test_fork_profile_resume_rejects_tampered_staged_child_run_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prepared 临时子 Run 的身份被修改后，恢复不得发布它。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, _transaction, staged_child, final_child = (
        _interrupt_fork_before_child_move(parent, monkeypatch, "forktxn10")
    )
    manifest_path = staged_child / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["profile"] = "general"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="run_manifest.json.profile"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn10",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"
    assert not final_child.exists()


def test_fork_profile_resume_rejects_tampered_staged_child_material_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prepared 临时子 Run 的材料摘要或证据哈希变化后，恢复不得发布它。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, _transaction, staged_child, final_child = (
        _interrupt_fork_before_child_move(parent, monkeypatch, "forktxn11")
    )
    problem_manifest_path = staged_child / "problem_manifest.json"
    problem_manifest = json.loads(problem_manifest_path.read_text("utf-8"))
    problem_manifest["content_digest"] = "0" * 64
    problem_manifest_path.write_text(json.dumps(problem_manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="problem_manifest|证据清单"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn11",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"
    assert not final_child.exists()


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("reviewer", "other-reviewer"),
        ("profile_selection_reason", "other-reason"),
        ("lineage_type", "other-lineage"),
        ("parent_gate_0_manifest_sha256", "0" * 64),
        ("parent_diagnosis_sha256", "0" * 64),
    ],
)
def test_fork_profile_resume_rejects_tampered_staged_child_parent_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    tampered_value: str,
) -> None:
    """prepared 临时子 Run 的父级审核绑定变化后，恢复不得发布它。"""
    parent = _forkable_general_run(tmp_path)
    transaction_id = "forktxn13_" + field
    transaction_path, _transaction, staged_child, final_child = (
        _interrupt_fork_before_child_move(parent, monkeypatch, transaction_id)
    )
    record_path = staged_child / "fork_record.json"
    record = json.loads(record_path.read_text("utf-8"))
    record[field] = tampered_value
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id=transaction_id,
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"
    assert not final_child.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows junction 攻击矩阵不属于本轮 CR")
def test_fork_profile_resume_rejects_staged_child_directory_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POSIX 上 prepared 临时子目录被符号链接替换后，恢复不得发布它。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, _transaction, staged_child, final_child = (
        _interrupt_fork_before_child_move(parent, monkeypatch, "forktxn12")
    )
    moved_child = staged_child.parent / f"{staged_child.name}-moved"
    staged_child.rename(moved_child)
    staged_child.symlink_to(moved_child, target_is_directory=True)

    with pytest.raises(ValueError, match="非符号链接目录"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn12",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"
    assert not final_child.exists()


def test_fork_profile_resume_rejects_tampered_published_child_diagnosis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已发布子 Run 的 Gate 0 诊断被修改后，恢复必须闭锁失败。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, _transaction, child = _interrupt_fork_after_child_move(
        parent, monkeypatch, "forktxn05"
    )
    diagnosis_path = child / "diagnosis.json"
    diagnosis = json.loads(diagnosis_path.read_text("utf-8"))
    diagnosis["problem_summary"] = "tampered after publish"
    diagnosis_path.write_text(json.dumps(diagnosis), encoding="utf-8")

    with pytest.raises(ValueError, match="diagnosis.json"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn05",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"


def test_fork_profile_resume_rejects_tampered_published_child_run_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已发布子 Run 的身份被修改后，恢复不得提交父子谱系。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, _transaction, child = _interrupt_fork_after_child_move(
        parent, monkeypatch, "forktxn06"
    )
    manifest_path = child / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["profile"] = "general"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="run_manifest.json.profile"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn06",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"


def test_fork_profile_resume_rejects_tampered_published_child_material_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已发布子 Run 的材料摘要或证据哈希变化后，恢复必须闭锁失败。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, _transaction, child = _interrupt_fork_after_child_move(
        parent, monkeypatch, "forktxn07"
    )
    problem_manifest_path = child / "problem_manifest.json"
    problem_manifest = json.loads(problem_manifest_path.read_text("utf-8"))
    problem_manifest["content_digest"] = "0" * 64
    problem_manifest_path.write_text(json.dumps(problem_manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="problem_manifest|证据清单"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn07",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows junction 攻击矩阵不属于本轮 CR")
def test_fork_profile_resume_rejects_published_child_directory_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POSIX 上正式子目录被符号链接替换后，恢复必须闭锁失败。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, _transaction, child = _interrupt_fork_after_child_move(
        parent, monkeypatch, "forktxn08"
    )
    moved_child = parent.parent / f"{child.name}-moved"
    child.rename(moved_child)
    child.symlink_to(moved_child, target_is_directory=True)

    with pytest.raises(ValueError, match="非符号链接目录"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn08",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "prepared"


def test_fork_profile_resumes_when_parent_event_precedes_transaction_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """父事件已追加但状态未落盘时，--resume 必须验证现有事件并完成提交。"""
    parent = _forkable_general_run(tmp_path)
    original_write = run_workflow_module._write_fork_transaction

    def interrupt_after_parent_event(path, transaction):
        if transaction.get("status") == "parent_linked":
            raise OSError("模拟父事件追加后的进程中断")
        original_write(path, transaction)

    monkeypatch.setattr(run_workflow_module, "_write_fork_transaction", interrupt_after_parent_event)
    with pytest.raises(OSError, match="进程中断"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn04",
        )

    transaction_path = parent.parent / ".transactions" / "fork-profile" / "forktxn04.json"
    interrupted_transaction = json.loads(transaction_path.read_text("utf-8"))
    child = parent.parent / interrupted_transaction["child_run_id"]
    assert interrupted_transaction["status"] == "child_published"
    assert replay_transition_log(parent)["superseded_by_run_id"] == child.name

    monkeypatch.setattr(run_workflow_module, "_write_fork_transaction", original_write)
    resumed = fork_profile(
        parent,
        profile="engineering_optimization",
        reviewer="reviewer",
        reason="Gate 0 确认需要工程优化专项 Profile。",
        transaction_id="forktxn04",
        resume=True,
    )
    assert Path(resumed["child_run"]) == child
    assert resumed["status"] == "committed"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "committed"


def test_fork_profile_rolls_back_parent_when_parent_linked_child_is_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """父事件已写但子提交前损坏时，补偿事件必须恢复父 Run 并中止事务。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, transaction, child = _interrupt_fork_after_parent_linked(
        parent, monkeypatch, "forktxn15"
    )
    assert transaction["status"] == "parent_linked"
    assert replay_transition_log(parent)["lifecycle_status"] == "superseded"
    (child / "diagnosis.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="diagnosis.json"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn15",
            resume=True,
        )

    parent_state = replay_transition_log(parent)
    assert parent_state["lifecycle_status"] == "active"
    assert parent_state["current_gate"] == 0
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "aborted"
    assert verify_run(parent)["advance_allowed"] is True
    with pytest.raises(ValueError, match="aborted|谱系"):
        advance_run(child, "reviewer")


def test_parent_linked_compensation_resumes_after_rollback_event_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """补偿事件落盘后的再次 resume 必须幂等完成事务中止。"""
    parent = _forkable_general_run(tmp_path)
    transaction_path, transaction, child = _interrupt_fork_after_parent_linked(
        parent, monkeypatch, "forktxn17"
    )
    (child / "diagnosis.json").write_text("{}\n", encoding="utf-8")
    original_abort_child = run_workflow_module._abort_child_fork_record

    def interrupt_after_rollback(*_args, **_kwargs):
        raise OSError("模拟 rollback event 后中断")

    monkeypatch.setattr(run_workflow_module, "_abort_child_fork_record", interrupt_after_rollback)
    with pytest.raises(OSError, match="rollback event"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn17",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "parent_linked"

    monkeypatch.setattr(run_workflow_module, "_abort_child_fork_record", original_abort_child)
    with pytest.raises(ValueError, match="diagnosis.json"):
        fork_profile(
            parent,
            profile="engineering_optimization",
            reviewer="reviewer",
            reason="Gate 0 确认需要工程优化专项 Profile。",
            transaction_id="forktxn17",
            resume=True,
        )
    assert replay_transition_log(parent)["lifecycle_status"] == "active"
    assert json.loads(transaction_path.read_text("utf-8"))["status"] == "aborted"
    assert json.loads((child / "fork_record.json").read_text("utf-8"))["status"] == "aborted"
    assert child.name == transaction["child_run_id"]


def test_export_runtime_pack_requires_context_and_resolves_profile_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """独立导出命令必须显式声明 context，且仅比赛上下文默认 general。"""
    monkeypatch.setattr(sys, "argv", ["export_runtime_pack.py", "--context", "new_problem"])
    args = parse_export_runtime_pack_args()
    assert args.context == "new_problem"
    assert resolve_profile_for_context(args.context, args.profile) == "general"
    with pytest.raises(ValueError, match="full_replay 必须显式提供 --profile"):
        resolve_profile_for_context("full_replay", None)


def test_prompt_regression_never_creates_gate_or_promotion_evidence(tmp_path: Path) -> None:
    args = Namespace(
        run_id="prompt_only",
        output_root=str(tmp_path / "runs"),
        problem="2024-C",
        profile="engineering_optimization",
        candidate_patch=[],
        exclude_patch=[],
    )
    run_dir = create_prompt_regression_run(args)

    assert not (run_dir / "transitions.jsonl").exists()
    assert not (run_dir / "gate_artifacts").exists()
    report = verify_run(run_dir)
    assert report["workflow"] == "prompt_regression"
    assert report["eligible_for_promotion"] is False


def test_modes_change_confirmation_points_not_machine_contract(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"fake problem pdf"
    (materials / "problem.pdf").write_bytes(problem)
    _write_material_manifest(materials, "2024-C", {"problem": [("problem.pdf", problem)]})

    run_dirs: list[Path] = []
    for mode in ("strict", "emergency"):
        args = Namespace(
            workflow="new_problem",
            mode=mode,
            run_id=f"mode_{mode}",
            output_root=str(tmp_path / "runs"),
            problem="2024-C",
            profile="engineering_optimization",
            gates="0-5",
            materials=str(materials),
            candidate_patch=[],
            exclude_patch=[],
            material_file=[],
            promotion_evidence=False,
            experiment_group_id=None,
            experiment_role=None,
            target_patch=None,
        )
        run_dir, ready = create_old_problem_run(args)
        assert ready is True
        run_dirs.append(run_dir)

    strict_manifest = json.loads((run_dirs[0] / "run_manifest.json").read_text("utf-8"))
    emergency_manifest = json.loads((run_dirs[1] / "run_manifest.json").read_text("utf-8"))
    assert strict_manifest["human_confirmation_gates"] == [0, 1, 2, 3, 4, 5]
    assert emergency_manifest["human_confirmation_gates"] == [0, 5]
    assert (run_dirs[0] / "runtime_pack.md").read_bytes() == (
        run_dirs[1] / "runtime_pack.md"
    ).read_bytes()
    assert {path.name for path in run_dirs[0].glob("*.json")} == {
        path.name for path in run_dirs[1].glob("*.json")
    }


def test_advance_and_verify_partial_v2_run(tmp_path: Path) -> None:
    run_dir = _v2_gate_0_run(tmp_path)
    _write_valid_gate_artifact(run_dir, 0)

    state = advance_run(run_dir, "human")
    report = verify_run(run_dir)

    assert state["current_gate"] == 1
    assert report["verified_gates"] == [0]
    assert report["eligible_for_promotion"] is False


def test_finalize_run_evidence_seals_current_files_and_detects_later_tampering(tmp_path: Path) -> None:
    """封存命令应重建最终哈希；随后篡改 response 必须可被校验器发现。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"fake problem pdf"
    (materials / "problem.pdf").write_bytes(pdf_data)
    _write_material_manifest(materials, "2024-C", {"problem": [("problem.pdf", pdf_data)]})
    args = Namespace(
        run_id="sealed_run", output_root=str(tmp_path / "runs"), problem="2024-C",
            profile="engineering_optimization", gates="0-5", materials=str(materials),
        candidate_patch=[], exclude_patch=[], material_file=[], promotion_evidence=False,
        experiment_group_id=None, experiment_role=None, target_patch=None,
    )
    run_dir, ready = create_old_problem_run(args)
    assert ready is True
    request_path = run_dir / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request.update({"prompt": "真实运行提示词", "model": "TestModel", "source": "real_ai_run"})
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    metadata_path = run_dir / "ai_run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update({"status": "completed", "provider": "test", "model": "TestModel"})
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    record_transition(run_dir, None, 0, "test_reviewer", "approved")
    for gate in range(5):
        _write_valid_gate_artifact(run_dir, gate)
        record_transition(run_dir, gate, gate + 1, "test_reviewer", "approved")
    (run_dir / "gate_5_review.json").write_text(
        json.dumps(_gate_5_review(run_dir, "test_reviewer"), ensure_ascii=False),
        encoding="utf-8",
    )
    write_gate_artifact_manifest(
        run_dir, 5, completed_at="2026-07-11T00:00:00Z"
    )
    immutable_manifest_before = (run_dir / "run_manifest.json").read_bytes()
    mark_run_completed(run_dir, "test_reviewer")
    preseal_report = verify_run(run_dir)
    assert preseal_report["completed"] is True
    assert preseal_report["sealed"] is False
    assert preseal_report["eligible_for_promotion"] is False

    report = complete_and_seal_run(run_dir, "test_reviewer")
    evidence = json.loads(
        (run_dir / "run_evidence_manifest.json").read_text(encoding="utf-8")
    )
    gate_3_manifest = json.loads(
        (run_dir / "gate_artifacts" / "gate_3.manifest.json").read_text(encoding="utf-8")
    )
    required_artifacts = json.loads((ROOT / "policies" / "promotion_policy.json").read_text(encoding="utf-8"))["run_evidence_requirements"]["ai_run_metadata_checks"]["required_artifacts"]
    assert (run_dir / "run_manifest.json").read_bytes() == immutable_manifest_before
    seal = json.loads((run_dir / "seal_record.json").read_text(encoding="utf-8"))
    validator = RepositoryValidator()
    assert validator.validate_schema(seal, "run_seal.schema.json", "run seal")
    assert seal["run_manifest_sha256"] == hashlib.sha256(immutable_manifest_before).hexdigest()
    assert gate_3_manifest["formal_result"]["formal_result_eligible"] is False
    assert gate_3_manifest["formal_result"]["formal_result_activation_status"] == "code_complete_candidate"
    assert evidence["formal_result_eligible"] is False
    assert evidence["formal_result_activation_status"] == "code_complete_candidate"
    assert seal["formal_result_eligible"] is False
    assert seal["formal_result_activation_status"] == "code_complete_candidate"
    assert report["formal_result_eligible"] is False
    assert report["formal_result_activation_status"] == "code_complete_candidate"
    assert report["completed"] is True
    assert report["sealed"] is True
    assert report["eligible_for_promotion"] is False
    assert complete_and_seal_run(run_dir, "test_reviewer")["sealed"] is True
    assert not validate_evidence_manifest(run_dir, evidence, required_artifacts)
    policy = json.loads(
        (ROOT / "policies" / "promotion_policy.json").read_text(encoding="utf-8")
    )
    shared_outcome = validate_full_run(run_dir, policy)
    assert not shared_outcome.valid
    assert shared_outcome.identity["run_id"] == "sealed_run"
    assert any("promotion_evidence" in error for error in shared_outcome.errors)

    with (run_dir / "response.json").open("a", encoding="utf-8") as response:
        response.write("\n篡改")
    tampered_outcome = validate_full_run(run_dir, policy)
    assert not tampered_outcome.valid
    assert any("sha256" in error.lower() for error in tampered_outcome.errors)
    assert any("response.json" in error and "sha256" in error for error in validate_evidence_manifest(run_dir, evidence, required_artifacts))


def test_finalize_run_evidence_rejects_incomplete_gate_workflow(tmp_path: Path) -> None:
    """AI 调用完成不足以封存，运行必须先完成并通过 Gate 5。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"fake problem pdf"
    (materials / "problem.pdf").write_bytes(pdf_data)
    _write_material_manifest(materials, "2024-C", {"problem": [("problem.pdf", pdf_data)]})
    args = Namespace(
        run_id="uncompleted_run", output_root=str(tmp_path / "runs"), problem="2024-C",
        profile="engineering_optimization", gates="0-5", materials=str(materials),
        candidate_patch=[], exclude_patch=[], material_file=[], promotion_evidence=False,
        experiment_group_id=None, experiment_role=None, target_patch=None,
    )
    run_dir, ready = create_old_problem_run(args)
    assert ready is True
    metadata_path = run_dir / "ai_run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update({"status": "completed", "provider": "test", "model": "TestModel"})
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="仅允许封存已完成 Gate 0-5"):
        finalize_run_evidence(run_dir)


def test_old_problem_cli_isolation_run_records_exclusion(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"fake problem pdf"
    (materials / "problem.pdf").write_bytes(pdf_data)
    _write_material_manifest(
        materials,
        "2024-C",
        {"problem": [("problem.pdf", pdf_data)]},
    )
    args = Namespace(
            run_id="test_isolation",
            output_root=str(tmp_path / "runs"),
            problem="2024-C",
            profile="engineering_optimization",
            gates="0-2",
            materials=str(materials),
            candidate_patch=[],
            exclude_patch=["A127"],
            material_file=[],
            promotion_evidence=False,
            experiment_group_id=None,
            experiment_role=None,
            target_patch=None
        )
    run_dir, ready = create_old_problem_run(args)
    assert ready is True
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["experiment_kind"] == "isolation"
    assert manifest["excluded_patches"] == ["A127"]
    pack_manifest = json.loads((run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8"))
    assert pack_manifest["exclusion_experiment"]["enabled"] is True
    assert pack_manifest["patches"] == []

def test_old_problem_cli_promotion_evidence_mode(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "problem.pdf").write_bytes(b"fake problem pdf")
    args = Namespace(
        run_id="test_promo",
        output_root=str(tmp_path / "runs"),
        problem="2024-C",
        profile="engineering_optimization",
        gates="0-2",
        materials=str(materials),
        candidate_patch=[],
        exclude_patch=["A127"],
        material_file=[],
        promotion_evidence=True,
        experiment_group_id="GRP_A127",
        experiment_role="baseline",
        target_patch="A127",
        no_eval=True
    )
    run_dir, ready = create_old_problem_run(args)
    manifest = json.loads((run_dir / "run_manifest.json").read_text("utf-8"))
    assert manifest["experiment_kind"] == "negative_control"
    assert manifest["experiment_group_id"] == "GRP_A127"
    assert manifest["experiment_role"] == "baseline"
    assert manifest["target_patch"] == "A127"
    assert manifest["promotion_evidence"] is True
    assert "evidence_validity" not in manifest
    assert "eligible_for_promotion" not in manifest


# ====== verify_materials failure-scenario tests ======


def _make_valid_manifest(problem_id: str, problem_pdf: bytes) -> dict:
    """Return a minimal valid manifest dict (for on-disc construction)."""
    return {
        "manifest_version": "1.0.0",
        "problem_id": problem_id,
        "material_root": ".",
        "source": {"kind": "official", "reference": "https://example.com"},
        "contains_answer_or_solution": False,
        "categories": {
            "problem": {
                "required": True,
                "files": [{"path": "problem.pdf", "sha256": sha256_bytes(problem_pdf)}],
            },
            "attachments": {"required": False, "files": []},
            "templates": {"required": False, "files": []},
        },
    }


def test_verify_materials_ready_with_valid_manifest(tmp_path: Path) -> None:
    """Valid manifest with existing file → ready."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"real problem pdf"
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = _make_valid_manifest("2024-C", pdf_data)
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials, expected_problem_id="2024-C")
    assert result.ready is True
    assert result.status == "ready"
    assert result.problem_id == "2024-C"


def test_verify_materials_missing_manifest(tmp_path: Path) -> None:
    """No manifest → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "problem.pdf").write_bytes(b"data")
    result = verify_materials(materials)
    assert result.ready is False
    assert "缺少机器可读材料清单" in result.errors[0]


def test_verify_materials_dir_not_found(tmp_path: Path) -> None:
    """Directory doesn't exist → blocked."""
    result = verify_materials(tmp_path / "nonexistent")
    assert result.ready is False
    assert any("不存在" in e for e in result.errors)


def test_verify_materials_hash_mismatch(tmp_path: Path) -> None:
    """File exists but SHA-256 doesn't match → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"actual content"
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = _make_valid_manifest("2024-C", b"different content")
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    cat = result.categories["problem"]
    assert any("SHA-256 不匹配" in e for e in cat.errors)


def test_verify_materials_file_missing(tmp_path: Path) -> None:
    """Manifest declares file that doesn't exist → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"data"
    manifest = _make_valid_manifest("2024-C", pdf_data)
    # Don't write the actual PDF
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    cat = result.categories["problem"]
    assert any("材料文件不存在" in e for e in cat.errors)


def test_verify_materials_answer_leak_detected(tmp_path: Path) -> None:
    """Manifest declares contains_answer_or_solution=True → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"problem with leaked answer"
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = _make_valid_manifest("2024-C", pdf_data)
    manifest["contains_answer_or_solution"] = True
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    assert any("答案或题解" in e for e in result.errors)


def test_verify_materials_problem_id_mismatch(tmp_path: Path) -> None:
    """Manifest problem_id doesn't match expected → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"data"
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = _make_valid_manifest("2024-C", pdf_data)
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials, expected_problem_id="2023-B")
    assert result.ready is False
    assert any("题号不匹配" in e for e in result.errors)


def test_verify_materials_duplicate_path(tmp_path: Path) -> None:
    """Same path declared twice → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"data"
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = _make_valid_manifest("2024-C", pdf_data)
    # Duplicate the file entry
    manifest["categories"]["problem"]["files"].append(
        {"path": "problem.pdf", "sha256": sha256_bytes(pdf_data)}
    )
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    cat = result.categories["problem"]
    assert any("重复声明" in e for e in cat.errors)


def test_verify_materials_empty_required_category(tmp_path: Path) -> None:
    """Required category has no files → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"data"
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = _make_valid_manifest("2024-C", pdf_data)
    manifest["categories"]["problem"]["files"] = []
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    cat = result.categories["problem"]
    assert any("材料类别为空" in e for e in cat.errors)


def test_verify_materials_manifest_outside_root(tmp_path: Path) -> None:
    """Manifest outside material root → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"data"
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = _make_valid_manifest("2024-C", pdf_data)
    # Put manifest outside materials dir
    outside_manifest = tmp_path / "material_manifest.json"
    outside_manifest.write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials, manifest_path=outside_manifest)
    assert result.ready is False
    assert any("必须位于材料根目录内" in e for e in result.errors)


def test_verify_materials_absolute_path_rejected(tmp_path: Path) -> None:
    """Absolute path in manifest → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"data"
    abs_path = str(materials / "problem.pdf")
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = {
        "manifest_version": "1.0.0",
        "problem_id": "2024-C",
        "material_root": ".",
        "source": {"kind": "official", "reference": "https://example.com"},
        "contains_answer_or_solution": False,
        "categories": {
            "problem": {
                "required": True,
                "files": [{"path": abs_path, "sha256": sha256_bytes(pdf_data)}],
            },
            "attachments": {"required": False, "files": []},
            "templates": {"required": False, "files": []},
        },
    }
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    cat = result.categories["problem"]
    assert any("绝对路径" in e for e in cat.errors)


def test_verify_materials_path_traversal_rejected(tmp_path: Path) -> None:
    """Path traversal attempt in manifest → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"data"
    # Create a file outside materials that would be targeted by traversal
    (tmp_path / "secret.pdf").write_bytes(b"secret")
    manifest = _make_valid_manifest("2024-C", pdf_data)
    manifest["categories"]["problem"]["files"] = [
        {"path": "../secret.pdf", "sha256": sha256_bytes(b"secret")}
    ]
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    cat = result.categories["problem"]
    assert any("逃逸" in e for e in cat.errors)


def test_verify_materials_invalid_json_manifest(tmp_path: Path) -> None:
    """Manifest is not valid JSON → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "material_manifest.json").write_text("not json", "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    assert any("不是有效 UTF-8 JSON" in e for e in result.errors)


def test_verify_materials_schema_violation(tmp_path: Path) -> None:
    """Manifest missing required fields → blocked."""
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "material_manifest.json").write_text('{"version": "bad"}', "utf-8")

    result = verify_materials(materials)
    assert result.ready is False
    assert any("Schema" in e for e in result.errors)


def test_verify_materials_to_dict_serializable(tmp_path: Path) -> None:
    """to_dict() produces valid JSON-serializable output."""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"data"
    (materials / "problem.pdf").write_bytes(pdf_data)
    manifest = _make_valid_manifest("2024-C", pdf_data)
    (materials / "material_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), "utf-8")

    result = verify_materials(materials)
    d = result.to_dict()
    assert d["status"] == "ready"
    assert d["ready"] is True
    assert len(d["files"]) == 1
    assert result.manifest_sha256 is not None


# ====== check_promotion_eligibility tests ======


def test_check_promotion_eligibility_produces_report() -> None:
    """Real policy + matrix + patch_index produce a valid report."""
    report, gaps = check_promotion_eligibility()
    policy = json.loads((ROOT / "policies" / "promotion_policy.json").read_text(encoding="utf-8"))
    assert report["policy_version"] == policy["policy_version"]
    assert report["total_patches"] == 4
    assert "per_patch" in report
    assert "verdict" in report
    # A092/A127 的 Legacy v1 已归档；新 v2 证据尚未重跑，必须现场派生为 pending。
    a092 = next(p for p in report["per_patch"] if p["patch_id"] == "A092")
    assert a092["positive"] == "pending"
    assert a092["boundary"] == "pending"
    assert a092["negative"] == "pending"
    # With the stricter v1.2.0 policy (min_distinct_cases=3, min_distinct_years=2),
    # A092 still passes (2016-C/2023-B/2024-C = 3 cases, 2016+2023+2024 = 3 years)
    assert a092["current_status_valid"] is True
    # Check that per_patch format uses new fields
    assert "current_gaps" in a092
    assert "gaps_to_next_status" in a092


def test_check_promotion_eligibility_gaps_is_list() -> None:
    """Gaps is always a list (may be empty)."""
    _, gaps = check_promotion_eligibility()
    assert isinstance(gaps, list)


def test_promotion_gap_str_contains_ids() -> None:
    """PromotionGap string representation includes patch_id and target."""
    g = PromotionGap("A092", "competition_evidenced", "需要人工确认")
    s = str(g)
    assert "A092" in s
    assert "competition_evidenced" in s
    assert "人工确认" in s


# ====== Gate state machine tests ======


def test_gate_names_complete() -> None:
    """GATE_NAMES covers 0-5 with correct names."""
    assert GATE_NAMES == {
        0: "题目与材料诊断",
        1: "模型路线",
        2: "代码计划",
        3: "结果确认",
        4: "论文候选",
        5: "最终验收",
    }


def test_valid_transitions() -> None:
    """Only sequential forward transitions are allowed."""
    assert VALID_TRANSITIONS[None] == {0}
    assert VALID_TRANSITIONS[0] == {1}
    assert VALID_TRANSITIONS[1] == {2}
    assert VALID_TRANSITIONS[2] == {3}
    assert VALID_TRANSITIONS[3] == {4}
    assert VALID_TRANSITIONS[4] == {5}
    assert VALID_TRANSITIONS[5] == set()


def test_record_and_read_transitions(tmp_path: Path) -> None:
    """Record gate transitions and read them back via get_current_gate."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_minimal_run_binding(run_dir)
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": True, "max_gate": 5, "note": "ok"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Enter Gate 0
    record_transition(run_dir, None, 0, "human", "approved")
    assert get_current_gate(run_dir) == 0
    assert is_gate_complete(run_dir, 0) is False

    # Progress through gates
    for gate in range(1, 6):
        record_transition(run_dir, gate - 1, gate, "human", "approved")
        assert get_current_gate(run_dir) == gate

    assert is_gate_complete(run_dir, 0) is True
    assert is_gate_complete(run_dir, 3) is True
    # Gate 5 is terminal; not complete until mark_run_completed
    assert is_gate_complete(run_dir, 5) is False

    # Mark completed - Gate 5 should now be complete
    (run_dir / "gate_5_review.json").write_text(
        json.dumps(_gate_5_review(run_dir, "automated_test")), encoding="utf-8"
    )
    mark_run_completed(run_dir, "automated_test")
    assert is_gate_complete(run_dir, 5) is True


def test_v2_transition_records_completed_gate_and_next_gate(tmp_path: Path) -> None:
    """v2 推进事件必须表达完成的 Gate，而不是只记录进入下一 Gate。"""
    run_dir = _v2_gate_0_run(tmp_path)
    _write_valid_gate_artifact(run_dir, 0)

    record_transition(run_dir, 0, 1, "human", "approved")

    last = json.loads(
        (run_dir / "transitions.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert last["completed_gate"] == 0
    assert last["next_gate"] == 1
    assert last["state"] == "completed_gate_0"
    assert "from" not in last and "to" not in last
    assert replay_transition_log(run_dir)["completed_gates"] == [0]


def test_v2_transition_hash_chain_rejects_event_tampering(tmp_path: Path) -> None:
    run_dir = _v2_gate_0_run(tmp_path)
    lines = (run_dir / "transitions.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["note"] = "tampered without rebuilding the chain"
    lines[0] = json.dumps(first)
    (run_dir / "transitions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="event_sha256 不匹配"):
        replay_transition_log(run_dir)


def test_atomic_write_preserves_original_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.json"
    target.write_bytes(b"original")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("atomic_io.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_bytes(target, b"replacement")

    assert target.read_bytes() == b"original"
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_atomic_write_cleans_stale_temp_file_before_recovery(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    stale = tmp_path / ".state.json.interrupted.tmp"
    stale.write_bytes(b"partial")

    atomic_write_bytes(target, b"recovered")

    assert target.read_bytes() == b"recovered"
    assert not stale.exists()


def test_v2_missing_gate_manifest_cannot_advance(tmp_path: Path) -> None:
    """未生成 Gate 清单时必须停留在当前 Gate。"""
    run_dir = _v2_gate_0_run(tmp_path)

    with pytest.raises(FileNotFoundError, match="gate_0.manifest.json"):
        record_transition(run_dir, 0, 1, "human", "approved")
    assert replay_transition_log(run_dir)["current_gate"] == 0


def test_v2_placeholder_business_artifact_cannot_build_manifest(tmp_path: Path) -> None:
    """只有占位说明而无业务内容的文件不能被封装为 Gate 完成证据。"""
    run_dir = _v2_gate_0_run(tmp_path)
    (run_dir / "diagnosis.json").write_text(
        json.dumps({"artifact_type": "diagnosis", "_note": "pending"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="diagnosis.json 不符合 Schema"):
        write_gate_artifact_manifest(run_dir, 0)


def test_v2_artifact_identity_mismatch_is_fail_closed(tmp_path: Path) -> None:
    """业务产物身份与当前运行不一致时不得生成可信清单。"""
    run_dir = _v2_gate_0_run(tmp_path)
    _write_valid_gate_artifact(run_dir, 0)
    diagnosis_path = run_dir / "diagnosis.json"
    diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    diagnosis["run_id"] = "copied_from_other_run"
    diagnosis_path.write_text(json.dumps(diagnosis), encoding="utf-8")

    with pytest.raises(ValueError, match="diagnosis.json.run_id 与当前运行现场不一致"):
        write_gate_artifact_manifest(run_dir, 0)


def test_v2_tampered_artifact_hash_cannot_advance(tmp_path: Path) -> None:
    """清单生成后篡改业务产物，即使 JSON 仍合法也不得离开 Gate。"""
    run_dir = _v2_gate_0_run(tmp_path)
    _write_valid_gate_artifact(run_dir, 0)
    diagnosis_path = run_dir / "diagnosis.json"
    diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    diagnosis["risks"].append("Tampering changed the reviewed business content.")
    diagnosis_path.write_text(json.dumps(diagnosis), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        record_transition(run_dir, 0, 1, "human", "approved")
    assert replay_transition_log(run_dir)["current_gate"] == 0


def test_partial_v2_run_can_be_verified_but_is_not_completed(tmp_path: Path) -> None:
    """部分 Gate 可保存复核，但不会被状态机标记为完整运行。"""
    run_dir = _v2_gate_0_run(tmp_path)
    _write_valid_gate_artifact(run_dir, 0)

    manifest = verify_gate_artifacts(run_dir, 0)
    state = replay_transition_log(run_dir)

    assert manifest["gate"] == 0
    assert state["completed"] is False
    assert state["completed_gates"] == []


def test_gate_5_review_schema_requires_target_gate(tmp_path: Path) -> None:
    """Gate 5 审核缺少 target_gate 时不得因默认值而通过。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_minimal_run_binding(run_dir)
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": True, "max_gate": 5}) + "\n",
        encoding="utf-8",
    )
    for gate in range(6):
        record_transition(run_dir, gate - 1 if gate else None, gate, "human", "approved")
    review = _gate_5_review(run_dir)
    review.pop("target_gate")
    (run_dir / "gate_5_review.json").write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="target_gate"):
        mark_run_completed(run_dir, "human")


@pytest.mark.parametrize(
    "field",
    ["run_id", "problem_id", "profile", "runtime_version", "runtime_pack_sha256"],
)
def test_gate_5_review_requires_all_run_binding_fields(tmp_path: Path, field: str) -> None:
    """Gate 5 审核缺少任一运行绑定字段时必须闭锁失败。"""
    run_dir = _ready_gate_5_run(tmp_path, "missing_binding")
    review = _gate_5_review(run_dir)
    review.pop(field)
    (run_dir / "gate_5_review.json").write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        mark_run_completed(run_dir, "human")


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("run_id", "other_run"),
        ("problem_id", "2099-Z"),
        ("profile", "other_profile"),
        ("runtime_version", "9.9.9"),
        ("runtime_pack_sha256", "f" * 64),
    ],
)
def test_gate_5_review_rejects_wrong_run_binding(
    tmp_path: Path, field: str, wrong_value: str
) -> None:
    """审核身份必须逐项等于当前运行现场，不能只依赖审核文件自身哈希。"""
    run_dir = _ready_gate_5_run(tmp_path, f"wrong_{field}")
    review = _gate_5_review(run_dir)
    review[field] = wrong_value
    (run_dir / "gate_5_review.json").write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(ValueError, match=f"{field} 与当前运行现场不一致"):
        mark_run_completed(run_dir, "human")


def test_gate_5_review_rejects_unknown_checklist_key(tmp_path: Path) -> None:
    """Checklist 只能包含固定八项，额外自定义通过项不能混入。"""
    run_dir = _ready_gate_5_run(tmp_path, "unknown_checklist")
    review = _gate_5_review(run_dir)
    review["checklist"]["custom_pass"] = True
    (run_dir / "gate_5_review.json").write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(ValueError, match="checklist"):
        mark_run_completed(run_dir, "human")


@pytest.mark.parametrize(("mode", "value"), [("missing", None), ("false", False)])
def test_gate_5_review_requires_all_checklist_items_true(
    tmp_path: Path, mode: str, value: bool | None
) -> None:
    """固定八项中缺项或任一项非 true 都不得完成运行。"""
    run_dir = _ready_gate_5_run(tmp_path, f"checklist_{mode}")
    review = _gate_5_review(run_dir)
    if mode == "missing":
        review["checklist"].pop("claim_evidence")
    else:
        review["checklist"]["claim_evidence"] = value
    (run_dir / "gate_5_review.json").write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(ValueError, match="checklist"):
        mark_run_completed(run_dir, "human")


def _write_manual_completed_transition_log(
    run_dir: Path,
    review: dict[str, object],
    *,
    material_ready: bool,
) -> None:
    """构造绕过 API 的历史日志，验证 replay 本身仍会 fail-closed。"""
    review_path = run_dir / "gate_5_review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    entries: list[dict[str, object]] = [
        {
            "from": None,
            "to": None,
            "state": "initialized",
            "material_ready": material_ready,
            "max_gate": 5,
        }
    ]
    current: int | None = None
    for gate in range(6):
        entries.append(
            {
                "from": current,
                "to": gate,
                "state": f"entering_gate_{gate}",
                "reviewer": "manual",
                "decision": "approved",
            }
        )
        current = gate
    entries.append(
        {
            "from": 5,
            "to": None,
            "state": "completed",
            "reviewer": review["reviewer"],
            "decision": "approved",
            "review_record": "gate_5_review.json",
            "review_record_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
            "reviewed_at": review["reviewed_at"],
        }
    )
    (run_dir / "transitions.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )


def test_replay_rejects_cross_run_review_after_hash_recalculation(tmp_path: Path) -> None:
    """复制审核到另一 Run 并重算转换日志哈希，仍必须因现场身份不符而失败。"""
    source = _ready_gate_5_run(tmp_path, "source", run_id="run_A", problem_id="2024-C")
    target = _ready_gate_5_run(tmp_path, "target", run_id="run_B", problem_id="2024-C")
    copied_review = _gate_5_review(source, "manual")

    # helper 会按目标目录中复制后的文件重新计算 review_record_sha256。
    _write_manual_completed_transition_log(target, copied_review, material_ready=True)

    with pytest.raises(ValueError, match="run_id 与当前运行现场不一致"):
        replay_transition_log(target)


def test_replay_rejects_forged_rejected_gate_5_review(tmp_path: Path) -> None:
    """匹配 SHA-256 不能使被拒绝的 Gate 5 review 伪装成完成。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_minimal_run_binding(run_dir)
    review = _gate_5_review(run_dir, "manual")
    review.update(
        {
            "decision": "rejected",
            "final_acceptance": False,
            "reason": "The final review explicitly rejected this run.",
        }
    )
    _write_manual_completed_transition_log(
        run_dir,
        review,
        material_ready=True,
    )
    with pytest.raises(ValueError, match="gate_5_review"):
        replay_transition_log(run_dir)


def test_replay_rejects_gate_entries_when_materials_are_not_ready(tmp_path: Path) -> None:
    """直接篡改 JSONL 也不能绕过材料就绪门禁。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_minimal_run_binding(run_dir)
    _write_manual_completed_transition_log(
        run_dir,
        _gate_5_review(run_dir, "manual"),
        material_ready=False,
    )
    with pytest.raises(ValueError, match="material_ready"):
        replay_transition_log(run_dir)


def test_forged_from_gate_rejected(tmp_path: Path) -> None:
    """Caller claims from_gate=1 when real current is 0 → ValueError."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": True, "max_gate": 5, "note": "ok"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    record_transition(run_dir, None, 0, "human", "approved")

    import pytest as pt
    with pt.raises(ValueError, match="from_gate 不匹配"):
        record_transition(run_dir, 1, 2, "human", "approved")


def test_material_not_ready_blocks_gate_entry(tmp_path: Path) -> None:
    """material_ready=false → ValueError on any gate entry."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": False, "max_gate": 5, "note": "blocked"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    import pytest as pt
    with pt.raises(ValueError, match="材料校验未通过"):
        record_transition(run_dir, None, 0, "human", "approved")


def test_exceeds_max_gate_rejected(tmp_path: Path) -> None:
    """max_gate=2 run cannot enter Gate 3."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": True, "max_gate": 2, "note": "ok"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    record_transition(run_dir, None, 0, "human", "approved")
    record_transition(run_dir, 0, 1, "human", "approved")
    record_transition(run_dir, 1, 2, "human", "approved")

    import pytest as pt
    with pt.raises(ValueError, match="不能进入 Gate 3"):
        record_transition(run_dir, 2, 3, "human", "approved")


def test_invalid_skip_gate(tmp_path: Path) -> None:
    """Skipping a gate raises ValueError."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": True, "max_gate": 5, "note": "ok"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    record_transition(run_dir, None, 0, "human", "approved")

    import pytest as pt
    with pt.raises(ValueError, match="不能从 0 进入 Gate 2"):
        record_transition(run_dir, 0, 2, "human", "approved")


def test_invalid_backward_transition(tmp_path: Path) -> None:
    """Going backward raises ValueError."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": True, "max_gate": 5, "note": "ok"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    record_transition(run_dir, None, 0, "human", "approved")
    record_transition(run_dir, 0, 1, "human", "approved")

    import pytest as pt
    with pt.raises(ValueError, match="不能从 1 进入 Gate 0"):
        record_transition(run_dir, 1, 0, "human", "approved")


def test_entry_before_initialization(tmp_path: Path) -> None:
    """Entering a gate without initialized transitions → FileNotFoundError (v2 hardened)."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # No transitions.jsonl — v2 now raises FileNotFoundError
    import pytest as pt
    with pt.raises(FileNotFoundError, match="缺少 transitions.jsonl"):
        record_transition(run_dir, None, 0, "human", "approved")


def test_rejected_transition_not_advances(tmp_path: Path) -> None:
    """A rejected transition does not change current gate."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": True, "max_gate": 5, "note": "ok"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    record_transition(run_dir, None, 0, "human", "approved")
    record_transition(run_dir, 0, 1, "human", "rejected")
    # Still at gate 0 because the transition to 1 was rejected
    assert get_current_gate(run_dir) == 0


def test_get_current_gate_no_file(tmp_path: Path) -> None:
    """No transitions file → None."""
    assert get_current_gate(tmp_path / "nonexistent") is None
    advance_run,
    create_prompt_regression_run,
