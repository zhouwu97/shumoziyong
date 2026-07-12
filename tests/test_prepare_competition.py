from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import prepare_competition as preparation  # noqa: E402
from run_workflow import complete_and_seal_run, fork_profile, verify_run  # noqa: E402
from test_repository_tooling import _prepare_completed_gate_run, _write_valid_gate_artifact  # noqa: E402


def _materials(tmp_path: Path) -> Path:
    """创建不含答案的最小比赛材料夹具。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "problem.pdf").write_bytes(b"competition problem")
    (materials / "data.xlsx").write_bytes(b"competition data")
    return materials


def _confirm_all(plan_path: Path) -> dict[str, object]:
    """模拟人工只填写逐项分类，不调用内部函数重算扫描摘要。"""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for item in plan["files"]:
        item["confirmed_category"] = item["suggested_category"]
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return plan


def test_plan_apply_publishes_ready_new_problem_run(tmp_path: Path) -> None:
    """apply 只能从已确认、未漂移计划发布包含比赛上下文的正式 Run。"""
    materials = _materials(tmp_path)
    plan_path = tmp_path / "competition" / "material_plan.json"
    created = preparation.plan("2026-A", materials, plan_path)

    assert "profile" not in created and "mode" not in created
    assert created["plan_digest"] == preparation._plan_digest(created)
    assert all(item["confirmed_category"] is None for item in created["files"])
    _confirm_all(plan_path)

    result = preparation.apply(
        plan_path,
        materials,
        profile="general",
        mode="standard",
        reviewer="tester",
        confirm_no_solution=True,
        output_root=str(tmp_path / "runs"),
    )

    run_dir = Path(result["run_dir"])
    assert run_dir.is_dir()
    assert result["workflow_context"] == "new_problem"
    assert result["profile"] == "general"
    assert result["mode"] == "standard"
    assert "Gate 0" in result["gate_0_prompt"]
    assert (materials / "material_manifest.json").is_file()
    assert not list((tmp_path / "runs" / ".tmp").glob("prepare-*"))


def test_plan_excludes_its_own_output_inside_material_directory(tmp_path: Path) -> None:
    """计划文件位于材料目录内时不得成为被分类或哈希的材料。"""
    materials = _materials(tmp_path)
    plan_path = materials / "custom_plan.json"

    created = preparation.plan("2026-A", materials, plan_path)
    assert "custom_plan.json" not in {item["path"] for item in created["files"]}

    _confirm_all(plan_path)
    result = preparation.apply(
        plan_path,
        materials,
        profile="engineering_optimization",
        mode="strict",
        reviewer="tester",
        confirm_no_solution=True,
        output_root=str(tmp_path / "runs"),
    )
    assert result["profile"] == "engineering_optimization"


def test_apply_rejects_material_drift_without_creating_manifest_or_run(tmp_path: Path) -> None:
    """plan 后任何材料新增、删除、重命名或替换都必须阻断 apply。"""
    materials = _materials(tmp_path)
    plan_path = tmp_path / "material_plan.json"
    preparation.plan("2026-A", materials, plan_path)
    _confirm_all(plan_path)
    (materials / "extra.png").write_bytes(b"new attachment")

    with pytest.raises(ValueError, match="新增、删除或重命名"):
        preparation.apply(
            plan_path,
            materials,
            profile="general",
            mode="standard",
            reviewer="tester",
            confirm_no_solution=True,
            output_root=str(tmp_path / "runs"),
        )
    assert not (materials / "material_manifest.json").exists()
    assert not (tmp_path / "runs").exists()


def test_apply_rejects_tampered_plan_digest_before_writing_manifest(tmp_path: Path) -> None:
    """人工编辑分类以外的计划内容也必须由 plan_digest 检出。"""
    materials = _materials(tmp_path)
    plan_path = tmp_path / "material_plan.json"
    preparation.plan("2026-A", materials, plan_path)
    plan = _confirm_all(plan_path)
    plan["problem_id"] = "2026-B"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="plan_digest"):
        preparation.apply(
            plan_path,
            materials,
            profile="general",
            mode="standard",
            reviewer="tester",
            confirm_no_solution=True,
            output_root=str(tmp_path / "runs"),
        )
    assert not (materials / "material_manifest.json").exists()


def test_apply_cleans_manifest_and_staging_run_when_initialization_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run 初始化失败不得遗留可推进目录或孤立材料清单。"""
    materials = _materials(tmp_path)
    plan_path = tmp_path / "material_plan.json"
    preparation.plan("2026-A", materials, plan_path)
    _confirm_all(plan_path)

    def blocked_init(args):
        return Path(args.output_root) / "blocked", False

    monkeypatch.setattr(preparation, "create_new_problem_run", blocked_init)
    with pytest.raises(ValueError, match="未就绪"):
        preparation.apply(
            plan_path,
            materials,
            profile="general",
            mode="standard",
            reviewer="tester",
            confirm_no_solution=True,
            output_root=str(tmp_path / "runs"),
        )
    assert not (materials / "material_manifest.json").exists()
    assert not list((tmp_path / "runs" / ".tmp").glob("prepare-*"))


def test_apply_rejects_corrupt_staged_run_without_publishing_partial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """staged Run 损坏时，材料清单与正式 Run 必须同时保持未提交。"""
    materials = _materials(tmp_path)
    plan_path = tmp_path / "material_plan.json"
    preparation.plan("2026-A", materials, plan_path)
    _confirm_all(plan_path)
    original_create = preparation.create_new_problem_run

    def create_corrupt_staged_run(args):
        staged_run, ready = original_create(args)
        (staged_run / "runtime_pack.manifest.json").write_text("{broken", encoding="utf-8")
        return staged_run, ready

    monkeypatch.setattr(preparation, "create_new_problem_run", create_corrupt_staged_run)
    output_root = tmp_path / "runs"
    with pytest.raises(json.JSONDecodeError):
        preparation.apply(
            plan_path,
            materials,
            profile="general",
            mode="standard",
            reviewer="tester",
            confirm_no_solution=True,
            output_root=str(output_root),
        )

    assert not (materials / "material_manifest.json").exists()
    assert not [path for path in output_root.glob("*") if path.name != ".tmp"]
    assert not list((output_root / ".tmp").glob("prepare-*"))


def test_competition_runtime_end_to_end_preserves_optional_markdown_boundary(
    tmp_path: Path,
) -> None:
    """最小模拟赛覆盖材料准备、Profile Fork、封存和身份产物防篡改。"""
    materials = _materials(tmp_path)
    (materials / "reference.png").write_bytes(b"fixture image")
    plan_path = tmp_path / "competition" / "material_plan.json"
    preparation.plan("2026-A", materials, plan_path)
    _confirm_all(plan_path)
    applied = preparation.apply(
        plan_path,
        materials,
        profile="general",
        mode="standard",
        reviewer="tester",
        confirm_no_solution=True,
        output_root=str(tmp_path / "runs"),
    )
    parent = Path(applied["run_dir"])

    from run_workflow import advance_run  # noqa: E402

    advance_run(parent, "tester")
    _write_valid_gate_artifact(parent, 0)
    forked = fork_profile(
        parent,
        profile="engineering_optimization",
        reviewer="tester",
        reason="Gate 0 将该题识别为工程优化问题。",
        transaction_id="e2efork01",
    )
    child = Path(forked["child_run"])
    assert verify_run(parent)["lifecycle_status"] == "superseded"

    _prepare_completed_gate_run(child, reviewer="tester")
    report = complete_and_seal_run(child, "tester")
    assert report["sealed"] is True
    assert report["eligible_for_promotion"] is False

    (child / "response.md").write_text("审阅说明可更新。", encoding="utf-8")
    assert verify_run(child)["sealed"] is True

    result_report = child / "result_report.json"
    result = json.loads(result_report.read_text(encoding="utf-8"))
    result["conclusions"].append("tampered")
    result_report.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        verify_run(child)
