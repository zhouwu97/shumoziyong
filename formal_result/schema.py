"""仅允许从仓库 Schema 目录加载合同。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .errors import FormalResultVerificationError


ROOT = Path(__file__).resolve().parents[1]


def validate_schema(value: Any, schema_name: str, label: str) -> None:
    if "/" in schema_name or "\\" in schema_name or not schema_name.endswith(".schema.json"):
        raise FormalResultVerificationError(f"{label} 引用了非法 Schema")
    schema_path = ROOT / "schemas" / schema_name
    if not schema_path.is_file():
        raise FormalResultVerificationError(f"{label} 引用的 Schema 不存在：{schema_name}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        detail = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise FormalResultVerificationError(f"{label} 不符合 Schema：{detail}")
