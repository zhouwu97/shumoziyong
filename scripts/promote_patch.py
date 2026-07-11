"""通过显式人工命令晋级 Patch，禁止手改 patch_index.json。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_bytes
from evidence_validation import derive_v2_matrix_results, validate_formal_patch


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policies" / "promotion_policy.json"
MATRIX_PATH = ROOT / "tests" / "prompt_regression" / "patch_negative_control_matrix.json"
INDEX_PATH = ROOT / "prompt_patches" / "patch_index.json"


def _load_object(path: Path, label: str) -> dict[str, Any] | list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, (dict, list)):
        raise ValueError(f"{label} 必须是 JSON 对象或数组")
    return value


def promote_patch(
    patch_id: str,
    target_status: str,
    approval_reviewer: str,
    *,
    root: Path = ROOT,
    index_path: Path | None = None,
    matrix_path: Path | None = None,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """验证完整证据后以原子写入把一个 Patch 晋级到目标状态。"""
    if target_status != "competition_evidenced":
        raise ValueError("当前仅支持晋级到 competition_evidenced")
    if not approval_reviewer.strip():
        raise ValueError("--approval 不能为空，且必须匹配稳定证据中的审核人")

    root = root.resolve()
    index_path = (index_path or root / "prompt_patches" / "patch_index.json").resolve()
    matrix_path = (
        matrix_path or root / "tests" / "prompt_regression" / "patch_negative_control_matrix.json"
    ).resolve()
    policy_path = (policy_path or root / "policies" / "promotion_policy.json").resolve()

    raw_index = _load_object(index_path, "patch_index.json")
    policy = _load_object(policy_path, "promotion_policy.json")
    matrix = _load_object(matrix_path, "patch_negative_control_matrix.json")
    if not isinstance(raw_index, list) or not isinstance(policy, dict) or not isinstance(matrix, dict):
        raise ValueError("晋级输入文件结构不合法")

    patch = next(
        (item for item in raw_index if isinstance(item, dict) and item.get("patch_id") == patch_id),
        None,
    )
    if patch is None:
        raise ValueError(f"Patch {patch_id} 不存在")
    if patch.get("status") != "regression_verified":
        raise ValueError(
            f"Patch {patch_id} 当前状态为 {patch.get('status')}，"
            "仅允许从 regression_verified 显式晋级"
        )
    stable_evidence = patch.get("stable_evidence", {})
    if not isinstance(stable_evidence, dict):
        raise ValueError("Patch 缺少结构化 stable_evidence")
    approval = stable_evidence.get("human_approval_record", {})
    if not isinstance(approval, dict) or approval.get("reviewer") != approval_reviewer:
        raise ValueError("--approval 必须与 stable_evidence.human_approval_record.reviewer 完全一致")

    derived_matrix, matrix_errors = derive_v2_matrix_results(matrix, policy, root=root)
    if matrix_errors:
        raise ValueError("v2 控制现场证据无效：" + "；".join(matrix_errors))
    matrix_entry = next(
        (
            item
            for item in derived_matrix.get("patches", [])
            if isinstance(item, dict) and item.get("patch_id") == patch_id
        ),
        None,
    )
    if matrix_entry is None:
        raise ValueError(f"Patch {patch_id} 在 v2 控制矩阵中没有记录")

    outcome = validate_formal_patch(
        patch,
        matrix_entry,
        policy,
        root=root,
        expected_status=target_status,
        enforce_recorded_status=False,
    )
    if not outcome.valid:
        raise ValueError("晋级证据未闭合：" + "；".join(outcome.errors))

    patch["status"] = target_status
    final_outcome = validate_formal_patch(
        patch, matrix_entry, policy, root=root, expected_status=target_status
    )
    if not final_outcome.valid:
        raise ValueError("晋级后的现场复核失败：" + "；".join(final_outcome.errors))

    rendered = (json.dumps(raw_index, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(index_path, rendered)
    return {
        "patch_id": patch_id,
        "previous_status": "regression_verified",
        "target_status": target_status,
        "reviewer": approval_reviewer,
        "derived_status": final_outcome.identity.get("derived_status"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证证据后原子晋级 Patch。")
    parser.add_argument("--patch", required=True, dest="patch_id")
    parser.add_argument(
        "--target", required=True, choices=["competition_evidenced"], dest="target_status"
    )
    parser.add_argument(
        "--approval",
        required=True,
        dest="approval_reviewer",
        help="stable_evidence.human_approval_record 中已批准的 reviewer。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = promote_patch(
            args.patch_id, args.target_status, args.approval_reviewer
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"晋级失败：{exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
