from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from validate_semantic_map import validate_paper_semantics  # noqa: E402


def _write(path: Path, text: str) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {"path": path.relative_to(path.parents[1]).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    statement = "2023-B 多波束测深：计算覆盖宽度、重叠率并优化测线方向。"
    sections = "\n".join([
        "变量与符号", "模型推导", "目标函数", "约束条件", "求解算法",
        "模型检验", "结果分析", "误差分析", "参考文献",
    ])
    bindings = []
    formulas = []
    paragraphs = []
    for index in range(1, 5):
        task = f"Q{index} 多波束覆盖宽度与重叠率数学任务"
        formula = f"W_{index}=2D tan(theta/{index + 1})"
        result = f"Q{index} 测线方向求解结果为候选 {index}"
        paragraphs.extend([task, formula, result, f"图{index}", f"结论{index}"])
        formula_id = f"F-Q{index}"
        formulas.append({
            "formula_id": formula_id,
            "expression": formula,
            "derivation_location": f"第{index}问模型推导",
            "problem_specific": True,
        })
        bindings.append({
            "subproblem_id": f"Q{index}",
            "mathematical_task": task,
            "variable_ids": [f"V{index}"],
            "formula_ids": [formula_id],
            "result_ids": [f"R{index}"],
            "figure_or_table_ids": [f"FIG{index}"],
            "conclusion_ids": [f"C{index}"],
            "model_formula_text": formula,
            "solver_result_text": result,
        })
    paper = "\n".join([
        "2023-B 多波束测深中的覆盖宽度、重叠率和测线方向", sections, *paragraphs
    ])
    source_dir = tmp_path / "source"
    paper_ref = _write(source_dir / "paper.md", paper)
    statement_ref = _write(source_dir / "problem.txt", statement)
    semantic_map = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_semantic_map_v1",
        "run_id": "semantic-2023b-fixture",
        "problem_id": "2023-B",
        "paper_text": paper_ref,
        "problem_statement": statement_ref,
        "bindings": bindings,
        "formula_catalog": formulas,
    }
    registry = json.loads(
        (ROOT / "runtime_contracts/problem_semantics_registry_v1.json").read_text(encoding="utf-8")
    )
    return semantic_map, registry


def test_2023b_complete_problem_specific_semantic_chain_passes(tmp_path: Path) -> None:
    semantic_map, registry = _fixture(tmp_path)
    report = validate_paper_semantics(semantic_map, registry, root=tmp_path)
    assert report["status"] == "passed"
    assert report["checked_subproblems"] == ["Q1", "Q2", "Q3", "Q4"]


def test_2023b_production_and_sampling_topic_is_rejected(tmp_path: Path) -> None:
    semantic_map, registry = _fixture(tmp_path)
    paper_path = tmp_path / semantic_map["paper_text"]["path"]
    paper_path.write_text("生产装配与抽样检验中的次品率和拆解决策", encoding="utf-8")
    semantic_map["paper_text"]["sha256"] = hashlib.sha256(paper_path.read_bytes()).hexdigest()
    report = validate_paper_semantics(semantic_map, registry, root=tmp_path)
    assert report["status"] == "failed"
    assert "PSM_REQUIRED_ENTITY_MISSING" in report["failure_codes"]
    assert "PSM_FORBIDDEN_ENTITY_PRESENT" in report["failure_codes"]


def test_each_subproblem_requires_its_own_model_and_result(tmp_path: Path) -> None:
    semantic_map, registry = _fixture(tmp_path)
    semantic_map["bindings"] = semantic_map["bindings"][:-1]
    report = validate_paper_semantics(semantic_map, registry, root=tmp_path)
    assert report["status"] == "failed"
    assert "PSM_SUBPROBLEM_COVERAGE" in report["failure_codes"]


def test_generic_route_selection_formula_is_not_formal_model(tmp_path: Path) -> None:
    semantic_map, registry = _fixture(tmp_path)
    semantic_map = copy.deepcopy(semantic_map)
    semantic_map["formula_catalog"][0]["expression"] = "r_star = arg max_{r in F} z_r"
    report = validate_paper_semantics(semantic_map, registry, root=tmp_path)
    assert report["status"] == "failed"
    assert "PSM_GENERIC_FORMULA_FORBIDDEN" in report["failure_codes"]
