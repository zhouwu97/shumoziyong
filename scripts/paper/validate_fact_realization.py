from __future__ import annotations

import argparse
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from paper_compiler_common import load_json, sha256_file, validate_schema, write_json


FACT_PATTERN = re.compile(
    r"<!--FACT:(?P<id>[A-Z0-9._-]+) type=(?P<type>[a-z_]+)-->(?P<value>[\s\S]*?)<!--/FACT:(?P=id)-->",
)
COMMENT_PATTERN = re.compile(r"<!--[\s\S]*?-->")
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[,.]\d+)*(?:%|‰)?")
DIRECTION_WORDS = ("增加", "提高", "降低", "减少", "上升", "下降")
OPTIMALITY_OVERCLAIMS = ("达到全局最优", "获得全局最优", "为全局最优", "严格最优解")
UNSUPPORTED_SIGNIFICANCE = ("显著提高", "显著降低", "统计显著")


def make_issue(code: str, message: str, ref_id: str | None = None) -> dict[str, str]:
    value = {"severity": "FAIL", "code": code, "message": message}
    if ref_id:
        value["ref_id"] = ref_id
    return value


def numbers(text: str) -> list[str]:
    return NUMBER_PATTERN.findall(text)


def decimal_or_none(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "").replace("%", "").replace("‰", ""))
    except InvalidOperation:
        return None


def classify_marker_drift(binding: dict[str, Any], actual: str) -> str:
    expected = binding["rendered_text"]
    if binding["ref_type"] == "formula":
        return "PFC_FORMULA_DRIFT"
    if binding["ref_type"] == "boundary":
        return "PFC_SCOPE_EXPANDED"
    expected_directions = {word for word in DIRECTION_WORDS if word in expected}
    actual_directions = {word for word in DIRECTION_WORDS if word in actual}
    if expected_directions != actual_directions:
        return "PFC_DIRECTION_DRIFT"
    if "较" in expected and numbers(expected) == numbers(actual):
        expected_prefix = expected.split(numbers(expected)[0], 1)[0] if numbers(expected) else expected
        actual_prefix = actual.split(numbers(actual)[0], 1)[0] if numbers(actual) else actual
        if expected_prefix != actual_prefix:
            return "PFC_BASELINE_MISMATCH"
    expected_numbers = numbers(expected)
    actual_numbers = numbers(actual)
    if expected_numbers != actual_numbers:
        if len(expected_numbers) == len(actual_numbers) == 1:
            left = decimal_or_none(expected_numbers[0])
            right = decimal_or_none(actual_numbers[0])
            if left == right and expected_numbers[0] != actual_numbers[0]:
                return "PFC_PRECISION_DRIFT"
        return "PFC_NUMBER_DRIFT"
    expected_unit = str(binding.get("display", {}).get("unit", ""))
    if expected_unit and expected_unit not in actual:
        return "PFC_UNIT_DRIFT"
    return "PFC_FACT_TEXT_DRIFT"


def validate_realization(
    paper_path: Path,
    projection_path: Path,
    exemptions_path: Path | None = None,
) -> dict[str, Any]:
    paper_text = paper_path.read_text(encoding="utf-8")
    projection = load_json(projection_path)
    validate_schema(projection, "paper_fact_projection.schema.json")
    bindings = {item["binding_id"]: item for item in projection["fact_bindings"]}
    issues: list[dict[str, str]] = []
    counts: Counter[str] = Counter()

    for match in FACT_PATTERN.finditer(paper_text):
        ref_id = match.group("id")
        counts[ref_id] += 1
        binding = bindings.get(ref_id)
        if not binding:
            issues.append(make_issue("PFC_UNBOUND_FACT", f"正文包含未知事实标记：{ref_id}", ref_id))
            continue
        if match.group("type") != binding["ref_type"]:
            issues.append(make_issue("PFC_FACT_TYPE_MISMATCH", f"{ref_id} 类型变化", ref_id))
        if match.group("value") != binding["rendered_text"]:
            code = classify_marker_drift(binding, match.group("value"))
            issues.append(make_issue(code, f"{ref_id} 的渲染内容与事实投影不一致", ref_id))

    for ref_id, binding in bindings.items():
        count = counts[ref_id]
        requirement = binding["usage"]["requirement"]
        if binding["ref_type"] == "boundary" and requirement.startswith("required") and count == 0:
            issues.append(make_issue("PFC_BOUNDARY_REMOVED", f"必要边界被删除：{ref_id}", ref_id))
        elif requirement == "required_once" and count != 1:
            issues.append(make_issue("PFC_FACT_CARDINALITY", f"{ref_id} 应出现一次，实际 {count} 次", ref_id))
        elif requirement == "required_at_least_once" and count < 1:
            issues.append(make_issue("PFC_FACT_CARDINALITY", f"{ref_id} 至少应出现一次", ref_id))

    outside = paper_text
    if exemptions_path:
        exemptions = load_json(exemptions_path)
        validate_schema(exemptions, "paper_typed_exemptions.schema.json")
        if exemptions["source_sha256"] != sha256_file(paper_path):
            issues.append(make_issue("PFC_EXEMPTION_SOURCE_DRIFT", "数字豁免对应的源文件哈希已经失效"))
        else:
            encoded = bytearray(outside.encode("utf-8"))
            for exemption in exemptions["exemptions"]:
                start = exemption["source_span"]["start_byte"]
                end = exemption["source_span"]["end_byte"]
                encoded[start:end] = b" " * (end - start)
            outside = encoded.decode("utf-8")
    outside = FACT_PATTERN.sub(lambda match: " " * len(match.group(0)), outside)
    outside = COMMENT_PATTERN.sub("", outside)
    if NUMBER_PATTERN.search(outside):
        issues.append(make_issue("PFC_UNBOUND_SEMANTIC_NUMBER", "正文存在未绑定且未由解析器豁免的数字"))
    if any(phrase in outside for phrase in OPTIMALITY_OVERCLAIMS):
        issues.append(make_issue("PFC_OPTIMALITY_OVERCLAIM", "正文将可行或候选结果扩大为最优结论"))
    if any(phrase in outside for phrase in UNSUPPORTED_SIGNIFICANCE):
        issues.append(make_issue("PFC_UNSUPPORTED_SIGNIFICANCE", "正文包含没有统计证据的显著性表述"))

    report = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_fact_realization_report",
        "status": "failed" if issues else "passed",
        "inputs": {
            "paper": str(paper_path.resolve()),
            "paper_sha256": sha256_file(paper_path),
            "projection": str(projection_path.resolve()),
            "projection_sha256": sha256_file(projection_path),
        },
        "summary": {"bindings_checked": len(bindings), "failures": len(issues)},
        "issues": issues,
        "reference_counts": dict(sorted(counts.items())),
    }
    validate_schema(report, "paper_fact_realization_report.schema.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="验证人工改写后的事实实现是否漂移")
    parser.add_argument("--paper", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--typed-exemptions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate_realization(args.paper, args.projection, args.typed_exemptions)
    write_json(args.output, report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
