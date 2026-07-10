"""
检查 patch 晋级资格与当前状态的差距。

与 validate_repository.py 的区别：
  - validate_repository.py 在 CI 中硬失败（exit 1），强制要求 verified_candidate/stable 的
    positive+boundary+negative 全部 pass；这是提交门禁，不允许跳过。
  - 本工具是"差距分析"：读取 promotion_policy.json 和矩阵统计每个 patch 的达标情况，
    报告哪些条件还不满足、还差多少才能达到下一级状态。它用于人工决策辅助，
    不修改任何状态文件。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policies" / "promotion_policy.json"
MATRIX_PATH = ROOT / "tests" / "prompt_regression" / "patch_negative_control_matrix.json"
INDEX_PATH = ROOT / "prompt_patches" / "patch_index.json"


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class PromotionGap:
    """一条不满足的条件。"""

    def __init__(self, patch_id: str, target_status: str, condition: str) -> None:
        self.patch_id = patch_id
        self.target_status = target_status
        self.condition = condition

    def __str__(self) -> str:
        return f"[{self.patch_id}] → {self.target_status}：{self.condition}"


def _count_passed_controls(entry: dict[str, Any]) -> int:
    """统计一条矩阵记录中 pass 的控制类型数。"""
    count = 0
    for key in ("positive", "boundary", "negative"):
        if entry.get(key, {}).get("result") == "pass":
            count += 1
    return count


def _check_negative_evidence(entry: dict[str, Any]) -> list[str]:
    """检查负控证据链是否完整。"""
    issues: list[str] = []
    neg = entry.get("negative", {})
    if neg.get("result") != "pass":
        return issues  # 还未 pass，不算证据问题

    evidence = neg.get("evidence")
    if not isinstance(evidence, dict):
        issues.append("negative 为 pass 但缺少 evidence 对象")
        return issues

    required_fields = ["baseline_run", "treatment_run", "comparison_review"]
    for field in required_fields:
        if not evidence.get(field):
            issues.append(f"negative evidence 缺少 {field}")
        else:
            path = ROOT / evidence[field]
            if not path.exists():
                issues.append(f"negative evidence {field} 路径不存在：{evidence[field]}")

    return issues


def check_promotion_eligibility() -> tuple[dict[str, Any], list[PromotionGap]]:
    """返回 (report, gaps)。gaps 为空表示所有 patch 都满足其当前状态的最低要求。"""
    policy = load_json(POLICY_PATH)
    matrix = load_json(MATRIX_PATH)
    patch_index = load_json(INDEX_PATH)

    matrix_by_id: dict[str, dict[str, Any]] = {
        item["patch_id"]: item for item in matrix.get("patches", [])
    }
    index_by_id: dict[str, dict[str, Any]] = {
        item["patch_id"]: item for item in patch_index
    }

    gaps: list[PromotionGap] = []
    results: list[dict[str, Any]] = []

    for patch in patch_index:
        pid = patch.get("patch_id", "<unknown>")
        current_status = patch.get("status", "draft")
        entry = matrix_by_id.get(pid, {})

        positive_result = entry.get("positive", {}).get("result", "pending")
        boundary_result = entry.get("boundary", {}).get("result", "pending")
        negative_result = entry.get("negative", {}).get("result", "pending")
        passed_count = sum(
            1 for r in (positive_result, boundary_result, negative_result) if r == "pass"
        )

        negative_issues = _check_negative_evidence(entry)

        # Determine which status level to validate against
        target_for_check = current_status  # 检查当前状态是否满足其自身的门槛

        if current_status in ("verified_candidate", "stable"):
            rules = policy["status_rules"].get(current_status, {})
            required_controls = rules.get("required_controls", [])
            min_cases = rules.get("min_distinct_cases", 0)

            # 1) 控制类型是否全齐
            for control in required_controls:
                if entry.get(control, {}).get("result") != "pass":
                    gaps.append(
                        PromotionGap(pid, current_status, f"{control}-control 必须为 pass（当前为 {entry.get(control, {}).get('result', 'pending')}）")
                    )

            # 2) 独立考题数量
            tested_problems = set()
            for control in ("positive", "boundary", "negative"):
                case = entry.get(control, {}).get("case")
                if case:
                    tested_problems.add(case)
            if len(tested_problems) < min_cases:
                gaps.append(
                    PromotionGap(pid, current_status, f"至少需要 {min_cases} 道不同考题，当前只有 {len(tested_problems)} 道（{sorted(tested_problems)}）")
                )

            # 3) stable 额外要求
            if current_status == "stable":
                rules_stable = policy["status_rules"]["stable"]
                min_mechanisms = rules_stable.get("min_distinct_mechanisms", 3)
                # Count mechanisms from profile validation data
                profiles = patch.get("runtime_profiles", [])
                mechanism_count = 0
                for prof_id in profiles:
                    prof_path = ROOT / "runtime_profiles" / f"{prof_id}.json"
                    if prof_path.exists():
                        prof_data = load_json(prof_path)
                        mechanisms = prof_data.get("validation", {}).get("mechanism_classes", [])
                        mechanism_count = max(mechanism_count, len(mechanisms))
                if mechanism_count < min_mechanisms:
                    gaps.append(
                        PromotionGap(pid, current_status, f"至少需要覆盖 {min_mechanisms} 个机制类，当前最多覆盖 {mechanism_count}")
                    )

                if rules_stable.get("requires_failure_fix_retest") and not patch.get("failure_fix_record"):
                    gaps.append(
                        PromotionGap(pid, current_status, "需要至少 1 次失败修复重测记录 (failure_fix_record)")
                    )

            # 4) 负控证据链完整性
            for issue in negative_issues:
                gaps.append(PromotionGap(pid, current_status, issue))

            # 5) 检查是否有 P 标签（可从 validation_records 中推断）
            if not patch.get("validation_records"):
                if current_status in ("verified_candidate", "stable"):
                    gaps.append(
                        PromotionGap(pid, current_status, "缺少 validation_records 条目")
                    )

        results.append(
            {
                "patch_id": pid,
                "current_status": current_status,
                "positive": positive_result,
                "boundary": boundary_result,
                "negative": negative_result,
                "passed_controls": passed_count,
                "total_controls": 3,
                "distinct_problems": sorted(
                    {entry.get(c, {}).get("case") for c in ("positive", "boundary", "negative") if entry.get(c, {}).get("case")}
                ),
                "negative_evidence_issues": negative_issues,
                "gaps_for_current_status": len(
                    [g for g in gaps if g.patch_id == pid]
                ),
            }
        )

    report: dict[str, Any] = {
        "policy_version": policy["policy_version"],
        "checked_at": None,  # 避免不可复现时间戳
        "total_patches": len(patch_index),
        "patches_with_gaps": len({g.patch_id for g in gaps}),
        "total_gaps": len(gaps),
        "gaps": [str(g) for g in gaps],
        "per_patch": results,
        "verdict": "all_eligible" if not gaps else "gaps_found",
    }

    return report, gaps


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
