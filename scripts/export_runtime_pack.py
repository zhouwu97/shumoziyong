from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


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


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_text(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"运行包依赖文件不存在：{relative_path}")
    return path.read_text(encoding="utf-8")


def file_record(relative_path: str) -> dict[str, str]:
    content = (ROOT / relative_path).read_bytes()
    return {"path": relative_path, "sha256": sha256_bytes(content)}


def read_patch_index() -> list[dict[str, Any]]:
    path = ROOT / "prompt_patches/patch_index.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("prompt_patches/patch_index.json 必须是 JSON 数组。")
    return data


def select_patches(profile: str, include_candidates: bool = False) -> list[dict[str, Any]]:
    allowed_statuses = CANDIDATE_PATCH_STATUSES if include_candidates else DEFAULT_PATCH_STATUSES
    selected = [
        patch
        for patch in read_patch_index()
        if profile in patch.get("runtime_profiles", [])
        and patch.get("status") in allowed_statuses
        and patch.get("file")
    ]
    selected.sort(key=lambda item: (item.get("priority", 999), item.get("patch_id", "")))
    return selected


def select_patch_files(profile: str, include_candidates: bool = False) -> list[str]:
    return [patch["file"] for patch in select_patches(profile, include_candidates)]


def resolve_pack_files(profile: str, include_candidates: bool = False) -> list[str]:
    if profile not in PROFILE_FILES:
        available = ", ".join(sorted(PROFILE_FILES))
        raise ValueError(f"未知 profile：{profile}。可选项：{available}")

    files: list[str] = []
    for relative_path in PROFILE_FILES[profile]:
        if relative_path == AUTO_PATCHES_MARKER:
            files.extend(select_patch_files(profile, include_candidates))
        else:
            files.append(relative_path)
    return files


def build_pack(profile: str, include_candidates: bool = False) -> str:
    files = resolve_pack_files(profile, include_candidates)
    profile_state = json.loads(read_text(f"runtime_profiles/{profile}.json"))
    parts = [
        "# 数模比赛运行规则包\n\n",
        f"- profile：`{profile}`\n",
        f"- runtime version：`{profile_state['version']}`\n",
        f"- maturity：`{profile_state['maturity']}`\n",
        "- 用途：复制到比赛工作目录的 `rules/runtime_pack.md`，供 MathModelAgent 执行前读取。\n",
        "- 原则：先诊断，后建模；先确认路线，后代码；先验证结果，后论文。\n",
    ]
    if include_candidates:
        parts.append("- 警告：本次显式包含 candidate patch，仅用于测试。\n")
    parts.append("\n")

    for relative_path in files:
        parts.append(f"\n\n# ===== {relative_path} =====\n\n")
        parts.append(read_text(relative_path))
    return "".join(parts)


def build_manifest(
    profile: str,
    pack_content: str,
    include_candidates: bool = False,
) -> dict[str, Any]:
    profile_state_path = f"runtime_profiles/{profile}.json"
    profile_state = json.loads(read_text(profile_state_path))
    selected_patches = select_patches(profile, include_candidates)
    selected_ids = {patch["patch_id"] for patch in selected_patches}
    all_profile_patches = [
        patch for patch in read_patch_index() if profile in patch.get("runtime_profiles", [])
    ]
    files = resolve_pack_files(profile, include_candidates)

    def records(prefix: str) -> list[dict[str, str]]:
        return [file_record(path) for path in files if path.startswith(prefix)]

    base_records = records("prompt_base/")
    return {
        "manifest_version": "1.0.0",
        "runtime_version": profile_state["version"],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "profile": profile,
        "maturity": profile_state["maturity"],
        "runtime_profile_state": file_record(profile_state_path),
        "patch_index": file_record("prompt_patches/patch_index.json"),
        "base": base_records[0] if base_records else None,
        "plugins": records("prompt_plugins/"),
        "patches": [
            {
                "patch_id": patch["patch_id"],
                "status": patch["status"],
                **file_record(patch["file"]),
            }
            for patch in selected_patches
        ],
        "checklists": records("checklists/"),
        "other_files": [
            file_record(path)
            for path in files
            if not path.startswith(("prompt_base/", "prompt_plugins/", "prompt_patches/", "checklists/"))
        ],
        "excluded_patches": [
            {
                "patch_id": patch["patch_id"],
                "status": patch["status"],
                "reason": "状态未进入本次导出的允许集合",
            }
            for patch in all_profile_patches
            if patch["patch_id"] not in selected_ids
        ],
        "export_flags": {"include_candidate_patches": include_candidates},
        "runtime_pack_sha256": sha256_bytes(pack_content.encode("utf-8")),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出可复现的数模比赛运行规则包和 manifest。")
    parser.add_argument("--profile", default="engineering_optimization", choices=sorted(PROFILE_FILES))
    parser.add_argument("--output", default="export/cumcm_runtime_pack.md")
    parser.add_argument("--manifest-output", help="manifest 路径；默认与运行包同名并加 .manifest.json。")
    parser.add_argument("--include-candidate-patches", action="store_true", help="测试用：额外导入 candidate patch。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = ROOT / args.output
    manifest_output = (
        ROOT / args.manifest_output
        if args.manifest_output
        else output.with_suffix(".manifest.json")
    )
    pack_content = build_pack(args.profile, args.include_candidate_patches)
    manifest = build_manifest(args.profile, pack_content, args.include_candidate_patches)

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    # 按 UTF-8 字节写入，避免 Windows 自动换行转换破坏 manifest 中的哈希。
    output.write_bytes(pack_content.encode("utf-8"))
    manifest_output.write_bytes(
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(f"已导出运行包：{output}")
    print(f"已导出 manifest：{manifest_output}")


if __name__ == "__main__":
    main()
