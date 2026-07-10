from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUTO_PATCHES_MARKER = "__AUTO_PATCHES__"
# 正式运行包只允许已批准的 patch：状态为 verified_candidate/stable
# AND patch_id 必须出现在对应 runtime profile 的 verified_patches 列表中。
VERIFIED_STATUSES = {"verified_candidate", "stable"}
CANDIDATE_STATUS = "candidate"
CANDIDATE_WARNING = "仅供旧题验证，不得直接比赛使用"

PROFILE_FILES = {
    "general": [
        "export/mathmodelagent_inject_prompt.md",
        "prompt_base/prompt_base_v1.0.md",
        "runtime_profiles/general_runtime.md",
        "checklists/gate_0_material_diagnosis.md",
        "checklists/gate_1_model_route.md",
        "checklists/gate_2_code_plan.md",
        "checklists/gate_3_results_confirmation.md",
        "checklists/gate_4_paper_confirmation.md",
        "checklists/gate_5_final_acceptance.md",
    ],
    "engineering_optimization": [
        "export/mathmodelagent_inject_prompt.md",
        "prompt_base/prompt_base_v1.0.md",
        "runtime_profiles/engineering_optimization_runtime.md",
        "prompt_plugins/plugin_optimization_v1.md",
        AUTO_PATCHES_MARKER,
        "checklists/gate_0_material_diagnosis.md",
        "checklists/gate_1_model_route.md",
        "checklists/gate_2_code_plan.md",
        "checklists/gate_3_results_confirmation.md",
        "checklists/gate_4_paper_confirmation.md",
        "checklists/gate_5_final_acceptance.md",
    ],
    "evaluation": [
        "export/mathmodelagent_inject_prompt.md",
        "prompt_base/prompt_base_v1.0.md",
        "runtime_profiles/evaluation_runtime.md",
        "checklists/gate_0_material_diagnosis.md",
        "checklists/gate_1_model_route.md",
        "checklists/gate_2_code_plan.md",
        "checklists/gate_3_results_confirmation.md",
        "checklists/gate_4_paper_confirmation.md",
        "checklists/gate_5_final_acceptance.md",
    ],
    "prediction": [
        "export/mathmodelagent_inject_prompt.md",
        "prompt_base/prompt_base_v1.0.md",
        "runtime_profiles/prediction_runtime.md",
        "checklists/gate_0_material_diagnosis.md",
        "checklists/gate_1_model_route.md",
        "checklists/gate_2_code_plan.md",
        "checklists/gate_3_results_confirmation.md",
        "checklists/gate_4_paper_confirmation.md",
        "checklists/gate_5_final_acceptance.md",
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


def read_profile_state(profile: str) -> dict[str, Any]:
    path = ROOT / "runtime_profiles" / f"{profile}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def select_patches(
    profile: str,
    candidate_patch_ids: list[str] | None = None,
    exclude_patch_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """选择进入运行包的 patch。

    正式 patch 必须同时满足三条件：
      1. patch_index 中 status 属于 {verified_candidate, stable}；
      2. patch_id 在 runtime_profiles/<profile>.json 的 verified_patches 中；
      3. patch 的 runtime_profiles 包含当前 profile。

    candidate patch 必须显式按 ID 传入，且每个都必须：
      存在于 patch_index；状态为 candidate；runtime_profiles 包含当前 profile。

    exclude_patch_ids 用于隔离实验：从已批准集合中移除指定 patch（如负控 baseline）。
    """
    state = read_profile_state(profile)
    approved_ids = set(state.get("verified_patches", []))
    candidate_patch_ids = list(candidate_patch_ids or [])
    exclude_set = set(exclude_patch_ids or [])

    patches_by_id = {patch["patch_id"]: patch for patch in read_patch_index()}

    # 校验显式 candidate patch
    for cid in candidate_patch_ids:
        patch = patches_by_id.get(cid)
        if patch is None:
            raise ValueError(f"--candidate-patch {cid} 不存在于 patch_index")
        if patch.get("status") != CANDIDATE_STATUS:
            raise ValueError(
                f"--candidate-patch {cid} 状态为 {patch.get('status')}，"
                f"仅可显式导入 status={CANDIDATE_STATUS} 的 patch"
            )
        if profile not in patch.get("runtime_profiles", []):
            raise ValueError(f"--candidate-patch {cid} 不支持 profile {profile}")

    # 校验显式排除 patch：必须存在且支持当前 profile（否则排除无意义）
    for eid in exclude_set:
        patch = patches_by_id.get(eid)
        if patch is None:
            raise ValueError(f"--exclude-patch {eid} 不存在于 patch_index")
        if profile not in patch.get("runtime_profiles", []):
            raise ValueError(f"--exclude-patch {eid} 不支持 profile {profile}")

    # 正式 patch：三条件 AND
    verified_selected = [
        patch
        for patch in read_patch_index()
        if patch.get("patch_id") in approved_ids
        and profile in patch.get("runtime_profiles", [])
        and patch.get("status") in VERIFIED_STATUSES
        and patch.get("file")
    ]
    # 隔离实验：从已批准集合中移除显式排除项
    verified_selected = [p for p in verified_selected if p["patch_id"] not in exclude_set]

    # 显式 candidate patch（按传入顺序保留，随后排序统一处理）
    candidate_selected = [patches_by_id[cid] for cid in candidate_patch_ids]

    selected = verified_selected + candidate_selected
    selected.sort(key=lambda item: (item.get("priority", 999), item.get("patch_id", "")))
    return selected


def select_patch_files(
    profile: str,
    candidate_patch_ids: list[str] | None = None,
    exclude_patch_ids: list[str] | None = None,
) -> list[str]:
    return [patch["file"] for patch in select_patches(profile, candidate_patch_ids, exclude_patch_ids)]


def resolve_pack_files(
    profile: str,
    candidate_patch_ids: list[str] | None = None,
    exclude_patch_ids: list[str] | None = None,
) -> list[str]:
    if profile not in PROFILE_FILES:
        available = ", ".join(sorted(PROFILE_FILES))
        raise ValueError(f"未知 profile：{profile}。可选项：{available}")

    files: list[str] = []
    for relative_path in PROFILE_FILES[profile]:
        if relative_path == AUTO_PATCHES_MARKER:
            files.extend(select_patch_files(profile, candidate_patch_ids, exclude_patch_ids))
        else:
            files.append(relative_path)
    return files


def build_pack(
    profile: str,
    candidate_patch_ids: list[str] | None = None,
    exclude_patch_ids: list[str] | None = None,
) -> str:
    files = resolve_pack_files(profile, candidate_patch_ids, exclude_patch_ids)
    profile_state = read_profile_state(profile)
    parts = [
        "# 数模比赛运行规则包\n\n",
        f"- profile：`{profile}`\n",
        f"- runtime version：`{profile_state['version']}`\n",
        f"- maturity：`{profile_state['maturity']}`\n",
        "- 用途：复制到比赛工作目录的 `rules/runtime_pack.md`，供 MathModelAgent 执行前读取。\n",
        "- 原则：先诊断，后建模；先确认路线，后代码；先验证结果，后论文。\n",
    ]
    if candidate_patch_ids:
        parts.append(f"- 警告：本次显式包含 candidate patch（{', '.join(candidate_patch_ids)}），{CANDIDATE_WARNING}。\n")
    if exclude_patch_ids:
        parts.append(f"- 警告：本次隔离实验排除已批准 patch（{', '.join(exclude_patch_ids)}），仅用于负控或对比测试。\n")
    parts.append("\n")

    for relative_path in files:
        parts.append(f"\n\n# ===== {relative_path} =====\n\n")
        parts.append(read_text(relative_path))
    return "".join(parts)


def _exclusion_reason(patch: dict[str, Any], profile: str, approved_ids: set[str],
                      candidate_ids: list[str], exclude_set: set[str]) -> str:
    pid = patch.get("patch_id", "<unknown>")
    status = patch.get("status")
    reasons: list[str] = []
    if pid in exclude_set:
        reasons.append("显式排除（隔离实验）")
    if status in VERIFIED_STATUSES and pid not in approved_ids:
        reasons.append("状态为 verified 但未进入 profile.verified_patches")
    if status == CANDIDATE_STATUS and pid not in candidate_ids:
        reasons.append("candidate patch 未显式指定导入")
    if status not in VERIFIED_STATUSES and status != CANDIDATE_STATUS:
        reasons.append(f"状态 {status} 不允许导出")
    if not approved_ids and status in VERIFIED_STATUSES and pid in approved_ids:
        # approved_ids empty branch safety (shouldn't reach)
        pass
    return "；".join(reasons) if reasons else "状态未进入本次导出的允许集合"


def build_manifest(
    profile: str,
    pack_content: str,
    candidate_patch_ids: list[str] | None = None,
    exclude_patch_ids: list[str] | None = None,
) -> dict[str, Any]:
    candidate_patch_ids = list(candidate_patch_ids or [])
    exclude_patch_ids = list(exclude_patch_ids or [])
    exclude_set = set(exclude_patch_ids)

    profile_state_path = f"runtime_profiles/{profile}.json"
    profile_state = json.loads(read_text(profile_state_path))
    approved_ids = set(profile_state.get("verified_patches", []))

    selected_patches = select_patches(profile, candidate_patch_ids, exclude_patch_ids)
    selected_ids = {patch["patch_id"] for patch in selected_patches}
    all_profile_patches = [
        patch for patch in read_patch_index() if profile in patch.get("runtime_profiles", [])
    ]
    files = resolve_pack_files(profile, candidate_patch_ids, exclude_patch_ids)

    def records(prefix: str) -> list[dict[str, str]]:
        return [file_record(path) for path in files if path.startswith(prefix)]

    base_records = records("prompt_base/")
    return {
        "manifest_version": "1.1.0",
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
                "reason": _exclusion_reason(
                    patch, profile, approved_ids, candidate_patch_ids, exclude_set
                ),
            }
            for patch in all_profile_patches
            if patch["patch_id"] not in selected_ids
        ],
        "candidate_experiment": {
            "enabled": bool(candidate_patch_ids),
            "patch_ids": candidate_patch_ids,
            "warning": CANDIDATE_WARNING if candidate_patch_ids else None,
        },
        "exclusion_experiment": {
            "enabled": bool(exclude_patch_ids),
            "patch_ids": exclude_patch_ids,
        },
        "export_flags": {
            "candidate_patches": candidate_patch_ids,
            "excluded_patches": exclude_patch_ids,
        },
        "runtime_pack_sha256": sha256_bytes(pack_content.encode("utf-8")),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出可复现的数模比赛运行规则包和 manifest。")
    parser.add_argument("--profile", default="engineering_optimization", choices=sorted(PROFILE_FILES))
    parser.add_argument("--output", default="export/cumcm_runtime_pack.md")
    parser.add_argument("--manifest-output", help="manifest 路径；默认与运行包同名并加 .manifest.json。")
    parser.add_argument(
        "--candidate-patch",
        action="append",
        default=[],
        metavar="PATCH_ID",
        dest="candidate_patch",
        help="显式加入指定 candidate patch，可重复传入；每个必须存在于 patch_index、状态为 candidate、支持当前 profile。",
    )
    parser.add_argument(
        "--exclude-patch",
        action="append",
        default=[],
        metavar="PATCH_ID",
        dest="exclude_patch",
        help="显式排除已批准 patch（隔离实验用，如负控 baseline / A092-only / A127-only），可重复传入。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = ROOT / args.output
    manifest_output = (
        ROOT / args.manifest_output
        if args.manifest_output
        else output.with_suffix(".manifest.json")
    )
    pack_content = build_pack(args.profile, args.candidate_patch, args.exclude_patch)
    manifest = build_manifest(args.profile, pack_content, args.candidate_patch, args.exclude_patch)

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
