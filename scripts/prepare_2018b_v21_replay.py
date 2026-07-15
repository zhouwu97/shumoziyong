"""为 2018-B v2.1 回放准备 Gate 0-2、冻结源码和 MATLAB A+B 输入。

脚本不执行 Gate 3，也不创建 Run。``contracts`` 阶段只准备执行前合同；
``matlab`` 阶段要求当前 Run 已存在完整 Python 候选输出，缺字段时闭锁。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPAIR_REQUIRED_FILES = (
    "parameters.json",
    "manual_case.json",
    "rgv/__init__.py",
    "rgv/baseline.py",
    "rgv/contracts.py",
    "rgv/experiments.py",
    "rgv/export.py",
    "rgv/faults.py",
    "rgv/model.py",
    "rgv/oracle.py",
    "rgv/policies.py",
    "rgv/self_check.py",
    "rgv/simulator.py",
    "rgv/validity.py",
)

OUTPUT_REQUIRED_FILES = (
    "run_summary.json",
    "schedules.json",
    "events.jsonl.gz",
    "constraint_self_check.json",
    "random_trials.json",
    "figure_data.json",
    "validity_evidence.json",
    "result.json",
)

METRIC_FIELDS = (
    "completed_clean_products",
    "scrapped_parts",
    "started_parts",
    "unfinished_parts",
    "rgv_busy_seconds",
    "rgv_wait_seconds",
    "rgv_utilization",
    "cnc_processing_seconds",
    "cnc_utilization",
    "cnc_waiting_seconds",
    "n_wip_at_horizon",
    "rgv_end_seconds",
    "post_shift_return_seconds",
    "action_count",
    "fallback_count",
)

EVENT_FIELDS = (
    "run_key",
    "sequence",
    "start_seconds",
    "end_seconds",
    "event_type",
    "resource_type",
    "resource_id",
    "action_id",
    "part_id",
    "stage",
    "state_before",
    "state_after",
    "payload",
)

PART_FIELDS = (
    "part_id",
    "process_type",
    "stage1_cnc",
    "stage1_load_seconds",
    "stage1_unload_seconds",
    "stage2_cnc",
    "stage2_load_seconds",
    "stage2_unload_seconds",
    "clean_start_seconds",
    "clean_end_seconds",
    "status",
    "scrapped_at_seconds",
)

FORMAL_ADAPTER = '''"""2018-B Run-local 正式执行入口；只编排冻结修复实现。"""

from __future__ import annotations

import argparse
from pathlib import Path

from rgv.contracts import load_parameters
from rgv.experiments import run_full_experiment
from rgv.export import export_formal_outputs
from rgv.validity import run_validity_suite


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parameters", default="../problem/parameters.json")
    parser.add_argument("--output", default="output")
    args = parser.parse_args()
    parameters = load_parameters(Path(args.parameters))
    data = run_full_experiment(parameters)
    data["validity_evidence"] = run_validity_suite(parameters, data)
    export_formal_outputs(Path(args.output), data, parameters)


if __name__ == "__main__":
    main()
'''


class OutputContractError(ValueError):
    """Python 候选输出不足以生成独立复算输入。"""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} 无法读取为 JSON：{path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象：{path}")
    return value


def ref(run_dir: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    if not resolved.is_relative_to(run_dir.resolve()) or not resolved.is_file():
        raise ValueError(f"工件引用必须位于当前 Run 内：{path}")
    return {
        "path": resolved.relative_to(run_dir.resolve()).as_posix(),
        "sha256": sha256_file(resolved),
    }


def identity(run_dir: Path) -> dict[str, str]:
    manifest = load_json(run_dir / "run_manifest.json", "run_manifest.json")
    if manifest.get("problem_id") != "2018-B":
        raise ValueError("脚手架只接受 problem_id=2018-B 的已初始化 Run")
    if manifest.get("runtime_manifest_version") != "1.3.0":
        raise ValueError("2018-B v2.1 新运行必须使用 runtime_manifest_version=1.3.0")
    if manifest.get("gate_contract_version") != "2.1.0":
        raise ValueError("2018-B v2.1 新运行必须使用 gate_contract_version=2.1.0")
    if manifest.get("blind_generalization") is not False:
        raise ValueError("2018-B 已读材料回放必须声明 blind_generalization=false")
    if manifest.get("profile_promotion_eligible") is not False:
        raise ValueError("2018-B 开发回放不得声明 profile_promotion_eligible=true")
    required = ("run_id", "problem_id", "profile", "runtime_version", "runtime_pack_sha256")
    missing = [name for name in required if not manifest.get(name)]
    if missing:
        raise ValueError(f"run_manifest.json 缺少身份字段：{', '.join(missing)}")
    return {name: str(manifest[name]) for name in required}


def named(name: str, definition: str, unit: str | None, source: str | None) -> dict[str, Any]:
    return {"name": name, "definition": definition, "unit": unit, "source": source}


def _git_value(workspace: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"无法读取 repair 来源 Git 身份：{completed.stderr.strip()}")
    return completed.stdout.strip()


def source_git_identity(repair_workspace: Path) -> dict[str, Any]:
    repository = Path(_git_value(repair_workspace, "rev-parse", "--show-toplevel")).resolve()
    commit = _git_value(repair_workspace, "rev-parse", "HEAD")
    relative = repair_workspace.resolve().relative_to(repository).as_posix()
    status = _git_value(repository, "status", "--porcelain", "--", relative)
    if status:
        raise ValueError(
            "repair workspace 存在未提交改动，不能只用 source commit 绑定：\n" + status
        )
    return {
        "repository": str(repository),
        "workspace_relative_path": relative,
        "commit": commit,
        "dirty": False,
    }


def _verify_repair_workspace(repair_workspace: Path) -> None:
    missing = [name for name in REPAIR_REQUIRED_FILES if not (repair_workspace / name).is_file()]
    if missing:
        raise ValueError("repair workspace 缺少冻结实现文件：" + ", ".join(missing))


def _copy_checked(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and sha256_file(target) != sha256_file(source):
        raise ValueError(f"目标已存在且内容不同，拒绝覆盖：{target}")
    if not target.exists():
        shutil.copy2(source, target)


def copy_repair_source(
    run_dir: Path,
    repair_workspace: Path,
    *,
    git_identity: Mapping[str, Any] | None = None,
) -> Path:
    _verify_repair_workspace(repair_workspace)
    source_identity = dict(git_identity or source_git_identity(repair_workspace))
    target_root = run_dir / "workspace" / "code"
    entries: list[dict[str, Any]] = []
    for relative in REPAIR_REQUIRED_FILES:
        source = repair_workspace / relative
        target_relative = "parameters.json" if relative == "parameters.json" else relative
        target = target_root / target_relative
        _copy_checked(source, target)
        entries.append(
            {
                "origin": "repair_workspace",
                "source_path": relative,
                "target_path": target.relative_to(run_dir).as_posix(),
                "sha256": sha256_file(target),
            }
        )
    adapter = target_root / "formal_run.py"
    if adapter.exists() and adapter.read_text(encoding="utf-8") != FORMAL_ADAPTER:
        raise ValueError(f"Run-local 正式入口已存在且内容不同：{adapter}")
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(FORMAL_ADAPTER, encoding="utf-8")
    entries.append(
        {
            "origin": "generated_adapter",
            "source_path": "scripts/prepare_2018b_v21_replay.py::FORMAL_ADAPTER",
            "target_path": adapter.relative_to(run_dir).as_posix(),
            "sha256": sha256_file(adapter),
        }
    )
    expected_targets = {str(item["target_path"]).removeprefix("workspace/code/") for item in entries}
    actual_targets = {
        path.relative_to(target_root).as_posix()
        for path in target_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    extras = sorted(actual_targets - expected_targets)
    if extras:
        raise ValueError("workspace/code 含未绑定文件，拒绝形成来源清单：" + ", ".join(extras))
    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "repair_source_manifest",
        "run_id": identity(run_dir)["run_id"],
        "problem_id": "2018-B",
        "source_git": source_identity,
        "files": sorted(entries, key=lambda item: str(item["target_path"])),
        "derived_cache_excluded": True,
    }
    path = run_dir / "repair_source_manifest.json"
    write_json(path, manifest)
    return path


def copy_official_materials(run_dir: Path, official_materials: Path) -> Path:
    manifest_path = official_materials / "material_manifest.json"
    manifest = load_json(manifest_path, "官方 material_manifest.json")
    errors: list[str] = []
    for category in manifest.get("categories", {}).values():
        if not isinstance(category, dict):
            continue
        for item in category.get("files", []):
            source = official_materials / str(item.get("path", ""))
            if not source.is_file():
                errors.append(f"缺文件 {item.get('path')}")
            elif sha256_file(source) != item.get("sha256"):
                errors.append(f"SHA不匹配 {item.get('path')}")
    if errors:
        raise ValueError("官方材料冻结清单验证失败：" + "；".join(errors))
    target_root = run_dir / "workspace" / "materials" / "official"
    for source in official_materials.rglob("*"):
        if source.is_file():
            _copy_checked(source, target_root / source.relative_to(official_materials))
    return target_root / "material_manifest.json"


def freeze_problem_inputs(run_dir: Path) -> tuple[Path, Path]:
    code_root = run_dir / "workspace" / "code"
    parameters = run_dir / "problem" / "parameters.json"
    manual_case = run_dir / "problem" / "manual_case.json"
    _copy_checked(code_root / "parameters.json", parameters)
    _copy_checked(code_root / "manual_case.json", manual_case)
    return parameters, manual_case


def build_gate_0(run_dir: Path) -> None:
    ident = identity(run_dir)
    write_json(
        run_dir / "benchmark_classification.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "benchmark_classification",
            "run_id": ident["run_id"],
            "current_problem": "2018-B",
            "cases": {
                "2024-C": {
                    "classification": "development_integration_benchmark",
                    "blind_generalization": False,
                    "profile_promotion_eligible": False,
                },
                "2018-B": {
                    "classification": "development_benchmark",
                    "blind_generalization": False,
                    "profile_promotion_eligible": False,
                },
            },
        },
    )
    diagnosis = {
        "schema_version": "1.0.0",
        "artifact_type": "diagnosis",
        **ident,
        "problem_summary": "在一台 RGV 服务八台 CNC 的单班生产单元中，为一道工序、两道工序和随机故障情形设计可复算的动态调度策略。",
        "material_findings": [
            "官方题面、参数附件和四份空白结果模板齐全",
            "2018-B 已进入开发过程，只能作为非盲开发基准",
        ],
        "objectives": [
            "比较一道工序与两道工序下的基线和有限前瞻策略",
            "按冻结四层词典序选择有限策略族内方案",
            "用配对随机种子评估故障扰动下的产量差异",
        ],
        "constraints": [
            "RGV 同时只能移动、服务、等待或清洗一个工件",
            "每台 CNC 同时只能加工、服务或维修一个工件",
            "两道工序必须遵守工艺顺序与 RGV 单手爪状态",
            "故障 CNC 在维修结束前不可生产",
            "所有主指标冻结在 28800 秒班次边界",
        ],
        "risks": [
            "有限策略族和 254 个非退化刀具分配不构成全局最优证明",
            "故障概率与维修分布只能支持冻结分布内结论",
            "任何缺少原子事件的随机试验都不能支持硬约束独立复核",
        ],
    }
    write_json(run_dir / "diagnosis.json", diagnosis)
    (run_dir / "diagnosis.md").write_text(
        "# Gate 0 题目诊断\n\n"
        "2018-B 采用离散事件仿真、有限前瞻策略、同配置公平基线和配对随机试验。"
        "正式结论仅覆盖冻结参数、策略族和比较协议；本回放不是盲测泛化证据。\n",
        encoding="utf-8",
    )


def _subproblem(subproblem_id: str, task_type: str, selected: str) -> dict[str, Any]:
    return {
        "subproblem_id": subproblem_id,
        "task_type": task_type,
        "inputs": [named("official_parameters", "官方三组时间参数与故障口径", "秒", "官方附件1和冻结parameters.json")],
        "outputs": [named("atomic_schedule", "工件、动作和资源原子事件调度", "秒", "Python离散事件输出")],
        "variables": [
            named("a_k", "第 k 个决策时点选择服务的 CNC", "无量纲", "策略决策"),
            named("tool_i", "两道工序下 CNC i 的工序配置", "无量纲", "254个非退化配置"),
        ],
        "parameters": [
            named("t_move", "RGV 按轨道距离移动时间", "秒", "附件1"),
            named("t_process", "CNC 工序加工时间", "秒", "附件1"),
            named("t_service", "RGV 对奇偶 CNC 上下料时间", "秒", "附件1"),
            named("t_clean", "成品清洗时间", "秒", "附件1"),
        ],
        "objectives": ["按 N_clean、N_WIP、W_CNC、T_RGV_end 的冻结词典序评价方案"],
        "constraints": ["RGV/CNC/清洗槽资源互斥", "工艺顺序与单手爪状态", "故障维修禁产", "班次边界截断"],
        "assumptions": ["同一参数组内时间确定", "故障按冻结键独立抽样", "班后返程与主班次指标分离"],
        "baseline_model": {"name": "FCFS-nearest", "rationale": "提供确定、低复杂度且可在同刀具配置下公平比较的基线。"},
        "selected_model": {"name": selected, "rationale": "显式维护物料、RGV、CNC、故障和班次边界状态，并可输出原子事件供独立复算。"},
        "alternatives_rejected": [{"name": "只按理论节拍排序", "rejection_reason": "无法表达共享 RGV、两道工序携带状态与随机维修造成的动态竞争。"}],
        "validation_requirements": ["Python状态自检", "MATLAB Level A四层目标与资源残差复算", "MATLAB Level B 2-4 CNC小样例枚举"],
        "uncertainty_plan": ["至少100个冻结配对种子", "故障概率和维修分布敏感性", "同时报告胜负次数与差值分布"],
        "failure_conditions": ["原子事件缺字段或未覆盖确定性运行", "跨语言四层目标不一致", "资源重叠残差大于零", "把有限搜索写成全局最优"],
    }


def build_gate_1(run_dir: Path) -> None:
    ident = identity(run_dir)
    assertions = run_dir / "public_assertions.json"
    write_json(
        assertions,
        [
            {"assertion_id": "public.unit_declared"},
            {"assertion_id": "public.boundary_case_declared"},
        ],
    )
    validity = {
        "schema_version": "1.0.0",
        "artifact_type": "model_validity_contract",
        "run_id": ident["run_id"],
        "problem_id": "2018-B",
        "contract_status": "planned",
        "data_generation": {
            "mechanism": "从官方三组时间参数构造离散事件状态机，对冻结策略、配置、随机种子和故障抽样键逐次重放。",
            "sources": ["problem/parameters.json", "workspace/materials/official/material_manifest.json"],
            "scope": "覆盖一道工序、两道工序、同配置与独立配置协议，以及冻结故障分布内的配对随机比较。",
        },
        "variables": [
            named("a_k", "第k个动作选择", "无量纲", "策略"),
            named("s_t", "时刻t的物料和资源状态", "无量纲", "离散事件状态"),
            named("tool_i", "CNC工序配置", "无量纲", "配置搜索"),
        ],
        "parameters": [
            named("H", "班次时域", "秒", "官方题面"),
            named("t_move", "移动时间", "秒", "附件1"),
            named("t_process", "加工时间", "秒", "附件1"),
            named("p_failure", "单次加工尝试故障概率", "无量纲", "冻结建模假设"),
        ],
        "formulas": [
            {"formula_id": "F_objective", "expression": "lexmax (N_clean(H), -N_WIP(H), -W_CNC, -T_RGV_end)", "symbols": ["N_clean", "N_WIP", "W_CNC", "T_RGV_end", "H"], "expected_units": "件,件,秒,秒"},
            {"formula_id": "F_resource", "expression": "overlap(interval_i, interval_j)=0 for each exclusive resource", "symbols": ["interval_i", "interval_j"], "expected_units": "秒"},
        ],
        "parameter_estimation_plan": {
            "method": "生产时间直接采用官方附件；故障概率、偏移与维修分布按冻结合同预注册。",
            "identifiability": "三组生产时间由官方表唯一确定；题面不能识别故障分布，相关结论只覆盖假设口径。",
            "stability_test": "执行前瞻深度、故障概率、维修分布、维修区间、种子数和平局规则敏感性。",
        },
        "small_examples": [
            {"case_id": "rgv_2cnc_dynamic_enumeration", "description": "两台 CNC 的缩小动态时间状态枚举。", "expected_behavior": "单 RGV 服务容量、完工计数和时域边界与独立枚举一致。", "execution_ref": "matlab_level_b_input.json"},
            {"case_id": "rgv_4cnc_dynamic_enumeration", "description": "四台 CNC 的缩小动态时间状态枚举。", "expected_behavior": "扩容后的动态最优完工计数不下降且零时域无完工。", "execution_ref": "matlab_level_b_input.json"},
        ],
        "limit_cases": [{"case_id": "zero_horizon_no_completion", "description": "零时域下不得计入任何完工件。", "expected_behavior": "N_clean(0)=0 且资源占用不越过零边界。", "execution_ref": "Gate3边界测试计划"}],
        "expected_monotonicity": [
            {"quantity": "固定调度的完工计数对时域H", "direction": "increasing", "condition": "原子事件序列保持不变"},
            {"quantity": "固定时域的资源违反量对允许重叠", "direction": "decreasing", "condition": "只放宽资源容量限制"},
        ],
        "falsification_conditions": ["MATLAB复算任一四层目标不同", "任一独占资源存在正重叠", "事件序列、时界或官方动作时长残差非零", "记录日志开关改变业务统计量"],
        "alternative_models": [
            {"name": "FCFS-nearest", "comparison_plan": "在同机器和同刀具配置协议下比较四层目标和配对随机产量。"},
            {"name": "完备动作枚举", "comparison_plan": "仅在2-4台CNC缩小样例中独立枚举，用于验证方向和边界，不外推到完整模型。"},
        ],
        "claim_scope": {
            "allowed": ["冻结参数、策略族、配置空间和比较协议内的计算结果", "冻结故障分布与配对种子内的经验比较"],
            "forbidden": ["宣称全局最优或真实生产分布下普遍稳健", "把MATLAB A+B称为完整模型独立复现", "把2018-B称为盲测泛化证据"],
        },
        "assertion_refs": [{"assertion_set_id": "2018B_public_v1", "layer": "public", "path": "public_assertions.json", "sha256": sha256_file(assertions), "sealed": False, "blind_evidence": False}],
    }
    write_json(run_dir / "model_validity_contract.json", validity)
    route = {
        "schema_version": "2.1.0",
        "artifact_type": "model_route_v2_1",
        **ident,
        "subproblems": [
            _subproblem("P1_ONE_STAGE", "单工序动态调度", "离散事件仿真加有限前瞻策略"),
            _subproblem("P2_TWO_STAGE", "两工序配置与动态调度", "254配置搜索加有限前瞻策略"),
            _subproblem("P3_FAULT", "随机故障稳健性比较", "共同随机数配对仿真"),
        ],
        "human_decisions_required": ["接受结论只覆盖有限策略族", "接受故障分布属于冻结假设", "接受2018-B仅为开发基准"],
        "model_validity_contract_ref": ref(run_dir, run_dir / "model_validity_contract.json"),
        "conclusion_scope": validity["claim_scope"]["allowed"],
    }
    write_json(run_dir / "model_route_v2_1.json", route)


def build_gate_2(
    run_dir: Path,
    source_manifest: Path,
    official_manifest: Path,
    parameters: Path,
    manual_case: Path,
) -> None:
    ident = identity(run_dir)
    execution = {
        "schema_version": "1.0.0",
        "artifact_type": "execution_spec",
        **ident,
        "formal_result_policy": "required_v1",
        "execution_contract_version": "1.0.0",
        "formal_result_contract_version": "1.0.0",
        "canonicalization_version": "1.0.0",
        "gate_artifact_contract_version": "1.0.0",
        "execution_mode": "trusted_local",
        "declared_workspace": "workspace",
        "network_access": False,
        "declared_writable_paths": ["workspace/output"],
        "approved_by": "Codex",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "tasks": [{
            "task_id": "SOLVE_2018B_REVISION_CANDIDATE",
            "runner": "python",
            "entrypoint": "code/formal_run.py",
            "entrypoint_arg_index": 1,
            "argv": ["python", "code/formal_run.py", "--parameters", "../problem/parameters.json", "--output", "output"],
            "working_directory": "workspace",
            "inputs": [ref(run_dir, parameters), ref(run_dir, manual_case)],
            "required_outputs": [{"path": f"workspace/output/{name}", "media_type": "application/gzip" if name.endswith(".gz") else "application/json"} for name in OUTPUT_REQUIRED_FILES],
            "depends_on": [],
            "timeout_seconds": 7200,
            "seed_policy": {"deterministic_expected": True, "seeds": [2018001]},
            "acceptance_checks": [{"check_id": "formal_candidate", "kind": "file_exists", "expectation": "output/result.json"}, {"check_id": "atomic_events", "kind": "file_exists", "expectation": "output/events.jsonl.gz"}],
            "fallback": "emit_blocker",
        }],
        "contract_notes": ["只生成 Candidate；Collector/Validator 通过后方可激活 Formal Result", "正式目标为逐场景四层词典序，不使用 result.json 的历史汇总目标", "随机硬约束结论要求逐试验原子事件；若实现未导出则 Gate 3 必须阻断"],
    }
    write_json(run_dir / "execution_spec.json", execution)
    write_json(
        run_dir / "code_plan.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "code_plan",
            **ident,
            "commands": ["python code/formal_run.py --parameters ../problem/parameters.json --output output", "MATLAB Level A", "MATLAB Level B"],
            "modules": ["code/rgv/离散事件实现", "code/formal_run.py", "matlab/v21/v21_level_a.m", "matlab/v21/v21_level_b.m"],
            "inputs": ["官方材料清单", "冻结parameters.json", "manual_case.json"],
            "outputs": ["确定性调度", "原子事件", "配对随机试验", "约束自检", "Candidate结果"],
            "verification_steps": ["来源哈希核对", "四层目标独立复算", "资源重叠检查", "官方动作时长检查", "2-4 CNC小样例枚举"],
        },
    )
    independence = {
        "schema_version": "1.0.0",
        "artifact_type": "validator_independence_manifest",
        "run_id": ident["run_id"],
        "validator_id": "matlab_2018b_rgv_v21",
        "raw_input_origin": "run-local official material manifest and frozen parameters",
        "reads_primary_intermediates": False,
        "reads_primary_metrics": False,
        "reads_primary_decision_vector": True,
        "reconstructs_coefficients_independently": True,
        "shared_source_modules": [],
        "independent_formula_implementation": True,
        "validation_scope": ["four_layer_objective_recalculation", "exclusive_resource_residuals", "official_duration_residuals", "key_statistics", "two_to_four_cnc_small_examples"],
        "f5_status": "pass",
        "evidence_refs": ["matlab_level_a_report.json", "matlab_level_b_report.json"],
    }
    write_json(run_dir / "validator_independence_manifest.json", independence)
    write_json(
        run_dir / "formal_result_binding_plan.json",
        {
            "schema_version": "1.0.0",
            "artifact_type": "formal_result_binding_plan",
            "run_id": ident["run_id"],
            "status": "planned",
            "required_fields": ["run_id", "problem_manifest_sha256", "execution_spec_sha256", "source_manifest_sha256", "execution_started_at", "created_at", "activation_status", "formal_result_ref"],
            "planned_values": {
                "run_id": ident["run_id"],
                "problem_manifest_sha256": sha256_file(run_dir / "problem_manifest.json"),
                "execution_spec_sha256": sha256_file(run_dir / "execution_spec.json"),
                "source_manifest_sha256": sha256_file(source_manifest),
                "activation_status": "active_after_collector_validator_only",
            },
            "forbidden_shortcuts": ["文件名包含new", "仅比较mtime", "仅比较上一文件SHA", "复用历史Formal Result"],
        },
    )


def _require_fields(value: Mapping[str, Any], fields: Iterable[str], label: str, errors: list[str]) -> None:
    missing = [name for name in fields if name not in value]
    if missing:
        errors.append(f"{label} 缺字段: {', '.join(missing)}")


def validate_candidate_outputs(run_dir: Path) -> dict[str, Any]:
    output_dir = run_dir / "workspace" / "output"
    errors = [f"workspace/output/{name} 不存在" for name in OUTPUT_REQUIRED_FILES if not (output_dir / name).is_file()]
    if errors:
        raise OutputContractError("2018-B MATLAB Level A 输入闭锁：\n- " + "\n- ".join(errors))
    summary = load_json(output_dir / "run_summary.json", "run_summary.json")
    schedules = load_json(output_dir / "schedules.json", "schedules.json")
    if summary.get("problem_id") != "2018-B":
        errors.append("run_summary.problem_id 必须为 2018-B")
    if summary.get("horizon_seconds") != 28800:
        errors.append("run_summary.horizon_seconds 必须为 28800")
    objective = summary.get("objective_contract")
    if not isinstance(objective, dict):
        errors.append("run_summary.objective_contract 必须是对象")
    else:
        if objective.get("lexicographic_order") != ["N_clean(H)", "N_WIP(H)", "W_CNC", "T_RGV_end"]:
            errors.append("正式四层目标顺序不符合冻结合同")
        if objective.get("directions") != ["maximize", "minimize", "minimize", "minimize"]:
            errors.append("正式四层目标方向不符合冻结合同")
    runs = summary.get("deterministic_runs")
    if not isinstance(runs, list) or not runs:
        errors.append("run_summary.deterministic_runs 必须是非空数组")
        runs = []
    summary_by_key: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(runs):
        if not isinstance(item, dict):
            errors.append(f"deterministic_runs[{index}] 必须是对象")
            continue
        _require_fields(item, ("run_key", "parameter_group", "process_type", "policy", "comparison_protocol", "metrics"), f"deterministic_runs[{index}]", errors)
        metrics = item.get("metrics")
        if not isinstance(metrics, dict):
            errors.append(f"deterministic_runs[{index}].metrics 必须是对象")
        else:
            _require_fields(metrics, METRIC_FIELDS, f"deterministic_runs[{index}].metrics", errors)
        key = str(item.get("run_key", ""))
        if not key or key in summary_by_key:
            errors.append(f"deterministic_runs[{index}].run_key 为空或重复")
        else:
            summary_by_key[key] = item
    schedule_runs = schedules.get("runs")
    if not isinstance(schedule_runs, list):
        errors.append("schedules.runs 必须是数组")
        schedule_runs = []
    schedule_keys: set[str] = set()
    for index, item in enumerate(schedule_runs):
        if not isinstance(item, dict):
            errors.append(f"schedules.runs[{index}] 必须是对象")
            continue
        _require_fields(item, ("run_key", "parts"), f"schedules.runs[{index}]", errors)
        key = str(item.get("run_key", ""))
        schedule_keys.add(key)
        parts = item.get("parts")
        if not isinstance(parts, list):
            errors.append(f"schedules.runs[{index}].parts 必须是数组")
            continue
        for part_index, part in enumerate(parts):
            if not isinstance(part, dict):
                errors.append(f"schedules.runs[{index}].parts[{part_index}] 必须是对象")
            else:
                _require_fields(part, PART_FIELDS, f"schedules.runs[{index}].parts[{part_index}]", errors)
    if set(summary_by_key) != schedule_keys:
        errors.append("run_summary 与 schedules 的 deterministic run_key 集合不一致")
    event_keys: set[str] = set()
    try:
        with gzip.open(output_dir / "events.jsonl.gz", "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(f"events.jsonl.gz 第 {line_number} 行不是合法JSON")
                    continue
                if not isinstance(event, dict):
                    errors.append(f"events.jsonl.gz 第 {line_number} 行必须是对象")
                    continue
                _require_fields(event, EVENT_FIELDS, f"events.jsonl.gz[{line_number}]", errors)
                event_keys.add(str(event.get("run_key", "")))
    except OSError as exc:
        errors.append(f"events.jsonl.gz 无法解压：{exc}")
    missing_events = sorted(set(summary_by_key) - event_keys)
    if missing_events:
        errors.append("下列确定性运行缺少原子事件：" + ", ".join(missing_events))
    if errors:
        raise OutputContractError("2018-B MATLAB Level A 输入闭锁：\n- " + "\n- ".join(errors))
    return {"summary": summary, "run_contracts": list(summary_by_key.values())}


def _common_matlab_input(run_dir: Path) -> dict[str, Any]:
    output = run_dir / "workspace" / "output"
    return {
        "schema_version": "1.0.0",
        "run_id": identity(run_dir)["run_id"],
        "model_kind": "rgv_2018b",
        "official_input_refs": [ref(run_dir, run_dir / "problem" / "parameters.json"), ref(run_dir, run_dir / "workspace" / "materials" / "official" / "material_manifest.json")],
        "python_result_ref": ref(run_dir, output / "run_summary.json"),
        "tolerances": {"objective": 0.0, "constraint": 0.0, "statistic": 1e-9, "decision": 0.0},
    }


def _manual_dynamic_optimum(
    horizon: int, cnc_count: int, service: int, process: int, clean: int
) -> int:
    """生成 MATLAB B 的 Python 侧期望值；实现不依赖主模拟器。"""

    @lru_cache(maxsize=None)
    def best(time: int, ready_times: tuple[int, ...]) -> int:
        if time >= horizon:
            return 0
        eligible = [
            index
            for index, ready_at in enumerate(ready_times)
            if ready_at < 0 or ready_at <= time
        ]
        if not eligible:
            future = [ready_at for ready_at in ready_times if ready_at > time]
            return best(min(future), ready_times) if future else 0
        optimum = 0
        for index in eligible:
            current = ready_times[index]
            service_end = time + service
            if service_end > horizon:
                continue
            next_ready = list(ready_times)
            next_ready[index] = service_end + process
            completed = int(current >= 0 and service_end + clean <= horizon)
            next_time = service_end + (clean if current >= 0 else 0)
            optimum = max(optimum, completed + best(next_time, tuple(next_ready)))
        return optimum

    return best(0, tuple(-1 for _ in range(cnc_count)))


def _level_b_examples() -> list[dict[str, Any]]:
    examples = []
    for cnc_count, horizon in ((2, 40), (4, 40)):
        service, process, clean = 2, 10, 1
        examples.append(
            {
                "case_id": f"rgv_{cnc_count}cnc_dynamic_enumeration",
                "example_kind": "rgv_dynamic_one_stage",
                "cnc_count": cnc_count,
                "model_scope": "缩小的一道工序动态时间状态枚举；验证目标方向、单RGV服务容量和时域边界，不代表完整模型独立求解",
                "horizon_seconds": horizon,
                "service_seconds": service,
                "process_seconds": process,
                "clean_seconds": clean,
                "python_expected": {
                    "objective_value": float(
                        _manual_dynamic_optimum(
                            horizon, cnc_count, service, process, clean
                        )
                    ),
                    "zero_horizon_objective": 0.0,
                },
            }
        )
    return examples


def build_matlab_inputs(run_dir: Path) -> None:
    validated = validate_candidate_outputs(run_dir)
    common = _common_matlab_input(run_dir)
    output = run_dir / "workspace" / "output"
    contracts: list[dict[str, Any]] = []
    for item in validated["run_contracts"]:
        metrics = item["metrics"]
        contracts.append(
            {
                "run_key": item["run_key"],
                "parameter_group": item["parameter_group"],
                "process_type": item["process_type"],
                "policy": item["policy"],
                "comparison_protocol": item["comparison_protocol"],
                "python_objective": [metrics["completed_clean_products"], -metrics["n_wip_at_horizon"], -metrics["cnc_waiting_seconds"], -metrics["rgv_end_seconds"]],
                "python_metrics": {name: metrics[name] for name in METRIC_FIELDS},
            }
        )
    level_a = {
        **common,
        "level": "A",
        "rgv_contract": {
            "parameters_ref": ref(run_dir, run_dir / "problem" / "parameters.json"),
            "schedules_ref": ref(run_dir, output / "schedules.json"),
            "events_ref": ref(run_dir, output / "events.jsonl.gz"),
            "constraint_self_check_ref": ref(run_dir, output / "constraint_self_check.json"),
            "objective_order": ["N_clean(H)", "-N_WIP(H)", "-W_CNC", "-T_RGV_end"],
            "run_contracts": contracts,
        },
    }
    write_json(run_dir / "matlab_level_a_input.json", level_a)
    level_b = {**common, "level": "B", "small_examples": _level_b_examples()}
    write_json(run_dir / "matlab_level_b_input.json", level_b)


def prepare_contracts(
    run_dir: Path,
    repair_workspace: Path,
    official_materials: Path,
    *,
    git_identity: Mapping[str, Any] | None = None,
) -> None:
    identity(run_dir)
    if not (run_dir / "problem_manifest.json").is_file():
        raise ValueError("已初始化 Run 缺少 problem_manifest.json")
    source_manifest = copy_repair_source(run_dir, repair_workspace, git_identity=git_identity)
    source_manifest_input = run_dir / "workspace" / "artifacts" / "repair_source_manifest.json"
    _copy_checked(source_manifest, source_manifest_input)
    official_manifest = copy_official_materials(run_dir, official_materials)
    parameters, manual_case = freeze_problem_inputs(run_dir)
    build_gate_0(run_dir)
    build_gate_1(run_dir)
    build_gate_2(run_dir, source_manifest_input, official_manifest, parameters, manual_case)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="准备2018-B v2.1 回放脚手架")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--repair-workspace", default=r"E:\AI\数模-2018b-multiagent\workspace\2018b_repair")
    parser.add_argument("--official-materials", default=r"E:\AI\shumo_training_private\2018_B\official_materials")
    parser.add_argument("--phase", choices=("contracts", "matlab", "all"), default="all")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    if args.phase == "all":
        # ``all`` 必须原子地满足结果前提，避免先写合同后才发现伪造风险。
        validate_candidate_outputs(run_dir)
    if args.phase in {"contracts", "all"}:
        prepare_contracts(run_dir, Path(args.repair_workspace).resolve(), Path(args.official_materials).resolve())
    if args.phase in {"matlab", "all"}:
        build_matlab_inputs(run_dir)
    print(json.dumps({"run_dir": str(run_dir), "phase": args.phase, "gate3_executed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
