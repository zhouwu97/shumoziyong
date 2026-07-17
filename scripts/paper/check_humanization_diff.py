from __future__ import annotations

import argparse
import hashlib
import json
import re
from itertools import zip_longest
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

try:
    from .check_paper_source import AI_WARNING_PHRASES, iter_balanced_calls, strip_comments
except ImportError:  # 允许直接执行脚本。
    from check_paper_source import AI_WARNING_PHRASES, iter_balanced_calls, strip_comments


ROOT = Path(__file__).resolve().parents[2]
NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?%?"
)
UNIT_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:%|‰|mm|cm|km|m|ms|s|min|h|kg|g|mg|kW|W|J|Hz|MHz|GHz|"
    r"件|台|次|秒|分钟|小时|天|周|月|年|米|毫米|厘米|千米|克|千克|吨|元|万元|"
    r"件/小时|次/分钟)(?![A-Za-z])"
)
CITATION_PATTERN = re.compile(r"\[(?:\d+)(?:\s*[-,，]\s*\d+)*\]|@(?!fig[-_:]|tab[-_:]|eq[-_:])[A-Za-z][\w.:-]*")
FIGURE_TABLE_REF_PATTERN = re.compile(
    r"(?:图|表)\s*\d+(?:[-–—.]\d+)?|@(?:fig|tab)[-_:][A-Za-z0-9_.:-]+",
    flags=re.IGNORECASE,
)
DIRECTION_PATTERN = re.compile(
    r"最大化|最小化|最大|最小|提高|降低|增加|减少|上升|下降|优于|劣于|"
    r"不低于|不高于|不少于|不超过|正相关|负相关|正向|负向|可行|不可行"
)
SCOPE_PATTERN = re.compile(
    r"全局最优|局部最优|近似最优|候选(?:集合|范围)?内最优|给定(?:配置|范围|预算|参数)下最优|"
    r"启发式(?:解|策略)|不保证全局最优"
)
MATH_PATTERNS = (
    re.compile(r"\$[\s\S]*?\$"),
    re.compile(r"\\\([\s\S]*?\\\)"),
    re.compile(r"\\\[[\s\S]*?\\\]"),
)
SYMBOL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[A-Za-zΑ-Ωα-ω][A-Za-z0-9_Α-Ωα-ω]*(?![A-Za-z0-9_])")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_text(path: Path) -> str:
    return strip_comments(path.read_text(encoding="utf-8"), path.suffix)


def extract_matches(pattern: re.Pattern[str], text: str) -> list[str]:
    return [match.group(0) for match in pattern.finditer(text)]


def extract_formulas(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for pattern in MATH_PATTERNS:
        found.extend((match.start(), match.group(0)) for match in pattern.finditer(text))
    found.extend(iter_balanced_calls(text, "#equation"))
    return [value for _, value in sorted(found, key=lambda item: item[0])]


def extract_symbols(text: str) -> list[str]:
    symbols: list[str] = []
    for formula in extract_formulas(text):
        symbols.extend(extract_matches(SYMBOL_PATTERN, formula))
    symbols.extend(match.group(1) for match in re.finditer(r"`([A-Za-zΑ-Ωα-ω][\wΑ-Ωα-ω]*)`", text))
    return symbols


def extract_table_cells(text: str) -> list[str]:
    cells: list[str] = []
    for _, call in iter_balanced_calls(text, "#three-line-table"):
        cells.extend(
            re.sub(r"\s+", " ", match.group(1)).strip()
            for match in re.finditer(r"\[([^\[\]]*)\]", call)
        )
    return cells


def extract_paragraphs(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def sequence_changes(before: list[str], after: list[str]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip_longest(before, after)):
        if left != right:
            changes.append({"index": index, "before": left, "after": right})
    return changes


def rewritten_paragraph_count(before: str, after: str) -> int:
    left = extract_paragraphs(before)
    right = extract_paragraphs(after)
    return sum(1 for a, b in zip_longest(left, right) if a != b)


def compare_category(
    before: str, after: str, extractor: Callable[[str], list[str]]
) -> list[dict[str, Any]]:
    return sequence_changes(extractor(before), extractor(after))


def check_humanization_diff(source_path: Path, output_path: Path) -> dict[str, Any]:
    source = clean_text(source_path)
    output = clean_text(output_path)
    categories = {
        "protected_numbers_changed": compare_category(
            source, output, lambda text: extract_matches(NUMBER_PATTERN, text)
        ),
        "protected_formulas_changed": compare_category(source, output, extract_formulas),
        "protected_units_changed": compare_category(
            source, output, lambda text: extract_matches(UNIT_PATTERN, text)
        ),
        "protected_symbols_changed": compare_category(source, output, extract_symbols),
        "citations_changed": compare_category(
            source, output, lambda text: extract_matches(CITATION_PATTERN, text)
        ),
        "figure_table_refs_changed": compare_category(
            source, output, lambda text: extract_matches(FIGURE_TABLE_REF_PATTERN, text)
        ),
        "table_cells_changed": compare_category(source, output, extract_table_cells),
        "direction_phrases_changed": compare_category(
            source, output, lambda text: extract_matches(DIRECTION_PATTERN, text)
        ),
        "scope_phrases_changed": compare_category(
            source, output, lambda text: extract_matches(SCOPE_PATTERN, text)
        ),
    }
    removed_stock_phrases = sum(
        max(0, source.count(phrase) - output.count(phrase)) for phrase in AI_WARNING_PHRASES
    )
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "source_sha256": sha256_file(source_path),
        "output_sha256": sha256_file(output_path),
        **categories,
        "rewritten_paragraph_count": rewritten_paragraph_count(source, output),
        "stock_phrases_removed": removed_stock_phrases,
        "status": "failed" if any(categories.values()) else "passed",
    }
    schema = json.loads(
        (ROOT / "schemas" / "paper_humanization_report.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查 Humanizer 前后受保护字段是否漂移")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, default=Path("paper_humanization_report.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = check_humanization_diff(args.source, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "rewritten_paragraph_count": report["rewritten_paragraph_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
