from __future__ import annotations

import argparse
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

    pack_content = build_pack(args.profile, include_candidates=args.include_candidate_patches)
    pack_manifest = build_manifest(args.profile, pack_content, args.include_candidate_patches)
    (run_dir / "runtime_pack.md").write_bytes(pack_content.encode("utf-8"))
    write_json(run_dir / "runtime_pack.manifest.json", pack_manifest)

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
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
            "materials": material_path.as_posix(),
            "material_status": "ready" if material_exists else "blocked_missing",
            "include_candidate_patches": args.include_candidate_patches,
            "status": "initialized" if material_exists else "blocked",
            "automatic_stable_update": False,
        },
    )
    write_json(
        run_dir / "material_review.json",
        {
            "material_path": material_path.as_posix(),
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
        f"- 材料：`{material_path.as_posix()}`\n"
        f"- 状态：{'材料就绪' if material_exists else '材料缺失，阻塞'}\n\n"
        "## 执行顺序\n\n"
        "1. 人工确认 `material_review.json` 的 T0-T4 与 M1-M5。\n"
        "2. 读取 `runtime_pack.md`，只执行指定 Gate。\n"
        "3. 将诊断写入 `diagnosis.md`。\n"
        "4. 填写 `score.json` 与 `failure_labels.json`。\n"
        "5. 只把升级建议写入 `patch_suggestions.md`，不得自动修改 stable 状态。\n",
        encoding="utf-8",
    )
    (run_dir / "diagnosis.md").write_text("# 总控诊断\n\n待执行。\n", encoding="utf-8")
    write_json(run_dir / "score.json", {"total": None, "items": {}, "passed": None})
    write_json(run_dir / "failure_labels.json", {"labels": [], "evidence": {}, "reviewed": False})
    (run_dir / "patch_suggestions.md").write_text("# Patch 建议\n\n待复盘后填写；不得自动升级状态。\n", encoding="utf-8")
    return run_dir, material_exists


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化可追溯的数学建模工作流运行目录。")
    parser.add_argument("--workflow", required=True, choices=["old_problem"])
    parser.add_argument("--problem", required=True, help="旧题编号，例如 2024-C。")
    parser.add_argument("--profile", default="engineering_optimization")
    parser.add_argument("--gates", default="0-2", choices=["0-2", "0-5"])
    parser.add_argument("--materials", help="题面/附件目录；默认从 official_materials/<题号> 推导。")
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id", help="显式运行 ID，便于自动化测试或重跑隔离。")
    parser.add_argument("--include-candidate-patches", action="store_true")
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
