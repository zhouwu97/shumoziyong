from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from evaluation_case_registry import (
    EVALUATOR_VERSION,
    find_authorized_case,
    load_registry,
    sha256_bytes,
    substantive_assertion_count,
)


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



def evaluate_manifest_alignment(
    response: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    active_patch_ids = {
        patch.get("patch_id")
        for patch in manifest.get("patches", [])
        if patch.get("patch_id")
    }

    decisions = response.get("patch_decisions", {})
    if not isinstance(decisions, dict):
        return ["patch_decisions 必须是对象"]

    for patch_id, decision in decisions.items():
        if not isinstance(decision, dict):
            errors.append(f"patch_decisions.{patch_id} 必须是对象")
            continue

        expected_enabled = patch_id in active_patch_ids
        actual_enabled = decision.get("enabled")

        if actual_enabled != expected_enabled:
            errors.append(
                f"patch_decisions.{patch_id}.enabled "
                f"期望 {expected_enabled}，实际 {actual_enabled}"
                "（与运行包包含情况不符）"
            )

        reason = decision.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(
                f"patch_decisions.{patch_id}.reason 不能为空；"
                "必须说明 Patch 的加载状态或适用性判断理由"
            )

    missing_active = active_patch_ids - set(decisions)
    if missing_active:
        errors.append(f"缺少已加载 Patch 的决策：{sorted(missing_active)}")

    return errors


def load_case(case_file: Path, case_id: str | None = None) -> dict[str, Any]:
    data = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    if case_id:
        cases = [case for case in cases if case.get("case_id") == case_id]
    if len(cases) != 1:
        raise ValueError("请确保用例文件只含一个用例，或通过 --case-id 精确选择。")
    return cases[0]


def repo_relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按语义字段和禁止项评估模型结构化输出。")
    parser.add_argument("--case", required=True, help="YAML 回归用例路径。")
    parser.add_argument("--response", required=True, help="模型输出 JSON 路径。")
    parser.add_argument("--case-id")
    parser.add_argument("--manifest", help="runtime_pack.manifest.json 路径")
    parser.add_argument("--output", help="自动评估结果输出路径")
    parser.add_argument("--promotion-evidence", action="store_true", help="启用晋级评估模式，强制校验 manifest 和生成 output")
    args = parser.parse_args()
    if args.promotion_evidence:
        if not args.manifest or not args.output:
            parser.error("--promotion-evidence 模式下必须提供 --manifest 和 --output。")
    return args


def main() -> None:
    args = parse_args()
    case_path = ROOT / args.case
    case = load_case(case_path, args.case_id)
    case_sha256 = sha256_bytes(case_path.read_bytes())
    authorized_case = None
    if args.promotion_evidence:
        registry = load_registry()
        authorized_case = find_authorized_case(
            registry,
            case_id=case["case_id"],
            case_file=repo_relative(case_path),
            case_sha256=case_sha256,
        )
        if authorized_case is None:
            raise ValueError("晋级评估用例未在 evaluation_case_registry.json 中授权")
        assertion_count = substantive_assertion_count(case)
        minimum = authorized_case["minimum_assertion_count"]
        if assertion_count < minimum:
            raise ValueError(
                "晋级评估用例的实质断言不足："
                f"当前 {assertion_count}，授权下限 {minimum}"
            )
    response_text = (ROOT / args.response).read_text(encoding="utf-8")
    response = json.loads(response_text)
    errors = evaluate_case(case, response)

    manifest_text = ""
    if args.manifest:
        manifest_text = (ROOT / args.manifest).read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        errors.extend(evaluate_manifest_alignment(response, manifest))

    result = "fail" if errors else "pass"

    if args.output:
        import hashlib, datetime
        out = {
            "case_id": case["case_id"],
            "case_file": repo_relative(ROOT / args.case) if "repo_relative" in globals() else str(args.case),
            "result": result,
            "errors": errors,
            "evaluated_at": datetime.datetime.now().astimezone().isoformat(),
            "evaluator_version": EVALUATOR_VERSION,
            "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
            "case_sha256": case_sha256,
            "manifest_sha256": hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() if args.manifest else None
        }
        if authorized_case is not None:
            out.update(
                {
                    "case_registry_version": registry["registry_version"],
                    "control_type": authorized_case["control_type"],
                    "target_patch": authorized_case["target_patch"],
                    "assertion_count": substantive_assertion_count(case),
                }
            )
        (ROOT / args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if errors:
        for error in errors:
            print(f"[FAIL] {case['case_id']}：{error}")
        raise SystemExit(1)
    print(f"[PASS] {case['case_id']}")


if __name__ == "__main__":
    main()
