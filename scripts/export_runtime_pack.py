from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_bytes
from evidence_validation import derive_v2_matrix_results, validate_formal_patch
from profile_derivation import derive_profile_report


ROOT = Path(__file__).resolve().parents[1]
AUTO_PATCHES_MARKER = "__AUTO_PATCHES__"
# 正式运行包只允许现场状态为 regression_verified/competition_evidenced 的 Patch。
VERIFIED_STATUSES = {"regression_verified", "competition_evidenced"}
CANDIDATE_STATUS = "review_ready"
CANDIDATE_WARNING = "仅供旧题验证，不得直接比赛使用"
POLICY_PATH = ROOT / "policies" / "promotion_policy.json"
MATRIX_PATH = ROOT / "tests" / "prompt_regression" / "patch_negative_control_matrix.json"

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


def build_timestamp() -> str:
    """生成时间允许由 SOURCE_DATE_EPOCH 固定，但不参与 Build Identity。"""
    source_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_epoch is not None:
        return datetime.fromtimestamp(int(source_epoch), tz=timezone.utc).isoformat()
    return datetime.now().astimezone().isoformat(timespec="seconds")


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


def _read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return value


def _derive_profile_state(
    profile: str, patches: list[dict[str, Any]]
) -> tuple[dict[str, Any], str]:
    """重算 Profile 成熟度，禁止手填 maturity 进入运行包。"""
    profile_state = read_profile_state(profile)
    policy = _read_object(POLICY_PATH, "promotion_policy.json")
    report = derive_profile_report(
        profile_state,
        patches,
        root=ROOT,
        policy=policy,
    )
    computed = str(report["computed_maturity"])
    if report["invalid_records"]:
        raise ValueError(
            f"Profile {profile} 现场证据无效：{report['invalid_records']}"
        )
    if profile_state.get("maturity") != computed:
        raise ValueError(
            f"Profile {profile} 手填 maturity 与现场证据不一致："
            f"记录为 {profile_state.get('maturity')}，现场为 {computed}"
        )
    return profile_state, computed


def _validate_formal_patches(patches: list[dict[str, Any]]) -> None:
    """对所有正式 Patch 重算控制结论和晋级资格。"""
    formal = [patch for patch in patches if patch.get("status") in VERIFIED_STATUSES]
    if not formal:
        return
    policy = _read_object(POLICY_PATH, "promotion_policy.json")
    matrix = _read_object(MATRIX_PATH, "patch_negative_control_matrix.json")
    matrix, matrix_errors = derive_v2_matrix_results(matrix, policy, root=ROOT)
    if matrix_errors:
        raise ValueError("v2 控制现场证据无效：" + "；".join(matrix_errors))
    matrix_by_id = {
        item.get("patch_id"): item
        for item in matrix.get("patches", [])
        if isinstance(item, dict)
    }
    for patch in formal:
        patch_id = str(patch.get("patch_id", "<unknown>"))
        outcome = validate_formal_patch(
            patch,
            matrix_by_id.get(patch_id, {}),
            policy,
            root=ROOT,
        )
        if not outcome.valid:
            raise ValueError(
                f"正式 Patch {patch_id} 现场证据不满足 {patch.get('status')}："
                + "；".join(outcome.errors)
            )


def select_patches(
    profile: str,
    candidate_patch_ids: list[str] | None = None,
    exclude_patch_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """选择进入运行包的 patch。

    正式 Patch 必须同时满足两个条件：状态已通过回归或比赛证据验证，且声明支持当前 Profile。

    review_ready patch 必须显式按 ID 传入，且每个都必须：
      存在于 patch_index；状态为 review_ready；runtime_profiles 包含当前 profile。

    exclude_patch_ids 用于隔离实验：从已批准集合中移除指定 patch（如负控 baseline）。
    """
    candidate_patch_ids = list(candidate_patch_ids or [])
    exclude_set = set(exclude_patch_ids or [])

    all_patches = read_patch_index()
    _validate_formal_patches(all_patches)
    patches_by_id = {patch["patch_id"]: patch for patch in all_patches}

    # 校验显式 review_ready 实验 patch
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

    # 正式 Patch：状态与 Profile 归属均从事实源现场判断。
    verified_selected = [
        patch
        for patch in all_patches
        if profile in patch.get("runtime_profiles", [])
        and patch.get("status") in VERIFIED_STATUSES
        and patch.get("file")
    ]
    # 隔离实验：从已批准集合中移除显式排除项
    verified_selected = [p for p in verified_selected if p["patch_id"] not in exclude_set]

    # 显式 review_ready 实验 patch（按传入顺序保留，随后排序统一处理）
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
    all_patches = read_patch_index()
    profile_state, computed_maturity = _derive_profile_state(profile, all_patches)
    parts = [
        "# 数模比赛运行规则包\n\n",
        f"- profile：`{profile}`\n",
        f"- runtime version：`{profile_state['version']}`\n",
        f"- maturity：`{computed_maturity}`\n",
        "- 用途：复制到比赛工作目录的 `rules/runtime_pack.md`，供 MathModelAgent 执行前读取。\n",
        "- 原则：先诊断，后建模；先确认路线，后代码；先验证结果，后论文。\n",
    ]
    if candidate_patch_ids:
        parts.append(f"- 警告：本次显式包含 review_ready patch（{', '.join(candidate_patch_ids)}），{CANDIDATE_WARNING}。\n")
    if exclude_patch_ids:
        parts.append(f"- 警告：本次隔离实验排除已批准 patch（{', '.join(exclude_patch_ids)}），仅用于负控或对比测试。\n")
    parts.append("\n")

    for relative_path in files:
        parts.append(f"\n\n# ===== {relative_path} =====\n\n")
        parts.append(read_text(relative_path))
    return "".join(parts)


def _exclusion_reason(
    patch: dict[str, Any], candidate_ids: list[str], exclude_set: set[str]
) -> str:
    pid = patch.get("patch_id", "<unknown>")
    status = patch.get("status")
    reasons: list[str] = []
    if pid in exclude_set:
        reasons.append("显式排除（隔离实验）")
    if status == CANDIDATE_STATUS and pid not in candidate_ids:
        reasons.append("review_ready patch 未显式指定导入")
    if status not in VERIFIED_STATUSES and status != CANDIDATE_STATUS:
        reasons.append(f"状态 {status} 不允许导出")
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
    all_patches = read_patch_index()
    profile_state, computed_maturity = _derive_profile_state(profile, all_patches)
    selected_patches = select_patches(profile, candidate_patch_ids, exclude_patch_ids)
    selected_ids = {patch["patch_id"] for patch in selected_patches}
    all_profile_patches = [
        patch for patch in all_patches if profile in patch.get("runtime_profiles", [])
    ]
    files = resolve_pack_files(profile, candidate_patch_ids, exclude_patch_ids)

    def records(prefix: str) -> list[dict[str, str]]:
        return [file_record(path) for path in files if path.startswith(prefix)]

    base_records = records("prompt_base/")
    manifest = {
        "manifest_version": "1.1.0",
        "runtime_version": profile_state["version"],
        "generated_at": build_timestamp(),
        "profile": profile,
        "maturity": computed_maturity,
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
                    patch, candidate_patch_ids, exclude_set
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
    identity_payload = {
        key: value for key, value in manifest.items() if key != "generated_at"
    }
    manifest["build_identity"] = sha256_bytes(
        json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return manifest


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
        help="显式加入指定 review_ready patch，可重复传入；每个必须存在于 patch_index 且支持当前 profile。",
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
    atomic_write_bytes(output, pack_content.encode("utf-8"))
    atomic_write_bytes(
        manifest_output,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(f"已导出运行包：{output}")
    print(f"已导出 manifest：{manifest_output}")


if __name__ == "__main__":
    main()
