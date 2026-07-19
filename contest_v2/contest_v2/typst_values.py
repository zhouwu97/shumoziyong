"""从派生 Ledger 确定性生成 Typst 结果变量。"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from .result_ledger import ResultLedger


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _name(question_id: str, metric_id: str) -> str:
    value = re.sub(r"[^a-z0-9-]", "-", f"{question_id}-{metric_id.replace('_', '-')}")
    value = re.sub(r"-+", "-", value).strip("-")
    if not value or not value[0].isalpha():
        raise ValueError(f"无法生成 Typst 名称：{question_id}/{metric_id}")
    return value


def _raw(value: int | float | str | bool) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return f'"{_escape(value)}"'
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Typst 不接受非有限浮点数")
    return repr(value)


def render_typst(ledger: ResultLedger) -> str:
    lines = ["// AUTO-GENERATED. DO NOT EDIT.", f'// contest_id: {_escape(ledger.contest_id)}']
    names: set[str] = set()
    for entry in ledger.entries:
        name = _name(entry.question_id, entry.metric_id)
        if name in names:
            raise ValueError(f"Typst 名称冲突：{name}")
        names.add(name)
        lines.extend(
            [
                f"#let {name}-raw = {_raw(entry.value)}",
                f'#let {name} = "{_escape(entry.display_value)}"',
                f'#let {name}-unit = "{_escape(entry.unit)}"',
                f'#let {name}-verification = "{entry.verification}"',
            ]
        )
    lines.append("")
    return "\n".join(lines)


def generate(ledger_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_typst(ResultLedger.load(ledger_path)), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.ledger, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
