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
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def evaluate_case(case: dict[str, Any], response: dict[str, Any]) -> list[str]:
    expected = case["expected"]
    errors: list[str] = []
    for path, expected_value in expected.get("values", {}).items():
        found, actual = get_path(response, path)
        if not found or actual != expected_value:
            errors.append(f"{path} 期望 {expected_value!r}，实际 {actual!r}")
    for path in expected.get("must_have_paths", []):
        found, value = get_path(response, path)
        if not found or value in (None, "", [], {}):
            errors.append(f"缺少必需字段或内容：{path}")
    serialized = json.dumps(response, ensure_ascii=False).lower()
    for forbidden in expected.get("must_not_contain", []):
        if forbidden.lower() in serialized:
            errors.append(f"出现禁止内容：{forbidden}")
    if expected.get("requires_manual_confirmation"):
        found, value = get_path(response, "manual_confirmation")
        if not found or value in (None, "", [], {}, False):
            errors.append("缺少有效的 manual_confirmation")
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
