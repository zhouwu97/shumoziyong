from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Iterator

from paper_compiler_common import sha256_file, validate_schema, write_json


RULES = (
    ("year", "year_expression", re.compile(r"(?<!\d)(?:19|20)\d{2}(?=\s*年)")),
    ("figure_number", "figure_reference", re.compile(r"(?<=图)\s*\d+(?:[-.．]\d+)?")),
    ("table_number", "table_reference", re.compile(r"(?<=表)\s*\d+(?:[-.．]\d+)?")),
    ("formula_number", "formula_reference", re.compile(r"(?<=式)\s*\d+(?:[-.．]\d+)?")),
)


def byte_offset(text: str, character_offset: int) -> int:
    return len(text[:character_offset].encode("utf-8"))


def matches(text: str) -> Iterator[tuple[str, str, int, int]]:
    citation_pattern = re.compile(r"\[(?P<body>\d+(?:\s*[-,，]\s*\d+)*)\]")
    for citation in citation_pattern.finditer(text):
        body_start = citation.start("body")
        for number in re.finditer(r"\d+", citation.group("body")):
            yield (
                "citation_number",
                "citation",
                body_start + number.start(),
                body_start + number.end(),
            )
    for exemption_type, node_type, pattern in RULES:
        for match in pattern.finditer(text):
            start, end = match.span()
            yield exemption_type, node_type, start, end
    heading_pattern = re.compile(r"(?m)^#+\s+(?P<number>\d+(?:\.\d+)*)[.．]?\s+")
    for match in heading_pattern.finditer(text):
        start, end = match.span("number")
        yield "section_number", "markdown_heading", start, end


def parse_exemptions(source_path: Path) -> dict[str, Any]:
    text = source_path.read_text(encoding="utf-8")
    found: list[tuple[int, int, str, str, str]] = []
    for exemption_type, node_type, start, end in matches(text):
        found.append((start, end, exemption_type, node_type, text[start:end]))
    found.sort()
    exemptions = []
    for index, (start, end, exemption_type, node_type, value) in enumerate(found, start=1):
        exemptions.append(
            {
                "exemption_id": f"EX-{index:05d}",
                "type": exemption_type,
                "value": value.strip(),
                "source_span": {
                    "start_byte": byte_offset(text, start),
                    "end_byte": byte_offset(text, end),
                },
                "ast_node_type": node_type,
            }
        )
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_typed_exemptions",
        "source_file": str(source_path.resolve()),
        "source_sha256": sha256_file(source_path),
        "detector": "paper_structure_number_parser",
        "detector_version": "1.0.0",
        "exemptions": exemptions,
    }
    validate_schema(payload, "paper_typed_exemptions.schema.json")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="解析可定位的排版与引用数字豁免")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_json(args.output, parse_exemptions(args.source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
