from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from paper_compiler_common import load_json, sha256_file, validate_schema, write_json


CHAR_N = 8
MAX_CONTIGUOUS_ALLOWED = 19
MAX_CHAR_NGRAM_OVERLAP = 0.35
DISTINCTIVE_MIN_LENGTH = 16


def normalize(text: str) -> str:
    text = re.sub(r"\$[\s\S]*?\$", "", text)
    text = re.sub(r"\d+(?:\.\d+)?", "", text)
    return re.sub(r"[^A-Za-z\u4e00-\u9fff]", "", text).lower()


def card_texts(card: dict[str, Any]) -> list[str]:
    values = [card["action"], *card["logic_pattern"]]
    if card.get("inference_policy"):
        values.extend(card["inference_policy"]["allowed_verbs"])
    return [normalize(value) for value in values if normalize(value)]


def longest_match_in_source(text: str, source: str) -> int:
    if not text:
        return 0
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if any(text[index : index + middle] in source for index in range(len(text) - middle + 1)):
            low = middle
        else:
            high = middle - 1
    return low


def longest_match_details(text: str, source: str) -> tuple[int, str, int, int]:
    length = longest_match_in_source(text, source)
    if length == 0:
        return 0, "", -1, -1
    for card_start in range(len(text) - length + 1):
        fragment = text[card_start : card_start + length]
        source_start = source.find(fragment)
        if source_start >= 0:
            return length, fragment, card_start, source_start
    return 0, "", -1, -1


def normalize_with_lines(text: str) -> tuple[str, list[int]]:
    masked = list(text)
    for pattern in (re.compile(r"\$[\s\S]*?\$"), re.compile(r"\d+(?:\.\d+)?")):
        for match in pattern.finditer(text):
            masked[match.start() : match.end()] = " " * (match.end() - match.start())
    normalized: list[str] = []
    lines: list[int] = []
    line_number = 1
    for character in "".join(masked):
        if character == "\n":
            line_number += 1
        if re.match(r"[A-Za-z\u4e00-\u9fff]", character):
            normalized.append(character.lower())
            lines.append(line_number)
    return "".join(normalized), lines


def ngrams(text: str, n: int) -> set[str]:
    return {text[index : index + n] for index in range(max(0, len(text) - n + 1))}


def check_overlap(
    card_dir: Path,
    source_path: Path,
    generated_path: Path,
) -> dict[str, Any]:
    source, source_lines = normalize_with_lines(source_path.read_text(encoding="utf-8"))
    source_ngrams = ngrams(source, CHAR_N)
    results = []
    for path in sorted(card_dir.glob("RC-*.json")):
        card = load_json(path)
        validate_schema(card, "paper_rhetoric_card.schema.json")
        texts = card_texts(card)
        details = [longest_match_details(text, source) for text in texts]
        longest, fragment, card_start, source_start = max(details, default=(0, "", -1, -1))
        card_ngrams = set().union(*(ngrams(text, CHAR_N) for text in texts)) if texts else set()
        overlap = len(card_ngrams & source_ngrams) / len(card_ngrams) if card_ngrams else 0.0
        distinctive = [
            text for text in texts if len(text) >= DISTINCTIVE_MIN_LENGTH and text in source
        ]
        passed = (
            longest <= MAX_CONTIGUOUS_ALLOWED
            and overlap <= MAX_CHAR_NGRAM_OVERLAP
            and not distinctive
        )
        results.append(
            {
                "card_id": card["card_id"],
                "longest_contiguous_match": longest,
                "char_ngram_overlap": round(overlap, 6),
                "distinctive_phrase_hits": distinctive,
                "highest_match": {
                    "normalized_text": fragment,
                    "card_normalized_start": card_start,
                    "source_normalized_start": source_start,
                    "source_line": source_lines[source_start] if source_start >= 0 else None,
                },
                "automatic_status": "passed" if passed else "failed",
            }
        )
    generated, generated_lines = normalize_with_lines(generated_path.read_text(encoding="utf-8"))
    generated_length, generated_fragment, generated_start, generated_source_start = (
        longest_match_details(generated, source)
    )
    generated_ngrams = ngrams(generated, CHAR_N)
    generated_overlap = (
        len(generated_ngrams & source_ngrams) / len(generated_ngrams) if generated_ngrams else 0.0
    )
    generated_passed = (
        generated_length <= MAX_CONTIGUOUS_ALLOWED and generated_overlap <= MAX_CHAR_NGRAM_OVERLAP
    )
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_rhetoric_overlap_report",
        "protocol": {
            "normalization": "移除空白、标点、数字和行内公式后按字符比较",
            "char_ngram_n": CHAR_N,
            "max_contiguous_allowed": MAX_CONTIGUOUS_ALLOWED,
            "max_char_ngram_overlap": MAX_CHAR_NGRAM_OVERLAP,
            "distinctive_min_length": DISTINCTIVE_MIN_LENGTH,
            "automatic_result_is_not_human_attestation": True,
        },
        "source": {
            "path": str(source_path.resolve()),
            "sha256": sha256_file(source_path),
        },
        "generated_text": {
            "path": str(generated_path.resolve()),
            "sha256": sha256_file(generated_path),
            "longest_contiguous_match": generated_length,
            "char_ngram_overlap": round(generated_overlap, 6),
            "highest_match": {
                "normalized_text": generated_fragment,
                "generated_normalized_start": generated_start,
                "source_normalized_start": generated_source_start,
                "generated_line": generated_lines[generated_start]
                if generated_start >= 0
                else None,
                "source_line": source_lines[generated_source_start]
                if generated_source_start >= 0
                else None,
            },
            "automatic_status": "passed" if generated_passed else "failed",
        },
        "status": "automatic_passed"
        if generated_passed and all(item["automatic_status"] == "passed" for item in results)
        else "automatic_failed",
        "human_review_status": "pending",
        "cards": results,
    }
    validate_schema(payload, "paper_rhetoric_overlap_report.schema.json")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="检查表达卡片与来源论文的高辨识度文本重合")
    parser.add_argument("--card-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = check_overlap(args.card_dir, args.source, args.generated)
    write_json(args.output, report)
    return 0 if report["status"] == "automatic_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
