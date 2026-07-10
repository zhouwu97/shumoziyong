from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_prompt_response import evaluate_case  # noqa: E402
from export_runtime_pack import (  # noqa: E402
    build_manifest,
    build_pack,
    select_patch_files,
    select_patches,
)
from run_workflow import create_old_problem_run  # noqa: E402


def test_default_pack_excludes_candidate_patches() -> None:
    selected = select_patch_files("engineering_optimization")
    assert "prompt_patches/patch_A092_engineering_optimization.md" in selected
    assert "prompt_patches/patch_A127_engineering_layout_optimization.md" in selected
    assert not any("B311" in path or "B477" in path for path in selected)


def test_manifest_hashes_pack_and_records_exclusions() -> None:
    pack = build_pack("engineering_optimization")
    manifest = build_manifest("engineering_optimization", pack)
    assert manifest["runtime_pack_sha256"]
    assert {item["patch_id"] for item in manifest["patches"]} == {"A092", "A127"}
    assert {item["patch_id"] for item in manifest["excluded_patches"]} == {"B311", "B477"}
    # 新增：默认导出不启用实验标记
    assert manifest["candidate_experiment"]["enabled"] is False
    assert manifest["exclusion_experiment"]["enabled"] is False


def test_verified_patches_and_condition_prevents_dangling_verified_export() -> None:
    """verified_candidate/stable 但未进入 verified_patches 的 patch 不得进入正式包。
    当前 A092/A127 都在 verified_patches，故默认应包含；本测试确认 AND 条件不误伤已批准 patch。"""
    selected = select_patches("engineering_optimization")
    assert {p["patch_id"] for p in selected} == {"A092", "A127"}


def test_candidate_patch_explicit_import() -> None:
    """显式 --candidate-patch B311 才会导入 candidate；不会一次导入全部 candidate。"""
    selected = select_patches("engineering_optimization", candidate_patch_ids=["B311"])
    ids = {p["patch_id"] for p in selected}
    assert "B311" in ids
    assert "B477" not in ids  # 不会一次导入全部 candidate
    assert "A092" in ids and "A127" in ids  # 已批准 patch 仍保留


def test_exclude_patch_isolation_runs() -> None:
    """隔离实验：baseline / A092-only / A127-only。"""
    baseline = select_patches("engineering_optimization", exclude_patch_ids=["A092", "A127"])
    assert [p["patch_id"] for p in baseline] == []
    a092_only = select_patches("engineering_optimization", exclude_patch_ids=["A127"])
    assert {p["patch_id"] for p in a092_only} == {"A092"}
    a127_only = select_patches("engineering_optimization", exclude_patch_ids=["A092"])
    assert {p["patch_id"] for p in a127_only} == {"A127"}


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
    (materials / "problem.pdf").write_bytes(b"fake problem pdf")
    (materials / "data.xlsx").write_bytes(b"fake xlsx")
    args = Namespace(
        run_id="test_run",
        output_root=str(tmp_path / "runs"),
        problem="2024-C",
        profile="engineering_optimization",
        gates="0-2",
        materials=str(materials),
        candidate_patch=[],
        exclude_patch=[],
    )
    run_dir, ready = create_old_problem_run(args)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert ready is True
    assert manifest["automatic_stable_update"] is False
    assert manifest["experiment_kind"] == "standard"
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


def test_old_problem_cli_isolation_run_records_exclusion(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    args = Namespace(
        run_id="test_isolation",
        output_root=str(tmp_path / "runs"),
        problem="2024-C",
        profile="engineering_optimization",
        gates="0-2",
        materials=str(materials),
        candidate_patch=[],
        exclude_patch=["A127"],
    )
    run_dir, ready = create_old_problem_run(args)
    assert ready is True
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["experiment_kind"] == "isolation"
    assert manifest["excluded_patches"] == ["A127"]
    pack_manifest = json.loads((run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8"))
    assert pack_manifest["exclusion_experiment"]["enabled"] is True
    assert {p["patch_id"] for p in pack_manifest["patches"]} == {"A092"}
