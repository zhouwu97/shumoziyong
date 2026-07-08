from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PROFILE_FILES = {
    "general": [
        "export/mathmodelagent_inject_prompt.md",
        "prompt_base/prompt_base_v1.0.md",
        "runtime_profiles/general_runtime.md",
        "checklists/gate_0_problem_diagnosis.md",
        "checklists/gate_1_before_modeling.md",
        "checklists/gate_2_before_coding.md",
        "checklists/gate_3_before_writing.md",
        "checklists/gate_4_final_review.md",
    ],
    "engineering_optimization": [
        "export/mathmodelagent_inject_prompt.md",
        "prompt_base/prompt_base_v1.0.md",
        "runtime_profiles/engineering_optimization_runtime.md",
        "prompt_plugins/plugin_optimization_v1.md",
        "prompt_patches/patch_A092_engineering_optimization.md",
        "prompt_patches/patch_A127_engineering_layout_optimization.md",
        "checklists/gate_0_problem_diagnosis.md",
        "checklists/gate_1_before_modeling.md",
        "checklists/gate_2_before_coding.md",
        "checklists/gate_3_before_writing.md",
        "checklists/gate_4_final_review.md",
    ],
    "evaluation": [
        "export/mathmodelagent_inject_prompt.md",
        "prompt_base/prompt_base_v1.0.md",
        "runtime_profiles/evaluation_runtime.md",
        "checklists/gate_0_problem_diagnosis.md",
        "checklists/gate_1_before_modeling.md",
        "checklists/gate_2_before_coding.md",
        "checklists/gate_3_before_writing.md",
        "checklists/gate_4_final_review.md",
    ],
    "prediction": [
        "export/mathmodelagent_inject_prompt.md",
        "prompt_base/prompt_base_v1.0.md",
        "runtime_profiles/prediction_runtime.md",
        "checklists/gate_0_problem_diagnosis.md",
        "checklists/gate_1_before_modeling.md",
        "checklists/gate_2_before_coding.md",
        "checklists/gate_3_before_writing.md",
        "checklists/gate_4_final_review.md",
    ],
}


def read_rule(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists():
        return f"\n\n<!-- 缺失文件：{relative_path} -->\n\n"
    return path.read_text(encoding="utf-8")


def build_pack(profile: str) -> str:
    if profile not in PROFILE_FILES:
        available = ", ".join(sorted(PROFILE_FILES))
        raise ValueError(f"未知 profile：{profile}。可选项：{available}")

    parts = [
        "# 数模比赛运行规则包\n\n",
        f"- profile：`{profile}`\n",
        "- 用途：复制到比赛工作目录的 `rules/runtime_pack.md`，供 MathModelAgent 执行前读取。\n",
        "- 原则：先诊断，后建模；先确认路线，后代码；先验证结果，后论文。\n\n",
    ]

    for relative_path in PROFILE_FILES[profile]:
        parts.append(f"\n\n# ===== {relative_path} =====\n\n")
        parts.append(read_rule(relative_path))

    return "".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出 MathModelAgent 可读取的比赛运行规则包。")
    parser.add_argument(
        "--profile",
        default="engineering_optimization",
        choices=sorted(PROFILE_FILES),
        help="选择要导出的运行配置，默认导出工程优化规则包。",
    )
    parser.add_argument(
        "--output",
        default="export/cumcm_runtime_pack.md",
        help="输出文件路径，默认写入 export/cumcm_runtime_pack.md。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_pack(args.profile), encoding="utf-8")
    print(f"已导出：{output}")


if __name__ == "__main__":
    main()
