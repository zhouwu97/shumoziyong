from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def get_path(data: dict[str, Any], dotted_path: str) -> tuple[bool, Any]:
    current: Any = data
    for part in dotted_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return False, None
        else:
            return False, None
    return True, current


def _extract_strings(value: Any) -> list[str]:
    """把任意 JSON 值归一化为字符串列表，用于字段级禁止值匹配。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, bool):
        return [str(value)]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            out.extend(_extract_strings(v))
        return out
    if isinstance(value, dict):
        out = []
        for v in value.values():
            out.extend(_extract_strings(v))
        return out
    return [str(value)]


def evaluate_case(case: dict[str, Any], response: dict[str, Any]) -> list[str]:
    expected = case["expected"]
    errors: list[str] = []

    # 1) 字段等值检查：primary_type 等
    for path, expected_value in expected.get("values", {}).items():
        found, actual = get_path(response, path)
        if not found or actual != expected_value:
            errors.append(f"{path} 期望 {expected_value!r}，实际 {actual!r}")

    # 2) 必需字段非空
    for path in expected.get("must_have_paths", []):
        found, value = get_path(response, path)
        if not found or value in (None, "", [], {}):
            errors.append(f"缺少必需字段或内容：{path}")

    # 3) 字段级禁止值：只检查指定字段，不检查解释、拒绝理由或自由文本。
    #    避免全局字符串搜索误判“正确拒绝神经网络”这类场景。
    for path, forbidden_list in expected.get("forbidden_values", {}).items():
        found, actual = get_path(response, path)
        if not found:
            continue  # 字段缺失不触发（如需必需，用 must_have_paths）
        actual_strings = _extract_strings(actual)
        for forbidden in forbidden_list:
            fl = forbidden.lower()
            for source in actual_strings:
                if fl in source.lower():
                    errors.append(f"{path} 出现禁止值：{forbidden}（来源：{source!r}）")
                    break

    # 4) patch_decisions.applicable 检查：负控题上指定 patch 应判定为不适用。
    for patch_id, expected_applicable in expected.get("patch_not_applicable", {}).items():
        path = f"patch_decisions.{patch_id}.applicable"
        found, actual = get_path(response, path)
        if not found:
            errors.append(f"缺少 {path}；负控题必须显式判定 patch 适用性")
        elif actual != expected_applicable:
            errors.append(
                f"{path} 期望 {expected_applicable!r}，实际 {actual!r}（负控题上 patch 应判定为不适用）"
            )
        reason_path = f"patch_decisions.{patch_id}.reason"
        found_r, reason = get_path(response, reason_path)
        if found_r and (reason in (None, "")):
            errors.append(f"{reason_path} 为空；不适用判定必须给出理由")

    # 5) 人工确认项
    if expected.get("requires_manual_confirmation"):
        found, value = get_path(response, "manual_confirmation")
        if not found or value in (None, "", [], {}, False):
            errors.append("缺少有效的 manual_confirmation")

    # 6) 兼容：must_not_contain 全局搜索（已弃用，优先使用 forbidden_values）
    serialized = json.dumps(response, ensure_ascii=False).lower()
    for forbidden in expected.get("must_not_contain", []):
        if forbidden.lower() in serialized:
            errors.append(f"出现禁止内容（全局匹配，建议改用 forbidden_values 字段级检查）：{forbidden}")

    return errors


def load_case(case_file: Path, case_id: str | None = None) -> dict[str, Any]:
    data = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    if case_id:
        cases = [case for case in cases if case.get("case_id") == case_id]
    if len(cases) != 1:
        raise ValueError("请确保用例文件只含一个用例，或通过 --case-id 精确选择。")
    return cases[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按语义字段和禁止项评估模型结构化输出。")
    parser.add_argument("--case", required=True, help="YAML 回归用例路径。")
    parser.add_argument("--response", required=True, help="模型输出 JSON 路径。")
    parser.add_argument("--case-id")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    case = load_case(ROOT / args.case, args.case_id)
    response = json.loads((ROOT / args.response).read_text(encoding="utf-8"))
    errors = evaluate_case(case, response)
    if errors:
        for error in errors:
            print(f"[FAIL] {case['case_id']}：{error}")
        raise SystemExit(1)
    print(f"[PASS] {case['case_id']}")


if __name__ == "__main__":
    main()
