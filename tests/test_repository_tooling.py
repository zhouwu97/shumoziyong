from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_prompt_response import evaluate_case  # noqa: E402
from export_runtime_pack import build_manifest, build_pack, select_patch_files  # noqa: E402
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


def test_prompt_response_evaluator_is_semantic_not_exact_text() -> None:
    case = {
        "expected": {
            "values": {"primary_type": "optimization"},
            "must_have_paths": ["constraints.budget"],
            "must_not_contain": ["neural_network"],
            "requires_manual_confirmation": True,
        }
    }
    response = {
        "primary_type": "optimization",
        "constraints": {"budget": "不超过 100 万元"},
        "manual_confirmation": ["确认预算口径"],
        "free_text": "先定义变量和约束。",
    }
    assert evaluate_case(case, response) == []


def test_old_problem_cli_creates_traceable_run(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    args = Namespace(
        run_id="test_run",
        output_root=str(tmp_path / "runs"),
        problem="2024-C",
        profile="engineering_optimization",
        gates="0-2",
        materials=str(materials),
        include_candidate_patches=False,
    )
    run_dir, ready = create_old_problem_run(args)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert ready is True
    assert manifest["automatic_stable_update"] is False
    assert (run_dir / "runtime_pack.manifest.json").is_file()
    assert (run_dir / "patch_suggestions.md").is_file()
