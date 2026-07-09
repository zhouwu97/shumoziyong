from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTO_PATCHES_MARKER = "__AUTO_PATCHES__"
DEFAULT_PATCH_STATUSES = {"verified_candidate", "stable"}
CANDIDATE_PATCH_STATUSES = DEFAULT_PATCH_STATUSES | {"candidate"}

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
        AUTO_PATCHES_MARKER,
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


def read_patch_index() -> list[dict]:
    path = ROOT / "prompt_patches/patch_index.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("prompt_patches/patch_index.json 必须是 JSON 数组。")
    return data


def select_patch_files(profile: str, include_candidates: bool = False) -> list[str]:
    allowed_statuses = CANDIDATE_PATCH_STATUSES if include_candidates else DEFAULT_PATCH_STATUSES
    selected: list[dict] = []

    for patch in read_patch_index():
        runtime_profiles = patch.get("runtime_profiles", [])
        status = patch.get("status", "")
        file = patch.get("file", "")
        if profile in runtime_profiles and status in allowed_statuses and file:
            selected.append(patch)

    selected.sort(key=lambda item: (item.get("priority", 999), item.get("patch_id", "")))
    return [item["file"] for item in selected]


def render_auto_patches(profile: str, include_candidates: bool = False) -> str:
    patch_files = select_patch_files(profile, include_candidates=include_candidates)
    if not patch_files:
        return "\n\n<!-- patch_index 未选中任何 patch。 -->\n\n"

    parts = [
        "\n\n# ===== prompt_patches/patch_index.json 自动选择 =====\n\n",
        "- 默认只导入 `verified_candidate` 和 `stable` patch。\n",
    ]
    if include_candidates:
        parts.append("- 本次导出已显式包含 `candidate` patch，仅适合测试，不建议直接比赛使用。\n")
    parts.append("\n")

    for relative_path in patch_files:
        parts.append(f"\n\n# ===== {relative_path} =====\n\n")
        parts.append(read_rule(relative_path))
    return "".join(parts)


def build_pack(profile: str, include_candidates: bool = False) -> str:
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
        if relative_path == AUTO_PATCHES_MARKER:
            parts.append(render_auto_patches(profile, include_candidates=include_candidates))
            continue
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
    parser.add_argument(
        "--include-candidate-patches",
        action="store_true",
        help="测试用：额外导入 candidate patch。默认只导入 verified_candidate/stable。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_pack(args.profile, include_candidates=args.include_candidate_patches),
        encoding="utf-8",
    )
    print(f"已导出：{output}")


if __name__ == "__main__":
    main()
