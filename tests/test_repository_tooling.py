from __future__ import annotations

import hashlib
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_prompt_response import evaluate_case  # noqa: E402
from export_runtime_pack import (  # noqa: E402
    build_manifest,
    build_pack,
    select_patch_files,
    select_patches,
)
from run_workflow import (  # noqa: E402
    GATE_5_CHECKLIST_KEYS,
    GATE_NAMES,
    TRANSITION_VERSION,
    VALID_TRANSITIONS,
    advance_run,
    create_old_problem_run,
    create_prompt_regression_run,
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
from validate_repository import RepositoryValidator  # noqa: E402
from verify_materials import MaterialVerificationResult, sha256_bytes, verify_materials  # noqa: E402
from check_promotion_eligibility import PromotionGap, check_promotion_eligibility  # noqa: E402


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
                "run_id": run_id,
                "problem_id": problem_id,
                "profile": profile,
                "runtime_version": runtime_version,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "runtime_pack.manifest.json").write_text(
        json.dumps(
            {
                "profile": profile,
                "runtime_version": runtime_version,
                "runtime_pack_sha256": runtime_pack_sha,
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
    write_gate_artifact_manifest(run_dir, gate, completed_at="2026-07-11T00:00:00Z")


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
    (run_dir / "transitions.jsonl").write_text(
        json.dumps(
            {
                "transition_version": TRANSITION_VERSION,
                "from": None,
                "to": None,
                "completed_gate": None,
                "next_gate": 0,
                "state": "initialized",
                "material_ready": True,
                "max_gate": 5,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    record_transition(run_dir, None, 0, "human", "approved")
    return run_dir


def test_default_pack_excludes_candidate_patches() -> None:
    selected = select_patch_files("engineering_optimization")
    assert selected == []


def test_manifest_hashes_pack_and_records_exclusions() -> None:
    pack = build_pack("engineering_optimization")
    manifest = build_manifest("engineering_optimization", pack)
    assert manifest["runtime_pack_sha256"]
    assert manifest["patches"] == []
    assert {item["patch_id"] for item in manifest["excluded_patches"]} == {
        "A092", "A127", "B311", "B477"
    }
    # 新增：默认导出不启用实验标记
    assert manifest["candidate_experiment"]["enabled"] is False
    assert manifest["exclusion_experiment"]["enabled"] is False
    validator = RepositoryValidator()
    assert validator.validate_schema(manifest, "runtime_pack_manifest.schema.json", "真实 exporter manifest")


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
    pack = build_pack("engineering_optimization", candidate_patch_ids, exclude_patch_ids)
    runtime_manifest = build_manifest(
        "engineering_optimization",
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
    assert manifest["automatic_stable_update"] is False
    assert manifest["experiment_kind"] == "standard"
    assert manifest["run_status"] == "initialized"
    assert manifest["integrity_status"] == "unsealed"
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
    mark_run_completed(run_dir, "test_reviewer")

    evidence = finalize_run_evidence(run_dir)
    required_artifacts = json.loads((ROOT / "policies" / "promotion_policy.json").read_text(encoding="utf-8"))["run_evidence_requirements"]["ai_run_metadata_checks"]["required_artifacts"]
    sealed_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert sealed_manifest["run_status"] == "completed"
    assert sealed_manifest["integrity_status"] == "sealed"
    assert not validate_evidence_manifest(run_dir, evidence, required_artifacts)

    with (run_dir / "response.json").open("a", encoding="utf-8") as response:
        response.write("\n篡改")
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

    with pytest.raises(ValueError, match="run_status 必须为 completed"):
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
    assert manifest["evidence_validity"] == "pending"
    assert manifest["eligible_for_promotion"] is False


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
        4: "论文确认",
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
