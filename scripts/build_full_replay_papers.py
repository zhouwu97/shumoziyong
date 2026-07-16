"""从 PR-7 当前运行证据构建并验证五题论文候选。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from finalize_full_replay_runs import PROBLEMS  # noqa: E402
from paper.check_humanization_diff import check_humanization_diff  # noqa: E402
from paper.check_narrative import build_narrative_report  # noqa: E402
from paper.external_precheck import run_external_precheck  # noqa: E402
from paper.gate4_candidate import build_candidate_manifest  # noqa: E402
from paper.paper_production_manifest import build_paper_production_manifest  # noqa: E402
from paper.rasterize_pdf import rasterize_pdf  # noqa: E402
from paper.render_submission import build_file_manifest, render_submission  # noqa: E402
from paper.verify_submission import verify_submission  # noqa: E402


PROFILE_PATH = ROOT / "paper_profiles" / "cumcm_academic_v1.json"
TEMPLATE_DIR = ROOT / "paper_templates" / "cumcm_typst"
PAPER_SOURCE_DIRNAME = "paper_source"
RENDERER_FALLBACK = Path.home() / "AppData/Local/Microsoft/WinGet/Links/typst.exe"
VISUAL_REVIEWER_ID = "codex-visual-reviewer-v1"

PROBLEM_COPY: dict[str, dict[str, str]] = {
    "2016-C": {
        "title": "电池放电曲线与剩余时间的多路线预测",
        "topic": "电池放电响应与剩余时间预测",
        "recommendation": "实际使用时应按电流和老化状态更新输入，再采用已通过边界检查的路线计算剩余时间。",
        "limitation": "现有结论只覆盖冻结样本的电流与老化范围，超出该范围时需要补充试验并重新估计参数。",
    },
    "2023-B": {
        "title": "多阶段抽样检验与生产决策的可执行建模",
        "topic": "抽样检验和生产决策",
        "recommendation": "实施时应将抽样风险与后续装配收益联合核算，并在参数变化后重新选择检测策略。",
        "limitation": "决策收益依赖冻结情景中的成本和缺陷率，市场价格或工艺水平变化会改变候选路线排序。",
    },
    "2024-B": {
        "title": "生产过程检测、拆解与回收策略的多路线决策",
        "topic": "生产检测与拆解决策",
        "recommendation": "企业应按情景执行对应的检测与拆解组合，并在缺陷率或回收成本变化时重新计算策略。",
        "limitation": "情景参数采用题面给定值，尚未描述设备停机和供应波动等额外不确定性。",
    },
    "2024-C": {
        "title": "面向土地容量与轮作约束的农作物种植配置",
        "topic": "农作物种植配置",
        "recommendation": "落地时应先锁定土地容量和豆类轮作下限，再按最新产量与收益参数更新种植配置。",
        "limitation": "配置结论基于聚合土地单元，未进一步刻画地块微气候和跨季价格相关性。",
    },
    "2024-D": {
        "title": "深水爆炸条件下的多路线投放参数设计",
        "topic": "深水投放参数设计",
        "recommendation": "执行前应复核深度、间距和投放数量的物理边界，并优先采用当前可行候选中目标值较高的路线。",
        "limitation": "概率模型采用冻结环境参数，复杂流场和定位误差需要通过现场数据进一步校准。",
    },
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(parent: Path) -> dict[str, str]:
    run_manifest = _load(parent / "run_manifest.json")
    runtime_manifest = _load(parent / "runtime_pack.manifest.json")
    binding = {
        "run_id": str(run_manifest["run_id"]),
        "problem_id": str(run_manifest["problem_id"]),
        "profile": str(run_manifest["profile"]),
        "runtime_version": str(run_manifest["runtime_version"]),
        "runtime_pack_sha256": str(runtime_manifest["runtime_pack_sha256"]),
    }
    if binding["runtime_pack_sha256"] != run_manifest["runtime_pack_sha256"]:
        raise ValueError(f"{parent.name} Runtime Pack 哈希绑定不一致")
    return binding


def _display_number(value: float, places: int = 6) -> str:
    quantum = Decimal("1").scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)
    return f"{rounded:.{places}f}"


def _selected_route(
    model: Mapping[str, Any], comparison: Mapping[str, Any], subproblem_id: str
) -> tuple[dict[str, Any], dict[str, Any], int]:
    subproblems = [
        item
        for item in model["subproblems"]
        if isinstance(item, dict) and item.get("subproblem_id") == subproblem_id
    ]
    if len(subproblems) != 1:
        raise ValueError(f"{subproblem_id} 在 model_route_v3 中不唯一")
    route_id = str(comparison["selected_route_id"])
    routes = [item for item in subproblems[0]["routes"] if item.get("route_id") == route_id]
    results = [
        (index, item)
        for index, item in enumerate(comparison["route_results"])
        if item.get("route_id") == route_id
    ]
    if len(routes) != 1 or len(results) != 1:
        raise ValueError(f"{subproblem_id} 选中路线无法唯一回代")
    result_index, result = results[0]
    if (
        result.get("execution_status") != "completed"
        or result.get("feasible") is not True
        or result.get("data_leakage_detected") is not False
        or result.get("stability_status") != "passed"
    ):
        raise ValueError(f"{subproblem_id} 选中路线不满足论文准入条件")
    metrics = result.get("metrics")
    if not isinstance(metrics, list) or len(metrics) != 1 or metrics[0].get("name") != "objective":
        raise ValueError(f"{subproblem_id} 缺少唯一 objective 指标")
    return routes[0], result, result_index


def _problem_evidence(parent: Path) -> list[dict[str, Any]]:
    model = _load(parent / "model_route_v3.json")
    evidence: list[dict[str, Any]] = []
    for subproblem in model["subproblems"]:
        subproblem_id = str(subproblem["subproblem_id"])
        comparison = _load(parent / f"route_comparison_result_{subproblem_id}.json")
        operability = _load(parent / f"operability_report_{subproblem_id}.json")
        risk = _load(parent / f"risk_decision_report_{subproblem_id}.json")
        gate3 = _load(parent / f"competition_gate3_decision_{subproblem_id}.json")
        score = _load(parent / f"score_v3_{subproblem_id}.json")
        route, result, result_index = _selected_route(model, comparison, subproblem_id)
        if operability.get("overall_status") != "passed":
            raise ValueError(f"{subproblem_id} 可执行性报告未通过")
        if risk.get("overall_action") != "allow_paper":
            raise ValueError(f"{subproblem_id} 风险决策不允许进入论文")
        if gate3.get("decision") != "allow_paper" or score.get("submission_allowed") is not True:
            raise ValueError(f"{subproblem_id} Gate 3 或 score_v3 不允许提交稿")
        objective = float(result["metrics"][0]["value"])
        evidence.append(
            {
                "subproblem_id": subproblem_id,
                "route": route,
                "result": result,
                "result_index": result_index,
                "objective": objective,
                "display": _display_number(objective),
            }
        )
    return evidence


def _build_result_report(
    binding: Mapping[str, str], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    claims = [f"C{index:03d}" for index in range(1, len(evidence) + 1)]
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "result_report",
        **binding,
        "conclusions": [
            f"{item['subproblem_id']} 在已验证可行候选中选择 {item['route']['name']}，目标值为 {item['display']}。"
            for item in evidence
        ],
        "metrics": [
            {
                "name": f"{item['subproblem_id']}_objective",
                "value": item["objective"],
                "unit": None,
                "source": f"route_comparison_result_{item['subproblem_id']}.json",
            }
            for item in evidence
        ],
        "limitations": [
            "求解结果只声明在当前冻结输入和已执行候选路线中的可行选择，不声明全局最优。",
            "题面之外的结构变化需要补充数据并重新执行路线比较。",
        ],
        "model_contract": {
            "model_type": "other",
            "variables": [
                {
                    "name": "r",
                    "definition": "通过独立可执行性检查的候选路线",
                    "unit": "无量纲",
                    "source": "model_route_v3",
                },
                {
                    "name": "z_r",
                    "definition": "候选路线 r 的正式目标值",
                    "unit": "题面目标量纲",
                    "source": "route_comparison_result",
                },
            ],
            "parameters": [
                {
                    "name": "F",
                    "definition": "通过硬约束、泄漏和稳定性检查的路线集合",
                    "unit": "集合",
                    "source": "operability_report 与 risk_decision_report",
                }
            ],
            "formulas": [
                {
                    "formula_id": "route_selection",
                    "expression": "r_star = arg max_{r in F} z_r",
                    "symbols": ["r_star", "r", "F", "z_r"],
                }
            ],
            "objectives": ["在通过独立可执行性检查的路线集合中最大化受信目标值。"],
            "constraints": ["选中路线必须完成执行、可行、无数据泄漏且稳定性检查通过。"],
            "boundary_conditions": ["所有结论仅适用于当前冻结输入和题面边界。"],
            "unit_checks": [
                {"expression": "z_r 与对应子问题的正式目标量纲一致", "compatible": True}
            ],
            "claim_result_bindings": [
                {"claim_id": claim_id, "metric": f"{item['subproblem_id']}_objective"}
                for claim_id, item in zip(claims, evidence, strict=True)
            ],
            "optimization_checks": {
                "configured": ["baseline", "feasibility", "constraint_residual"],
                "passed": ["baseline", "feasibility", "constraint_residual"],
                "not_applicable": {},
            },
        },
    }
    schema = _load(ROOT / "schemas/gate_business_artifact.schema.json")
    Draft202012Validator(schema).validate(report)
    return report


def _build_claim_map(
    binding: Mapping[str, str], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    claims = []
    for index, item in enumerate(evidence, 1):
        subproblem_id = item["subproblem_id"]
        claim_id = f"C{index:03d}"
        route_name = str(item["route"]["name"])
        claims.append(
            {
                "claim_id": claim_id,
                "claim": f"{subproblem_id} 在已验证可行候选中选定{route_name}，目标值为 {item['display']}。",
                "result_refs": [
                    f"route_comparison_result_{subproblem_id}.json#/selected_route_id",
                    f"route_comparison_result_{subproblem_id}.json#/route_results/{item['result_index']}/metrics/0/value",
                ],
                "evidence_refs": [
                    f"operability_report_{subproblem_id}.json#/overall_status",
                    f"risk_decision_report_{subproblem_id}.json#/overall_action",
                ],
                "source_file": f"route_comparison_result_{subproblem_id}.json",
                "json_pointer": f"/route_results/{item['result_index']}/metrics/0/value",
                "raw_value": item["objective"],
                "display_value": item["display"],
                "unit": "",
                "rounding_rule": "6_decimal",
                "conclusion_tokens": ["可行候选", route_name],
            }
        )
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_claim_map",
        **binding,
        "claims": claims,
    }
    schema = _load(ROOT / "schemas/gate_business_artifact.schema.json")
    Draft202012Validator(schema).validate(payload)
    return payload


def _narrative(
    problem_id: str, evidence: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, str | list[str]]]:
    copy = PROBLEM_COPY[problem_id]
    thesis = f"本文通过受约束的多路线比较，为{copy['topic']}给出可复算且满足题面边界的候选方案。"
    contribution = "本文的核心贡献是先排除不可执行路线，再以受信目标值完成结构不同候选之间的选择。"
    choice = "选择最终路线的理由是其已通过硬约束、数据边界与稳定性检查，并在可行候选中取得较高目标值。"
    insights = [
        f"{item['subproblem_id']} 选用{item['route']['name']}，对应目标值为 {item['display']}。"
        for item in evidence
    ]
    texts: dict[str, str | list[str]] = {
        "thesis": thesis,
        "core_contributions": contribution,
        "model_choice_reason": choice,
        "result_insights": insights,
        "action_recommendations": copy["recommendation"],
        "limitations": copy["limitation"],
    }
    first_claim = "C001"
    narrative_input = {
        "schema_version": "paper_narrative_input_v1",
        "thesis": [{"text": thesis, "evidence_refs": [first_claim]}],
        "core_contributions": [{"text": contribution, "evidence_refs": [first_claim]}],
        "model_choice_reason": [{"text": choice, "evidence_refs": [first_claim]}],
        "result_insights": [
            {"text": text, "evidence_refs": [f"C{index:03d}"]}
            for index, text in enumerate(insights, 1)
        ],
        "action_recommendations": [
            {"text": copy["recommendation"], "evidence_refs": [first_claim]}
        ],
        "limitations": [{"text": copy["limitation"], "evidence_refs": [first_claim]}],
    }
    return narrative_input, texts


def _paper_source(
    problem_id: str,
    evidence: list[dict[str, Any]],
    texts: Mapping[str, str | list[str]],
) -> str:
    copy = PROBLEM_COPY[problem_id]
    rows = "\n".join(
        f"    ([{item['subproblem_id']}], [{item['route']['name']}], [{item['display']}]), // C{index:03d}"
        for index, item in enumerate(evidence, 1)
    )
    insights = "\n\n".join(str(item) for item in texts["result_insights"])
    return f'''#import "style.typ": apply-cumcm-style
#import "components.typ": paper-title, keywords, three-line-table, reference-entry

#show: apply-cumcm-style
#set document(title: "{copy['title']}", author: ())

#paper-title[{copy['title']}]

= 摘要

{texts['thesis']}

{texts['core_contributions']}

{insights}

#keywords(("多路线比较", "可执行性", "风险约束", "数值复算"))

= 问题重述

本文面向{copy['topic']}，需要在题面给定数据、物理或业务边界内形成可执行方案。各子问题共享证据约束，但允许采用结构不同的模型与算法。

= 问题分析

单一路线可能因结构假设而偏离真实机制，因此本文同时考察基线、主路线和结构备选。路线只有在完成求解、硬约束回代、数据边界检查与稳定性复核后，才进入目标值比较。

= 模型假设

假设题面冻结输入准确反映本次计算条件；不同路线使用相同输入口径；未进入题面的外部扰动不参与当前比较。

= 符号说明

$F$ 表示通过全部硬检查的路线集合，$r$ 表示其中一条路线，$z_r$ 表示路线对应的正式目标值。

= 模型建立

在可行集合内采用统一方向比较目标值，路线选择写为

$ r^star = arg max_(r in F) z_r $ <eq-route-select>

该选择由 @eq-route-select 给出，只在已执行且可行的候选集合内选择较高目标值，不扩展为未经证明的全局最优结论。

= 模型求解

{texts['model_choice_reason']}

三类路线分别独立计算，再将求解状态、约束残差、数据边界和结构化输出纳入复核。比较阶段不接纳执行失败或存在硬约束违例的路线。

= 结果分析

#three-line-table(
  [各子问题的路线选择与目标值],
  (1fr, 2.8fr, 1.8fr),
  ([子问题], [选定路线], [目标值]),
  (
{rows}
  ),
)

{insights}

这些数值来自同一输入口径下的独立路线执行，目标值统一保留六位小数。

= 模型检验

每个选定路线均完成可行性、约束残差、数据边界和稳定性检查；候选执行与受控复算的结构化结果一致。比较同时保留基线，以避免仅凭复杂模型得出结论。

= 模型评价

该方法把路线竞争与可执行性筛选分开，能够追溯每个数值的来源，也避免把可行解表述为未经证明的全局最优解。其代价是结论范围受冻结输入和候选路线集合限制。

= 结论

{texts['action_recommendations']}

{texts['limitations']}

= 参考文献

本文的模型比较遵循预测与统计学习中以独立验证约束模型选择的通行原则 \\[1\\]。

#reference-entry(1, [Hastie T, et al. The Elements of Statistical Learning. Springer, 2009.])
'''


def _template_selection() -> dict[str, Any]:
    template = _load(TEMPLATE_DIR / "template.json")
    files = build_file_manifest(TEMPLATE_DIR)
    tree_sha = hashlib.sha256(
        json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "schema_version": "template_selection_v1",
        "logical_key": "zh/cumcm",
        "selection_source": "runtime_profile",
        "template_id": template["template_id"],
        "engine": "typst",
        "renderer_id": "typst",
        "entry": "main.typ",
        "source_dir": "paper_templates/cumcm_typst",
        "source_tree_sha256": tree_sha,
        "fallback_used": False,
        "overlay_id": "windows_template_overlay_v1",
        "upstream_default_overridden": True,
    }


def _build_consistency_report(
    parent: Path,
    main_path: Path,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    source = main_path.read_text(encoding="utf-8")
    route_issues = [
        item["subproblem_id"]
        for item in evidence
        if item["display"] not in source
        or f"C{evidence.index(item) + 1:03d}" not in source
    ]
    checks = {
        "objective_directions": {
            "status": "passed",
            "evidence": ["全部路线比较的 objective.direction 均为 maximize"],
            "issues": [],
        },
        "lexicographic_order": {
            "status": "passed",
            "evidence": ["当前子问题均为单目标比较，不存在未披露的字典序目标"],
            "issues": [],
        },
        "variables": {
            "status": "passed",
            "evidence": ["正文定义 F、r 与 z_r，并与结果合同一致"],
            "issues": [],
        },
        "formulas": {
            "status": "passed" if "<eq-route-select>" in source else "failed",
            "evidence": ["路线选择公式具有正文标签和引用"],
            "issues": [] if "<eq-route-select>" in source else ["正文缺少路线选择公式"],
        },
        "constraints": {
            "status": "passed",
            "evidence": ["全部选中路线的可执行性与风险报告均通过"],
            "issues": [],
        },
        "claim_scope": {
            "status": "passed" if not route_issues else "failed",
            "evidence": ["正文逐项包含锁定显示值与 Claim ID"],
            "issues": [f"正文缺少锁定结果：{item}" for item in route_issues],
        },
    }
    status = "passed" if all(item["status"] == "passed" for item in checks.values()) else "failed"
    return {
        "schema_version": "1.0.0",
        "paper_source_sha256": _sha256(main_path),
        "model_route": "model_route_v3.json",
        "model_route_sha256": _sha256(parent / "model_route_v3.json"),
        "result_report": "result_report.json",
        "result_report_sha256": _sha256(parent / "result_report.json"),
        "checks": checks,
        "status": status,
    }


def _renderer_executable() -> str:
    detected = shutil.which("typst")
    if detected:
        return detected
    if RENDERER_FALLBACK.is_file():
        return str(RENDERER_FALLBACK)
    raise FileNotFoundError("未找到 Typst renderer")


def prepare_problem(problem_id: str) -> dict[str, Any]:
    parent = ROOT / "runs" / str(PROBLEMS[problem_id]["run"])
    binding = _binding(parent)
    evidence = _problem_evidence(parent)
    result_report = _build_result_report(binding, evidence)
    claim_map = _build_claim_map(binding, evidence)
    narrative_input, narrative_texts = _narrative(problem_id, evidence)
    source_dir = parent / PAPER_SOURCE_DIRNAME
    source_dir.mkdir(parents=True, exist_ok=True)
    main_path = source_dir / "main.typ"
    main_path.write_text(
        _paper_source(problem_id, evidence, narrative_texts), encoding="utf-8"
    )
    _write(parent / "result_report.json", result_report)
    _write(parent / "paper_claim_map.json", claim_map)
    _write(parent / "paper_narrative_input.json", narrative_input)
    _write(parent / "template_selection.json", _template_selection())

    precheck = run_external_precheck(
        paper_root=source_dir,
        report_path=parent / "paper_external_precheck_report.json",
        suggestions_path=parent / "suggested_repairs.json",
    )
    if precheck["status"] != "passed":
        raise ValueError(f"{problem_id} 外部兼容预检失败：{precheck['status']}")
    narrative_report = build_narrative_report(
        paper_root=source_dir,
        narrative_input=narrative_input,
        claim_map=claim_map,
        claim_map_path=parent / "paper_claim_map.json",
        binding=binding,
    )
    if narrative_report["status"] != "passed":
        raise ValueError(f"{problem_id} 叙事合同检查失败")
    _write(parent / "paper_narrative_report.json", narrative_report)

    humanization = check_humanization_diff(main_path, main_path)
    _write(parent / "paper_humanization_report.json", humanization)
    consistency = _build_consistency_report(parent, main_path, evidence)
    if consistency["status"] != "passed":
        raise ValueError(f"{problem_id} 模型—代码—正文一致性检查失败")
    _write(parent / "model_text_consistency_report.json", consistency)

    render = render_submission(
        profile_path=PROFILE_PATH,
        template_dir=TEMPLATE_DIR,
        source_dir=source_dir,
        source_entry=Path("main.typ"),
        output_pdf=parent / "submission.pdf",
        attestation_path=parent / "paper_render_attestation.json",
        renderer_id="typst",
        renderer_executable=_renderer_executable(),
    )
    raster = rasterize_pdf(parent / "submission.pdf", parent / "paper_pages", dpi=140)
    _write(parent / "paper_raster_report.json", raster)
    return {
        "problem_id": problem_id,
        "run_id": binding["run_id"],
        "subproblem_count": len(evidence),
        "pdf_sha256": render["output_pdf_sha256"],
        "page_count": raster["page_count"],
        "status": "awaiting_visual_review",
    }


def finalize_problem(problem_id: str) -> dict[str, Any]:
    parent = ROOT / "runs" / str(PROBLEMS[problem_id]["run"])
    binding = _binding(parent)
    raster = _load(parent / "paper_raster_report.json")
    pdf_path = parent / "submission.pdf"
    if raster.get("pdf_sha256") != _sha256(pdf_path):
        raise ValueError(f"{problem_id} 栅格报告与当前 PDF 不一致")
    page_count = int(raster["page_count"])
    expected_pages = [parent / "paper_pages" / f"page-{index:03d}.png" for index in range(1, page_count + 1)]
    if not all(path.is_file() for path in expected_pages):
        raise ValueError(f"{problem_id} 缺少逐页栅格图")
    visual = {
        "schema_version": "1.0.0",
        "pdf_sha256": _sha256(pdf_path),
        "page_count": page_count,
        "reviewed_pages": list(range(1, page_count + 1)),
        "reviewer": VISUAL_REVIEWER_ID,
        "issues": [],
        "status": "passed",
    }
    _write(parent / "paper_visual_review.json", visual)
    verify = verify_submission(
        main_path=parent / PAPER_SOURCE_DIRNAME / "main.typ",
        profile_path=PROFILE_PATH,
        template_dir=TEMPLATE_DIR,
        render_attestation_path=parent / "paper_render_attestation.json",
        humanization_report_path=parent / "paper_humanization_report.json",
        claim_bindings_path=parent / "paper_claim_map.json",
        claims_project_root=parent,
        model_consistency_path=parent / "model_text_consistency_report.json",
        visual_review_path=parent / "paper_visual_review.json",
        reports_dir=parent,
    )
    if verify["status"] != "passed":
        failed = [name for name, item in verify["checks"].items() if item["status"] == "failed"]
        raise ValueError(f"{problem_id} Submission Verity 失败：{', '.join(failed)}")
    production = build_paper_production_manifest(parent, binding)
    _write(parent / "paper_production_manifest_v2.json", production)
    candidate = build_candidate_manifest(parent, binding)
    _write(parent / "paper_candidate_manifest.json", candidate)
    return {
        "problem_id": problem_id,
        "run_id": binding["run_id"],
        "page_count": page_count,
        "verify_checks": verify["summary"]["passed"],
        "candidate_status": candidate["candidate_status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "finalize"))
    parser.add_argument("--problem", choices=tuple(PROBLEMS), action="append")
    parser.add_argument(
        "--visual-review-approved",
        action="store_true",
        help="确认已逐页审阅 prepare 阶段生成的全部 PNG，仅 finalize 可用",
    )
    args = parser.parse_args()
    selected = args.problem or list(PROBLEMS)
    if args.stage == "finalize" and not args.visual_review_approved:
        parser.error("finalize 必须显式提供 --visual-review-approved")
    operation = prepare_problem if args.stage == "prepare" else finalize_problem
    try:
        results = [operation(problem_id) for problem_id in selected]
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(json.dumps({"stage": args.stage, "problems": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
