"""
检查 patch 晋级资格与当前状态的差距。

完全委托给 promotion_engine.py —— 这是 promotion_policy.json 的唯一调用入口。
禁止本文件自行硬编码晋级规则。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from promotion_engine import (
    PromotionGap,
    evaluate_full,
    load_json,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policies" / "promotion_policy.json"
MATRIX_PATH = ROOT / "tests" / "prompt_regression" / "patch_negative_control_matrix.json"
INDEX_PATH = ROOT / "prompt_patches" / "patch_index.json"


def check_promotion_eligibility() -> tuple[dict[str, Any], list[PromotionGap]]:
    """返回 (report, gaps)。gaps 来自 promotion_engine 的统一评估。

    与上一版的关键区别：
      - review_ready patch 现在会报告“到 regression_verified 还差什么”。
      - 机制计数为 patch 级别，不从 profile 继承。
      - 真正检查 failure_labels.json 中的 P/M 标签。
    """
    policy = load_json(POLICY_PATH)
    matrix = load_json(MATRIX_PATH)
    patch_index = load_json(INDEX_PATH)

    matrix_by_id: dict[str, dict[str, Any]] = {
        item["patch_id"]: item for item in matrix.get("patches", [])
    }

    all_gaps: list[PromotionGap] = []
    results: list[dict[str, Any]] = []

    for patch in patch_index:
        pid = patch.get("patch_id", "<unknown>")
        current_status = patch.get("status", "draft")
        entry = matrix_by_id.get(pid, {})

        full = evaluate_full(patch, entry, policy, all_matrix_entries=matrix_by_id)

        # 收集当前状态的 gaps
        for g in full.current_gaps:
            all_gaps.append(PromotionGap(pid, current_status, g))

        # 收集下一级状态的 gaps（review_ready → regression_verified 等）
        for g in full.gaps_to_next_status:
            next_s = full.next_status or "?"
            all_gaps.append(PromotionGap(pid, next_s, g))

        # 按控制类型收集 pass/fail
        control_results: dict[str, str] = {}
        for control in ("positive", "boundary", "negative"):
            control_results[control] = entry.get(control, {}).get("result", "pending")
        passed_count = sum(1 for r in control_results.values() if r == "pass")

        results.append(
            {
                "patch_id": pid,
                "current_status": current_status,
                "current_status_valid": full.current_status_valid,
                "current_gaps": full.current_gaps,
                "next_status": full.next_status,
                "next_status_eligible": full.next_status_eligible,
                "gaps_to_next_status": full.gaps_to_next_status,
                "positive": control_results["positive"],
                "boundary": control_results["boundary"],
                "negative": control_results["negative"],
                "passed_controls": passed_count,
                "total_controls": 3,
                "distinct_problems": sorted(
                    {entry.get(c, {}).get("case") for c in ("positive", "boundary", "negative") if entry.get(c, {}).get("case")}
                ),
            }
        )

    report: dict[str, Any] = {
        "policy_version": policy["policy_version"],
        "checked_at": None,
        "total_patches": len(patch_index),
        "patches_with_gaps": len({g.patch_id for g in all_gaps}),
        "total_gaps": len(all_gaps),
        "gaps": [str(g) for g in all_gaps],
        "per_patch": results,
        "verdict": "all_eligible" if not all_gaps else "gaps_found",
    }

    return report, all_gaps


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 patch 晋级资格与当前状态的差距。")
    parser.add_argument("--output", help="将机器可读报告写入指定 JSON 文件。")
    parser.add_argument("--strict", action="store_true", help="存在差距时以非 0 退出码返回。")
    args = parser.parse_args()

    report, gaps = check_promotion_eligibility()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")

    if gaps:
        print(f"\n发现 {len(gaps)} 条差距：")
        for g in gaps:
            print(f"  {g}")
        if args.strict:
            raise SystemExit(2)

    raise SystemExit(0)


if __name__ == "__main__":
    main()
