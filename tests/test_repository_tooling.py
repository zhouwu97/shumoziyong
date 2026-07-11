from __future__ import annotations

import hashlib
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
from run_workflow import (  # noqa: E402
    GATE_NAMES,
    VALID_TRANSITIONS,
    create_old_problem_run,
    get_current_gate,
    is_gate_complete,
    mark_run_completed,
    record_transition,
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
        "problem_manifest", "automatic_evaluation", "ai_run_metadata", "human_review",
    }


def test_finalize_run_evidence_seals_current_files_and_detects_later_tampering(tmp_path: Path) -> None:
    """封存命令应重建最终哈希；随后篡改 response 必须可被校验器发现。"""
    materials = tmp_path / "materials"
    materials.mkdir()
    pdf_data = b"fake problem pdf"
    (materials / "problem.pdf").write_bytes(pdf_data)
    _write_material_manifest(materials, "2024-C", {"problem": [("problem.pdf", pdf_data)]})
    args = Namespace(
        run_id="sealed_run", output_root=str(tmp_path / "runs"), problem="2024-C",
        profile="engineering_optimization", gates="0-2", materials=str(materials),
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

    evidence = finalize_run_evidence(run_dir)
    required_artifacts = json.loads((ROOT / "policies" / "promotion_policy.json").read_text(encoding="utf-8"))["run_evidence_requirements"]["ai_run_metadata_checks"]["required_artifacts"]
    assert json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))["status"] == "sealed"
    assert not validate_evidence_manifest(run_dir, evidence, required_artifacts)

    with (run_dir / "response.json").open("a", encoding="utf-8") as response:
        response.write("\n篡改")
    assert any("response.json" in error and "sha256" in error for error in validate_evidence_manifest(run_dir, evidence, required_artifacts))


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
    assert {p["patch_id"] for p in pack_manifest["patches"]} == {"A092"}

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
    assert report["policy_version"] == "1.3.0"
    assert report["total_patches"] == 4
    assert "per_patch" in report
    assert "verdict" in report
    # A092 and A127 have all 3 controls passing and satisfy verified_candidate rules
    a092 = next(p for p in report["per_patch"] if p["patch_id"] == "A092")
    assert a092["positive"] == "pass"
    assert a092["boundary"] == "pass"
    assert a092["negative"] == "pass"
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
    g = PromotionGap("A092", "stable", "需要人工确认")
    s = str(g)
    assert "A092" in s
    assert "stable" in s
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
    (run_dir / "gate_5_review.json").write_text('{"final_acceptance": true, "reviewer": "automated_test"}', encoding="utf-8")
    mark_run_completed(run_dir, "automated_test")
    assert is_gate_complete(run_dir, 5) is True


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
