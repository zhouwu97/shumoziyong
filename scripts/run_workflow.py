from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from export_runtime_pack import build_manifest, build_pack
from verify_materials import MaterialVerificationResult, verify_materials


ROOT = Path(__file__).resolve().parents[1]


def normalize_problem_dir(problem: str) -> str:
    """将题号规范为 official_materials 下使用的目录名。"""
    return re.sub(r"[^A-Za-z0-9]+", "_", problem).strip("_")


def write_json(path: Path, data: object) -> None:
    """以 UTF-8 和稳定缩进写入 JSON。"""
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def sha256_bytes(content: bytes) -> str:
    """计算内容哈希。"""
    return hashlib.sha256(content).hexdigest()


EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("run_manifest.json", "run_manifest", "application/json"),
    ("request.json", "request", "application/json"),
    ("response.json", "model_response", "application/json"),
    ("runtime_pack.md", "runtime_pack", "text/markdown"),
    ("runtime_pack.manifest.json", "runtime_pack_manifest", "application/json"),
    ("problem_manifest.json", "problem_manifest", "application/json"),
    ("automatic_evaluation.json", "automatic_evaluation", "application/json"),
    ("ai_run_metadata.json", "ai_run_metadata", "application/json"),
    ("human_review.md", "human_review", "text/markdown"),
)


def build_run_evidence_manifest(
    run_dir: Path,
    run_id: str,
    content_overrides: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """为运行目录中的晋级证据生成可验证的路径、大小和内容哈希清单。"""
    artifacts: list[dict[str, Any]] = []
    for filename, role, media_type in EVIDENCE_ARTIFACT_SPECS:
        path = run_dir / filename
        if content_overrides and filename in content_overrides:
            content = content_overrides[filename]
        else:
            content = path.read_bytes()
        artifacts.append(
            {
                "path": filename,
                "sha256": sha256_bytes(content),
                "media_type": media_type,
                "size_bytes": len(content),
                "role": role,
            }
        )
    return {
        "evidence_manifest_version": "1.0.0",
        "run_id": run_id,
        "artifacts": artifacts,
    }


def repo_relative(path: Path) -> str:
    """优先记录仓库相对路径；外部材料目录保留绝对路径以确保可追溯。"""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_problem_manifest(
    problem_id: str,
    material_path: Path,
    verification: MaterialVerificationResult,
) -> dict[str, Any]:
    """从材料校验结果生成运行固定的题目快照。

    只记录机器清单中明确声明且哈希校验通过的文件；不再递归扫描目录并把“目录存在”误判为材料就绪。
    """
    files: list[dict[str, Any]] = []
    for item in verification.files:
        relative_file = item["path"]
        resolved = material_path / relative_file
        files.append(
            {
                "category": item["category"],
                "path": repo_relative(resolved),
                "size": item["size"],
                "sha256": item["sha256"],
            }
        )
    files.sort(key=lambda item: (item["category"], item["path"]))

    digest_input = "".join(
        f"{item['category']}:{item['path']}:{item['size']}:{item['sha256']}" for item in files
    )
    content_digest = sha256_bytes(digest_input.encode("utf-8")) if files else None
    return {
        "problem_id": problem_id,
        "material_root": repo_relative(material_path),
        "material_manifest": repo_relative(verification.manifest_path),
        "material_manifest_sha256": verification.manifest_sha256,
        "material_exists": material_path.is_dir(),
        "material_status": verification.status,
        "categories": {
            name: category.to_dict() for name, category in verification.categories.items()
        },
        "files": files,
        "content_digest": content_digest,
        "errors": verification.errors,
    }


def _experiment_kind(candidate_patches: list[str], excluded_patches: list[str]) -> str:
    if excluded_patches and not candidate_patches:
        return "isolation"
    if candidate_patches:
        return "candidate_experiment"
    return "standard"


def create_old_problem_run(args: argparse.Namespace) -> tuple[Path, bool]:
    """初始化旧题运行目录，并在 Gate 0 前强制校验材料完整性。"""
    if getattr(args, "material_file", []):
        raise ValueError("不再支持 --material-file：旧题运行必须校验完整材料清单，不能用子集绕过附件或模板检查")

    run_id = args.run_id or f"{date.today().isoformat()}_{normalize_problem_dir(args.problem)}_gate{args.gates}"
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"运行目录已存在：{run_dir}")
    run_dir.mkdir(parents=True)

    material_path = (
        Path(args.materials)
        if args.materials
        else ROOT / "official_materials" / normalize_problem_dir(args.problem)
    )
    if not material_path.is_absolute():
        material_path = ROOT / material_path
    material_path = material_path.resolve()
    material_verification = verify_materials(
        material_path,
        expected_problem_id=args.problem,
    )

    profile_state_path = ROOT / "runtime_profiles" / f"{args.profile}.json"
    if not profile_state_path.is_file():
        raise FileNotFoundError(f"runtime profile 状态不存在：{profile_state_path}")
    profile_state = json.loads(profile_state_path.read_text(encoding="utf-8"))

    # 隔离实验：--exclude-patch / --candidate-patch 透传给导出器。
    pack_content = build_pack(args.profile, args.candidate_patch, args.exclude_patch)
    pack_manifest = build_manifest(args.profile, pack_content, args.candidate_patch, args.exclude_patch)
    (run_dir / "runtime_pack.md").write_bytes(pack_content.encode("utf-8"))
    write_json(run_dir / "runtime_pack.manifest.json", pack_manifest)

    problem_manifest = build_problem_manifest(args.problem, material_path, material_verification)
    write_json(run_dir / "problem_manifest.json", problem_manifest)

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    status = "initialized" if material_verification.ready else "blocked"
    manifest_data: dict[str, Any] = {
        "run_id": run_id,
        "workflow": "old_problem",
        "created_at": created_at,
        "problem_id": args.problem,
        "profile": args.profile,
        "runtime_version": profile_state["version"],
        "gates": args.gates,
        "materials": repo_relative(material_path),
        "material_manifest": repo_relative(material_verification.manifest_path),
        "material_manifest_sha256": material_verification.manifest_sha256,
        "material_status": material_verification.status,
        "material_error_count": len(material_verification.errors)
        + sum(len(category.errors) for category in material_verification.categories.values()),
        "candidate_patches": args.candidate_patch,
        "excluded_patches": args.exclude_patch,
        "experiment_kind": _experiment_kind(args.candidate_patch, args.exclude_patch),
        "status": status,
        "automatic_stable_update": False,
    }

    if getattr(args, "promotion_evidence", False):
        if not getattr(args, "experiment_group_id", None):
            raise ValueError("--promotion-evidence 必须提供 --experiment-group-id")
        if not getattr(args, "experiment_role", None):
            raise ValueError("--promotion-evidence 必须提供 --experiment-role")
        if not getattr(args, "target_patch", None):
            raise ValueError("--promotion-evidence 必须提供 --target-patch")

        manifest_data["experiment_kind"] = "negative_control"
        manifest_data["experiment_group_id"] = args.experiment_group_id
        manifest_data["experiment_role"] = args.experiment_role
        manifest_data["target_patch"] = args.target_patch
        manifest_data["evidence_validity"] = "pending"
        manifest_data["eligible_for_promotion"] = False

        target = args.target_patch
        excluded = args.exclude_patch
        if args.experiment_role == "baseline":
            if target not in excluded:
                raise ValueError("baseline 必须在 excluded_patches 中排除 target_patch")
        elif args.experiment_role == "patch_only" and target in excluded:
            raise ValueError("patch_only 不能排除 target_patch")

    write_json(run_dir / "run_manifest.json", manifest_data)
    material_report = material_verification.to_dict()
    material_report["material_path"] = repo_relative(material_path)
    material_report["manual_review_required"] = True
    material_report["material_level"] = None
    material_report["risk_labels"] = []
    write_json(run_dir / "material_review.json", material_report)

    material_status_text = "材料校验通过" if material_verification.ready else "材料校验失败，已阻塞"
    (run_dir / "execution_plan.md").write_text(
        f"# 旧题闭环执行计划\n\n"
        f"- 题目：`{args.problem}`\n"
        f"- profile：`{args.profile}`（{profile_state['version']} / {profile_state['maturity']}）\n"
        f"- 闸门范围：Gate {args.gates}\n"
        f"- 材料：`{repo_relative(material_path)}`\n"
        f"- 材料清单：`{repo_relative(material_verification.manifest_path)}`\n"
        f"- candidate patch：{args.candidate_patch or '无'}\n"
        f"- 排除 patch：{args.exclude_patch or '无'}\n"
        f"- 实验类型：{_experiment_kind(args.candidate_patch, args.exclude_patch)}\n"
        f"- 状态：{material_status_text}\n\n"
        "## Gate 0-5 定义\n\n"
        "- Gate 0：题目与材料诊断\n"
        "- Gate 1：模型路线\n"
        "- Gate 2：代码计划\n"
        "- Gate 3：结果确认\n"
        "- Gate 4：论文确认\n"
        "- Gate 5：最终验收\n\n"
        "## 执行顺序\n\n"
        "1. 先检查 `material_review.json`：只有 `status=ready` 才能进入 Gate 0。\n"
        "2. 人工确认材料等级 T0-T4 与风险 M1-M5。\n"
        "3. 读取 `runtime_pack.md`，只执行指定 Gate。\n"
        "4. 把发送给 AI 的提示词存入 `request.json`。\n"
        "5. 将诊断写入 `diagnosis.md`（人看）与 `diagnosis.json`（机器检查，符合 `schemas/diagnosis.schema.json`）。\n"
        "6. 把 AI 原始输出存入 `response.md` 和 `response.json`。\n"
        "7. 运行 `evaluate_prompt_response.py` 生成 `automatic_evaluation.json`。\n"
        "8. 人工填写 `human_review.md`、`score.json` 与 `failure_labels.json`。\n"
        "9. 只把升级建议写入 `patch_suggestions.md`，不得自动修改 patch 状态。\n",
        encoding="utf-8",
    )
    (run_dir / "diagnosis.md").write_text("# Gate 0：题目与材料诊断\n\n待执行。\n", encoding="utf-8")
    write_json(
        run_dir / "diagnosis.json",
        {"stage": "diagnosis", "_note": "待执行；完成后须符合 schemas/diagnosis.schema.json"},
    )
    write_json(run_dir / "score.json", {"total": None, "items": {}, "passed": None})
    write_json(run_dir / "failure_labels.json", {"labels": [], "evidence": {}, "reviewed": False})
    (run_dir / "patch_suggestions.md").write_text(
        "# Patch 建议\n\n待复盘后填写；不得自动升级状态。\n", encoding="utf-8"
    )
    # 证据文件脚手架：由 AI 运行和人工审核填充。
    write_json(
        run_dir / "request.json",
        {
            "_note": "待填写：发送给 AI 的提示词",
            "prompt": "",
            "model": "",
            "runtime_version": profile_state["version"],
            "source": "pending",
            "response_reference": None,
        },
    )
    (run_dir / "response.md").write_text("# AI 输出（Markdown）\n\n待填写。\n", encoding="utf-8")
    write_json(
        run_dir / "response.json",
        {"_note": "待填写：AI 结构化 JSON 输出，须符合 diagnosis.schema.json"},
    )
    write_json(
        run_dir / "automatic_evaluation.json",
        {"_note": "待生成：由 evaluate_prompt_response.py 产出", "case_id": "", "errors": []},
    )
    (run_dir / "human_review.md").write_text(
        "# 人工审核\n\n待填写。至少写明：\n"
        "- 是否出现 patch 特有机制\n"
        "- 是否改变正确题型\n"
        "- 是否相比 baseline 发生跑偏\n"
        "- 最终判定 pass/fail\n"
        "- 判断理由\n",
        encoding="utf-8",
    )
    # AI 运行元数据脚手架：状态 pending，不含伪造时间戳或模型名
    write_json(
        run_dir / "ai_run_metadata.json",
        {
            "metadata_version": "1.0.0",
            "status": "pending",
            "note": "待填写真实运行数据；pending 元数据不能作为晋级证据。",
            "provider": None,
            "model": None,
            "model_snapshot": None,
            "client": None,
            "client_version": None,
            "reasoning_effort": None,
            "temperature": None,
            "seed": None,
            "started_at": None,
            "completed_at": None,
            "prompt_sha256": None,
            "runtime_pack_sha256": None,
            "problem_material_digest": None,
            "tool_permissions": None,
            "working_directory_mode": None,
        },
    )
    write_json(
        run_dir / "run_evidence_manifest.json",
        build_run_evidence_manifest(run_dir, run_id),
    )
    # 闸门转换日志：记录每次阶段推进
    _init_transitions(run_dir, args.gates, material_verification.ready)
    return run_dir, material_verification.ready


GATE_NAMES: dict[int, str] = {
    0: "题目与材料诊断",
    1: "模型路线",
    2: "代码计划",
    3: "结果确认",
    4: "论文确认",
    5: "最终验收",
}

VALID_TRANSITIONS: dict[int, set[int | None]] = {
    # from_gate -> {valid to_gate}；None 表示只允许从初始状态进入
    None: {0},       # 只能从 initialized 进入 Gate 0
    0: {1},          # Gate 0 → Gate 1
    1: {2},          # Gate 1 → Gate 2
    2: {3},          # Gate 2 → Gate 3
    3: {4},          # Gate 3 → Gate 4
    4: {5},          # Gate 4 → Gate 5
    5: set(),        # Gate 5 是终点
}


def _init_transitions(run_dir: Path, gate_range: str, material_ready: bool) -> None:
    """初始化 transitions.jsonl 并记录 initialized 状态。"""
    max_gate = int(gate_range.split("-")[1])
    lines: list[str] = []
    lines.append(
        json.dumps(
            {
                "from": None,
                "to": None,
                "state": "initialized",
                "material_ready": material_ready,
                "max_gate": max_gate,
                "note": "运行目录已创建；材料校验通过后才允许进入 Gate 0",
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    (run_dir / "transitions.jsonl").write_text("".join(lines), encoding="utf-8")


def record_transition(run_dir: Path, from_gate: int | None, to_gate: int, reviewer: str, decision: str) -> None:
    """记录一次闸门推进事件。

    与 v1 不同，v2 不再信任调用方传入的 from_gate：
    - 必须从 transitions.jsonl 读取真实的当前 Gate。
    - from_gate 仅用于调用方自检（如传入错误值会触发 ValueError）。
    - material_ready=false 时禁止进入任何 Gate。
    - 不能超过初始化时声明的 max_gate。
    - transitions.jsonl 必须已初始化。

    Args:
        run_dir: 运行目录。
        from_gate: 调用方认为的当前 Gate（首次为 None）。必须与真实当前 Gate 一致。
        to_gate: 将要进入的 Gate。
        reviewer: 审核人标识（human 或 automated）。
        decision: approved / rejected。

    Raises:
        ValueError: 如果转换不合法（伪造跳跃、回退、材料未就绪、超出 max_gate）。
        FileNotFoundError: 如果 transitions.jsonl 未初始化。
    """
    if to_gate not in GATE_NAMES:
        raise ValueError(f"未知 Gate：{to_gate}（允许 0-5）")

    transitions_path = run_dir / "transitions.jsonl"
    if not transitions_path.is_file():
        raise FileNotFoundError(f"缺少 transitions.jsonl：{transitions_path}（请先通过 _init_transitions 初始化）")

    # 读取初始化和当前状态
    init_data: dict[str, Any] = {}
    real_current: int | None = None
    for line in transitions_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("state") == "initialized":
            init_data = entry
        to_g = entry.get("to")
        if to_g is not None and entry.get("decision") == "approved":
            real_current = to_g

    # 1) 材料未就绪时禁止进入任何 Gate
    if init_data.get("material_ready") is not True:
        raise ValueError(
            f"材料校验未通过（material_ready={init_data.get('material_ready')}），"
            "禁止进入任何 Gate。请先修复材料问题。"
        )

    # 2) 不能超过 max_gate
    max_gate = init_data.get("max_gate", 5)
    if to_gate > max_gate:
        raise ValueError(
            f"不能进入 Gate {to_gate}，初始化声明的最大 Gate 为 {max_gate}。"
        )

    # 3) 验证调用方传入的 from_gate 与真实当前 Gate 一致
    if from_gate != real_current:
        raise ValueError(
            f"from_gate 不匹配：调用方声称当前为 {from_gate}，"
            f"但 transitions.jsonl 记录的实际当前 Gate 为 {real_current}。"
            "禁止伪造跳跃。"
        )

    # 4) 验证转换合法性
    valid_next = VALID_TRANSITIONS.get(real_current, set())
    if to_gate not in valid_next:
        expected = f"{{{', '.join(str(g) for g in sorted(valid_next))}}}" if valid_next else "（终点）"
        raise ValueError(
            f"Gate 转换非法：不能从 {real_current} 进入 Gate {to_gate}。"
            f"允许的下一 Gate：{expected}。"
        )

    if decision not in ("approved", "rejected"):
        raise ValueError(f"decision 必须为 approved 或 rejected，实际为 {decision!r}")

    entry = {
        "from": real_current,
        "to": to_gate,
        "state": f"entering_gate_{to_gate}" if decision == "approved" else f"rejected_gate_{to_gate}",
        "gate_name": GATE_NAMES[to_gate],
        "reviewer": reviewer,
        "decision": decision,
    }
    with open(transitions_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def is_gate_complete(run_dir: Path, gate: int) -> bool:
    """检查指定 Gate 是否已完成并通过。

    Gate 5 完成后（进入 completed 状态）视为 Gate 5 完成。
    """
    transitions_path = run_dir / "transitions.jsonl"
    if not transitions_path.is_file():
        return False
    current: int | None = None
    completed = False
    for line in transitions_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("state") == "completed":
            completed = True
            break
        to_g = entry.get("to")
        if to_g is not None and entry.get("decision") == "approved":
            current = to_g
    if completed:
        return gate <= 5
    if current is not None and current > gate:
        return True
    return False


def get_current_gate(run_dir: Path) -> int | None:
    """从 transitions.jsonl 读取当前所在 Gate。"""
    transitions_path = run_dir / "transitions.jsonl"
    if not transitions_path.is_file():
        return None
    current: int | None = None
    for line in transitions_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("state") == "completed":
            return None  # 已完成运行，没有"当前"Gate
        to_gate = entry.get("to")
        if to_gate is not None and entry.get("decision") == "approved":
            current = to_gate
    return current


def mark_run_completed(run_dir: Path, reviewer: str) -> None:
    """将运行标记为 completed 终态（Gate 5 通过后调用）。"""
    transitions_path = run_dir / "transitions.jsonl"
    if not transitions_path.is_file():
        raise FileNotFoundError(f"缺少 transitions.jsonl：{transitions_path}")
    
    init_data = {}
    current = None
    completed = False
    for line in transitions_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("state") == "initialized":
            init_data = entry
        elif entry.get("state") == "completed":
            completed = True
        elif entry.get("to") is not None and entry.get("decision") == "approved":
            current = entry.get("to")
            
    if completed:
        raise ValueError("运行已标记为 completed，不能重复标记。")
        
    max_gate = init_data.get("max_gate", 5)
    if max_gate < 5:
        raise ValueError(f"最大 Gate 为 {max_gate}，0-4 的运行不得被标记为 completed。")
        
    if current != 5:
        raise ValueError(f"当前不在 Gate 5（当前 Gate：{current}），无法完成运行。")
        
    gate_5_review = run_dir / "gate_5_review.json"
    if not gate_5_review.is_file():
        raise FileNotFoundError(f"缺少 Gate 5 人工审核记录：{gate_5_review}")

    entry = {
        "from": 5,
        "to": None,
        "state": "completed",
        "reviewer": reviewer,
        "note": "Gate 5 通过，运行完成。",
    }
    with open(transitions_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化可追溯的数学建模工作流运行目录。")
    parser.add_argument("--workflow", required=True, choices=["old_problem"])
    parser.add_argument("--problem", required=True, help="旧题编号，例如 2024-C。")
    parser.add_argument("--profile", default="engineering_optimization")
    parser.add_argument("--gates", default="0-2", choices=["0-2", "0-5"])
    parser.add_argument("--materials", help="题面/附件根目录；默认从 official_materials/<题号> 推导。")
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id", help="显式运行 ID，便于自动化测试或重跑隔离。")
    parser.add_argument(
        "--candidate-patch",
        action="append",
        default=[],
        metavar="PATCH_ID",
        dest="candidate_patch",
        help="显式加入指定 candidate patch，可重复传入。",
    )
    parser.add_argument(
        "--exclude-patch",
        action="append",
        default=[],
        help="要排除的 patch_id（可多次指定）。",
    )
    parser.add_argument("--promotion-evidence", action="store_true", help="启用晋级评估模式。")
    parser.add_argument("--experiment-group-id", help="实验组 ID。")
    parser.add_argument("--experiment-role", choices=["baseline", "patch_only"], help="实验角色。")
    parser.add_argument("--target-patch", help="目标 Patch ID。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir, material_ready = create_old_problem_run(args)
    print(f"已创建运行目录：{run_dir}")
    if not material_ready:
        print("[BLOCKED] 题面、附件、模板或 SHA-256 校验未通过；详见 material_review.json。")
        raise SystemExit(2)
    print("[READY] 题面、附件、模板和 SHA-256 校验通过；请完成人工材料等级与风险确认。")


if __name__ == "__main__":
    main()
