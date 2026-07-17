from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_schema(payload: Any, schema_name: str) -> None:
    schema = load_json(ROOT / "schemas" / schema_name)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda item: list(item.absolute_path),
    )
    if not errors:
        return
    rendered = []
    for error in errors[:20]:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        rendered.append(f"{location}: {error.message}")
    raise ValueError(f"{schema_name} 校验失败：" + "；".join(rendered))


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer 必须为空或以 / 开头")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(f"无法在标量值上继续解析 {pointer}")
    return current


def resolve_inside(base: Path, relative: str) -> Path:
    base_resolved = base.resolve()
    target = (base_resolved / relative).resolve()
    try:
        target.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"路径越出运行目录：{relative}") from exc
    if not target.is_file():
        raise FileNotFoundError(target)
    return target


def relative_posix(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def normalize_formula_tokens(expression: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*|<=|>=|==|[-+*/=()]|\d+(?:\.\d+)?", expression)


def format_binding_value(value: Any, display: dict[str, Any]) -> str:
    literal = display.get("literal")
    if literal is not None:
        rendered_literal = str(literal)
        if display.get("strip_terminal_punctuation"):
            rendered_literal = rendered_literal.rstrip("。；;.!！")
        return rendered_literal
    prefix = str(display.get("prefix", ""))
    suffix = str(display.get("suffix", ""))
    if isinstance(value, bool):
        rendered = str(value)
    elif isinstance(value, (int, float, Decimal)):
        scaled = Decimal(str(value)) * Decimal(str(display.get("scale", 1)))
        places = display.get("decimal_places")
        if places is None:
            rendered = format(scaled, "f")
        else:
            quantum = Decimal("1").scaleb(-int(places))
            rounded = scaled.quantize(quantum, rounding=ROUND_HALF_UP)
            rendered = f"{rounded:.{int(places)}f}"
    else:
        rendered = str(value)
    result = f"{prefix}{rendered}{suffix}"
    if display.get("strip_terminal_punctuation"):
        result = result.rstrip("。；;.!！")
    return result


def decimal_operation(operation: str, left: Any, right: Any) -> Decimal:
    left_decimal = Decimal(str(left))
    right_decimal = Decimal(str(right))
    if operation == "subtract":
        return left_decimal - right_decimal
    if operation == "ratio":
        if right_decimal == 0:
            raise ValueError("比值派生的分母不能为 0")
        return left_decimal / right_decimal
    raise ValueError(f"不支持的派生操作：{operation}")


def rhetoric_bundle_digest(cards: list[dict[str, str]]) -> str:
    """计算只依赖卡片身份、路径和内容哈希的稳定包摘要。"""
    canonical = json.dumps(cards, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_verified_bundle_cards(
    card_dir: Path,
    bundle: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """按 Manifest 加载卡片，并验证路径、内容哈希和包摘要。"""
    cards: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, str]] = []
    expected_digest = rhetoric_bundle_digest(bundle["cards"])
    if bundle["content_sha256"] != expected_digest:
        issues.append(
            {
                "severity": "FAIL",
                "code": "PFC_CARD_BUNDLE_DIGEST_DRIFT",
                "message": "卡片包内容摘要与 Manifest 不一致",
            }
        )

    card_root = card_dir.resolve()
    seen_ids: set[str] = set()
    for entry in bundle["cards"]:
        card_id = entry["card_id"]
        if card_id in seen_ids:
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "PFC_CARD_BUNDLE_DUPLICATE_ID",
                    "message": f"卡片包包含重复 card_id：{card_id}",
                }
            )
            continue
        seen_ids.add(card_id)
        try:
            path = resolve_inside(ROOT, entry["path"])
            path.relative_to(card_root)
        except (FileNotFoundError, ValueError) as exc:
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "PFC_CARD_BUNDLE_PATH_INVALID",
                    "message": f"卡片 {card_id} 的 Manifest 路径无效：{exc}",
                }
            )
            continue
        if sha256_file(path) != entry["sha256"]:
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "PFC_CARD_BUNDLE_HASH_DRIFT",
                    "message": f"卡片 {card_id} 的内容哈希与 Manifest 不一致",
                }
            )
            continue
        card = load_json(path)
        try:
            validate_schema(card, "paper_rhetoric_card.schema.json")
        except ValueError as exc:
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "PFC_CARD_SCHEMA_INVALID",
                    "message": f"卡片 {card_id} 不符合 Schema：{exc}",
                }
            )
            continue
        if card["card_id"] != card_id:
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "PFC_CARD_BUNDLE_ID_MISMATCH",
                    "message": f"Manifest 的 {card_id} 与文件内 card_id 不一致",
                }
            )
            continue
        cards[card_id] = card
    return cards, issues
