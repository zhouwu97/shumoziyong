from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collector_core import collect  # noqa: E402


def _source(root: Path) -> Path:
    root.mkdir(); (root / "workspace" / "code").mkdir(parents=True); (root / "materials").mkdir()
    (root / "model_route_v2.json").write_text("{}", encoding="utf-8")
    (root / "environment_lock.json").write_text('{"solver":{"name":"deterministic_greedy","version":"1","status":"optimal"}}', encoding="utf-8")
    (root / "execution_spec.json").write_text(json.dumps({"network_access": False, "tasks": [{"task_id":"Q1_DRYLAND_BASELINE", "argv":["python", "code/solve.py"], "timeout_seconds":30}]}), encoding="utf-8")
    (root / "workspace" / "code" / "solve.py").write_text("from pathlib import Path\nimport json\nPath('output').mkdir(exist_ok=True)\nPath('output/decision_variables.json').write_text(json.dumps({'schema_version':'1.0.0','problem_id':'2024-C','scope':'q1_dryland_single_season_baseline','task_id':'Q1_DRYLAND_BASELINE','assignments':[{'plot_id':'A1','crop_id':1,'area_mu':10}],'objective_reported':2900}))", encoding="utf-8")
    book = Workbook(); land = book.active; land.title = "乡村的现有耕地"; land.append(["地块名称","地块类型","地块面积/亩"]); land.append(["A1","平旱地",10]); book.save(root / "materials" / "附件1.xlsx")
    book = Workbook(); stats = book.active; stats.title = "2023年统计的相关数据"; stats.append(["序号","作物编号","作物名称","地块类型","种植季次","亩产量/斤","种植成本/(元/亩)","销售单价/(元/斤)"]); stats.append([1,1,"黄豆","平旱地","单季",100,10,"2.00-4.00"]); book.save(root / "materials" / "附件2.xlsx")
    (root / "materials" / "material_manifest.json").write_text("{}", encoding="utf-8")
    return root


def test_collector_generates_formal_result_only_after_independent_validation(tmp_path: Path) -> None:
    result = collect(_source(tmp_path / "source"), tmp_path / "results")
    assert result["contract_version"] == "formal_result_v1"
    assert result["candidate_output_used"] is False
    assert result["recomputed_objective"] == 2900
    formal = tmp_path / "results" / "formal_results" / result["formal_result_id"]
    assert (formal / "formal_result_manifest.json").is_file()
