from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROUNDING_PATTERN = re.compile(r"^(?P<places>\d+)_decimal$")
PERCENT_PATTERN = re.compile(r"^percent_(?P<places>\d+)_decimal$")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """按 RFC 6901 解析 JSON Pointer。"""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer 必须为空字符串或以 / 开头")

    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"数组索引不存在: {token}") from exc
        elif isinstance(current, dict):
            if token not in current:
                raise KeyError(f"对象字段不存在: {token}")
            current = current[token]
        else:
            raise KeyError(f"无法在标量值上继续解析: {token}")
    return current


def decimal_value(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise InvalidOperation("布尔值不是受支持的数字")
    return Decimal(str(value))


def numeric_equal(left: Any, right: Any) -> bool:
    try:
        return decimal_value(left) == decimal_value(right)
    except (InvalidOperation, ValueError):
        return left == right


def parse_display_number(display: str) -> Decimal:
    normalized = display.strip().replace(",", "").replace("，", "")
    normalized = normalized.replace("%", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", normalized)
    if not match:
        raise InvalidOperation(f"显示值中没有可解析数字: {display}")
    return Decimal(match.group(0))


def validate_rounding(raw_value: Any, display_value: str, rule: str) -> tuple[bool, str]:
    try:
        raw = decimal_value(raw_value)
        shown = parse_display_number(display_value)
    except (InvalidOperation, ValueError) as exc:
        return False, str(exc)

    percent = PERCENT_PATTERN.fullmatch(rule)
    decimal_rule = ROUNDING_PATTERN.fullmatch(rule)
    if rule == "integer":
        places = 0
    elif percent:
        places = int(percent.group("places"))
        raw *= Decimal("100")
        if "%" not in display_value:
            return False, "百分比舍入规则要求显示值包含 %"
    elif decimal_rule:
        places = int(decimal_rule.group("places"))
    else:
        return False, f"不支持的舍入规则: {rule}"

    quantum = Decimal("1").scaleb(-places)
    expected = raw.quantize(quantum, rounding=ROUND_HALF_UP)
    if shown != expected:
        return False, f"显示值应为 {expected}，实际为 {shown}"

    number_match = re.search(r"[-+]?\d+(?:[,.，]\d+)*", display_value)
    shown_text = number_match.group(0).replace(",", "").replace("，", "") if number_match else ""
    actual_places = len(shown_text.partition(".")[2]) if "." in shown_text else 0
    if actual_places != places:
        return False, f"显示值应保留 {places} 位小数，实际保留 {actual_places} 位"
    return True, ""


def claim_windows(paper_text: str, claim_id: str, radius: int = 800) -> list[str]:
    windows: list[str] = []
    start_at = 0
    while True:
        position = paper_text.find(claim_id, start_at)
        if position < 0:
            return windows
        start = max(0, position - radius)
        end = min(len(paper_text), position + len(claim_id) + radius)
        windows.append(paper_text[start:end])
        start_at = position + len(claim_id)


def add_issue(
    issues: list[dict[str, Any]],
    code: str,
    message: str,
    claim_id: str | None = None,
) -> None:
    item: dict[str, Any] = {"severity": "FAIL", "code": code, "message": message}
    if claim_id:
        item["claim_id"] = claim_id
    issues.append(item)


def check_bindings(
    bindings_path: Path,
    paper_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    payload = load_json(bindings_path)
    claims = payload.get("claims", payload if isinstance(payload, list) else [])
    if not isinstance(claims, list):
        raise ValueError("Claim 绑定文件必须是列表，或包含 claims 列表")

    paper_text = paper_path.read_text(encoding="utf-8")
    issues: list[dict[str, Any]] = []
    checked_sources: dict[str, str] = {}
    conflict_map: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            add_issue(issues, "invalid_claim", f"第 {index + 1} 个 Claim 不是对象")
            continue
        claim_id = str(claim.get("claim_id", "")).strip()
        if not claim_id:
            add_issue(issues, "missing_claim_id", f"第 {index + 1} 个 Claim 缺少 claim_id")
            continue

        required = [
            "source_file",
            "json_pointer",
            "raw_value",
            "display_value",
            "unit",
            "rounding_rule",
        ]
        missing = [field for field in required if field not in claim]
        if missing:
            add_issue(issues, "missing_fields", f"缺少字段: {', '.join(missing)}", claim_id)
            continue

        source_path = (project_root / str(claim["source_file"])).resolve()
        try:
            source_path.relative_to(project_root.resolve())
        except ValueError:
            add_issue(
                issues, "source_outside_root", f"来源文件越出项目根目录: {source_path}", claim_id
            )
            continue
        if not source_path.is_file():
            add_issue(issues, "missing_source", f"来源文件不存在: {source_path}", claim_id)
            continue

        checked_sources[str(source_path)] = sha256_file(source_path)
        try:
            source_value = resolve_json_pointer(load_json(source_path), str(claim["json_pointer"]))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            add_issue(issues, "invalid_json_pointer", str(exc), claim_id)
            continue

        if not numeric_equal(source_value, claim["raw_value"]):
            add_issue(
                issues,
                "raw_value_mismatch",
                f"来源值 {source_value!r} 与锁定原始值 {claim['raw_value']!r} 不一致",
                claim_id,
            )

        rounding_ok, rounding_message = validate_rounding(
            claim["raw_value"], str(claim["display_value"]), str(claim["rounding_rule"])
        )
        if not rounding_ok:
            add_issue(issues, "rounding_mismatch", rounding_message, claim_id)

        windows = claim_windows(paper_text, claim_id)
        if not windows:
            add_issue(issues, "claim_not_in_paper", "论文中未出现 Claim ID", claim_id)
        else:
            display = str(claim["display_value"])
            display_variants = {display, display.replace(",", ""), display.replace("，", "")}
            if not any(
                variant and variant in window for window in windows for variant in display_variants
            ):
                add_issue(
                    issues, "display_value_not_locked", "Claim 附近未出现锁定显示值", claim_id
                )
            unit = str(claim["unit"])
            if unit and not any(unit in window for window in windows):
                add_issue(issues, "unit_mismatch", f"Claim 附近未出现锁定单位 {unit}", claim_id)
            for token in claim.get("conclusion_tokens", []):
                if not any(str(token) in window for window in windows):
                    add_issue(
                        issues,
                        "conclusion_token_missing",
                        f"Claim 附近未出现锁定结论词: {token}",
                        claim_id,
                    )

        conflict_map[claim_id].append(
            (
                json.dumps(claim["raw_value"], ensure_ascii=False, sort_keys=True),
                str(claim["display_value"]),
                str(claim["unit"]),
            )
        )

    for claim_id, values in conflict_map.items():
        if len(set(values)) > 1:
            add_issue(
                issues, "conflicting_claim_values", "同一 Claim 对应多个冲突值或单位", claim_id
            )

    return {
        "schema_version": "1.0.0",
        "passed": not issues,
        "inputs": {
            "bindings": str(bindings_path.resolve()),
            "bindings_sha256": sha256_file(bindings_path),
            "paper": str(paper_path.resolve()),
            "paper_sha256": sha256_file(paper_path),
            "project_root": str(project_root.resolve()),
        },
        "summary": {
            "claims_checked": len(claims),
            "source_files_checked": len(checked_sources),
            "failures": len(issues),
        },
        "source_sha256": checked_sources,
        "issues": issues,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查论文 Claim 与结果 JSON 的数字绑定")
    parser.add_argument("--bindings", type=Path, required=True, help="claim_bindings.json")
    parser.add_argument("--paper", type=Path, required=True, help="论文源文件")
    parser.add_argument(
        "--project-root", type=Path, default=Path.cwd(), help="来源文件相对的项目根目录"
    )
    parser.add_argument("--output", type=Path, default=Path("paper_claim_check.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = check_bindings(args.bindings, args.paper, args.project_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
