from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from export_runtime_pack import build_manifest, build_pack


ROOT = Path(__file__).resolve().parents[1]


def normalize_problem_dir(problem: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", problem).strip("_")


def write_json(path: Path, data: object) -> None:
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def repo_relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_problem_manifest(problem_id: str, material_path: Path, material_files: list[str]) -> dict:
    """记录题面与附件的相对路径、文件大小和 SHA-256，计算 content_digest。"""
    files: list[dict[str, object]] = []
    
    if material_path.is_dir():
        if material_files:
            for mf in material_files:
                p = (material_path / mf).resolve()
                if not p.is_relative_to(material_path.resolve()):
                    raise ValueError(f"指定的文件 {mf} 逃逸了材料根目录 {material_path}")
                if p.is_file():
                    content = p.read_bytes()
                    files.append({
                        "path": repo_relative(p),
                        "size": len(content),
                        "sha256": sha256_bytes(content),
                    })
        else:
            for p in sorted(material_path.rglob("*")):
                if p.is_file():
                    content = p.read_bytes()
                    files.append({
                        "path": repo_relative(p),
                        "size": len(content),
                        "sha256": sha256_bytes(content),
                    })
    
    # Sort files by path for stable digest
    files.sort(key=lambda x: x["path"])
    
    digest_input = "".join(f"{f['path']}:{f['size']}:{f['sha256']}" for f in files)
    content_digest = sha256_bytes(digest_input.encode("utf-8")) if files else None

    return {
        "problem_id": problem_id,
        "material_root": repo_relative(material_path),
        "material_exists": material_path.is_dir(),
        "files": files,
        "content_digest": content_digest
    }


def create_old_problem_run(args: argparse.Namespace) -> tuple[Path, bool]:
    run_id = args.run_id or f"{date.today().isoformat()}_{normalize_problem_dir(args.problem)}_gate{args.gates}"
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"运行目录已存在：{run_dir}")
    run_dir.mkdir(parents=True)

    material_path = Path(args.materials) if args.materials else ROOT / "official_materials" / normalize_problem_dir(args.problem)
    if not material_path.is_absolute():
        material_path = ROOT / material_path
    material_exists = material_path.exists()

    profile_state_path = ROOT / "runtime_profiles" / f"{args.profile}.json"
    if not profile_state_path.is_file():
        raise FileNotFoundError(f"runtime profile 状态不存在：{profile_state_path}")
    profile_state = json.loads(profile_state_path.read_text(encoding="utf-8"))

    # 隔离实验：--exclude-patch / --candidate-patch 透传给导出器
    pack_content = build_pack(args.profile, args.candidate_patch, args.exclude_patch)
    pack_manifest = build_manifest(args.profile, pack_content, args.candidate_patch, args.exclude_patch)
    (run_dir / "runtime_pack.md").write_bytes(pack_content.encode("utf-8"))
    write_json(run_dir / "runtime_pack.manifest.json", pack_manifest)

    problem_manifest = build_problem_manifest(args.problem, material_path, args.material_file)
    write_json(run_dir / "problem_manifest.json", problem_manifest)

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    status = "initialized" if material_exists else "blocked"
    write_json(
        run_dir / "run_manifest.json",
        {
            "run_id": run_id,
            "workflow": "old_problem",
            "created_at": created_at,
            "problem_id": args.problem,
            "profile": args.profile,
            "runtime_version": profile_state["version"],
            "gates": args.gates,
            "materials": repo_relative(material_path),
            "material_status": "ready" if material_exists else "blocked_missing",
            "candidate_patches": args.candidate_patch,
            "excluded_patches": args.exclude_patch,
            "experiment_kind": _experiment_kind(args.candidate_patch, args.exclude_patch),
            "status": status,
            "automatic_stable_update": False,
        },
    )
    write_json(
        run_dir / "material_review.json",
        {
            "material_path": repo_relative(material_path),
            "exists": material_exists,
            "material_level": None,
            "risk_labels": [],
            "manual_review_required": True,
        },
    )
    (run_dir / "execution_plan.md").write_text(
        f"# 旧题闭环执行计划\n\n"
        f"- 题目：`{args.problem}`\n"
        f"- profile：`{args.profile}`（{profile_state['version']} / {profile_state['maturity']}）\n"
        f"- 闸门范围：Gate {args.gates}\n"
        f"- 材料：`{repo_relative(material_path)}`\n"
        f"- candidate patch：{args.candidate_patch or '无'}\n"
        f"- 排除 patch：{args.exclude_patch or '无'}\n"
        f"- 实验类型：{_experiment_kind(args.candidate_patch, args.exclude_patch)}\n"
        f"- 状态：{'材料就绪' if material_exists else '材料缺失，阻塞'}\n\n"
        "## 执行顺序\n\n"
        "1. 人工确认 `material_review.json` 的 T0-T4 与 M1-M5。\n"
        "2. 读取 `runtime_pack.md`，只执行指定 Gate。\n"
        "3. 把发送给 AI 的提示词存入 `request.json`。\n"
        "4. 将诊断写入 `diagnosis.md`（人看）与 `diagnosis.json`（机器检查，符合 diagnosis_output.schema.json）。\n"
        "5. 把 AI 原始输出存入 `response.md` 和 `response.json`。\n"
        "6. 运行 `evaluate_prompt_response.py` 生成 `automatic_evaluation.json`。\n"
        "7. 人工填写 `human_review.md`。\n"
        "8. 填写 `score.json` 与 `failure_labels.json`。\n"
        "9. 只把升级建议写入 `patch_suggestions.md`，不得自动修改 stable 状态。\n",
        encoding="utf-8",
    )
    (run_dir / "diagnosis.md").write_text("# 总控诊断\n\n待执行。\n", encoding="utf-8")
    write_json(run_dir / "diagnosis.json", {"stage": "diagnosis", "_note": "待执行；完成后须符合 schemas/diagnosis_output.schema.json"})
    write_json(run_dir / "score.json", {"total": None, "items": {}, "passed": None})
    write_json(run_dir / "failure_labels.json", {"labels": [], "evidence": {}, "reviewed": False})
    (run_dir / "patch_suggestions.md").write_text("# Patch 建议\n\n待复盘后填写；不得自动升级状态。\n", encoding="utf-8")
    # 证据文件脚手架：由 AI 运行和人工审核填充
    write_json(run_dir / "request.json", {"_note": "待填写：发送给 AI 的提示词", "prompt": "", "model": "", "runtime_version": profile_state["version"], "source": "real_ai_run", "response_reference": None})
    (run_dir / "response.md").write_text("# AI 输出（Markdown）\n\n待填写。\n", encoding="utf-8")
    write_json(run_dir / "response.json", {"_note": "待填写：AI 结构化 JSON 输出，须符合 diagnosis_output.schema.json"})
    write_json(run_dir / "automatic_evaluation.json", {"_note": "待生成：由 evaluate_prompt_response.py 产出", "case_id": "", "errors": []})
    (run_dir / "human_review.md").write_text(
        "# 人工审核\n\n待填写。至少写明：\n"
        "- 是否出现 patch 特有机制\n"
        "- 是否改变正确题型\n"
        "- 是否相比 baseline 发生跑偏\n"
        "- 最终判定 pass/fail\n"
        "- 判断理由\n",
        encoding="utf-8",
    )
    return run_dir, material_exists


def _experiment_kind(candidate_patches: list[str], excluded_patches: list[str]) -> str:
    if excluded_patches and not candidate_patches:
        return "isolation"
    if candidate_patches:
        return "candidate_experiment"
    return "standard"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化可追溯的数学建模工作流运行目录。")
    parser.add_argument("--workflow", required=True, choices=["old_problem"])
    parser.add_argument("--problem", required=True, help="旧题编号，例如 2024-C。")
    parser.add_argument("--profile", default="engineering_optimization")
    parser.add_argument("--gates", default="0-2", choices=["0-2", "0-5"])
    parser.add_argument("--materials", help="题面/附件根目录；默认从 official_materials/<题号> 推导。")
    parser.add_argument("--material-file", action="append", default=[], help="限定仅打包的材料相对路径。如果指定，必须位于 materials 根目录下。")
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
        metavar="PATCH_ID",
        dest="exclude_patch",
        help="显式排除已批准 patch（隔离实验用），可重复传入。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir, material_exists = create_old_problem_run(args)
    print(f"已创建运行目录：{run_dir}")
    if not material_exists:
        print("[BLOCKED] 未找到题目材料；已生成审查文件，补齐材料后再执行诊断。")
        raise SystemExit(2)
    print("[READY] 材料存在；请先完成人工材料等级与风险确认。")


if __name__ == "__main__":
    main()
