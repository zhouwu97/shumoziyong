from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


PLACEHOLDER_RULES = {
    "TODO": "todo",
    "PLACEHOLDER": "placeholder",
    "待补充": "chinese_placeholder",
    "待续写": "chinese_placeholder",
    "示例数据": "example_data_placeholder",
}

INTERNAL_RULES = {
    "results/": "internal_results_path",
    "training/": "internal_training_path",
    ".json": "internal_json_name",
    "run_workflow.py": "internal_workflow_script",
}

AI_WARNING_PHRASES = (
    "综上所述",
    "值得注意的是",
    "结果表明",
    "有效验证",
    "具有一定的推广价值",
    "提供科学依据",
)

INCLUDE_PATTERN = re.compile(r'#include\s*[\( ]\s*["\']([^"\']+)["\']')
IMAGE_PATTERN = re.compile(r'image\s*\(\s*["\']([^"\']+)["\']')
EQUATION_LABEL_PATTERN = re.compile(r"<(?P<label>eq[-_:][A-Za-z0-9_.:-]+)>")
EQUATION_REF_PATTERN = re.compile(r"@(?P<label>eq[-_:][A-Za-z0-9_.:-]+)")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    path: Path,
    line: int | None = None,
) -> None:
    item: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
        "file": str(path.resolve()),
    }
    if line is not None:
        item["line"] = line
    issues.append(item)


def line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def strip_comments(text: str, suffix: str) -> str:
    if suffix == ".typ":
        return re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    return re.sub(r"%.*?$", "", text, flags=re.MULTILINE)


def collect_sources(main_path: Path) -> list[Path]:
    """只跟随正文 include，避免把样式组件当成论文内容扫描。"""
    discovered: list[Path] = []
    queue = [main_path.resolve()]
    seen: set[Path] = set()
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        discovered.append(path)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for relative in INCLUDE_PATTERN.findall(text):
            child = (path.parent / relative).resolve()
            if child not in seen:
                queue.append(child)
    return discovered


def iter_balanced_calls(text: str, marker: str) -> Iterable[tuple[int, str]]:
    start = 0
    while True:
        marker_pos = text.find(marker, start)
        if marker_pos < 0:
            return
        open_pos = text.find("(", marker_pos + len(marker))
        if open_pos < 0:
            return
        depth = 0
        quote: str | None = None
        escaped = False
        for pos in range(open_pos, len(text)):
            char = text[pos]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    yield marker_pos, text[marker_pos : pos + 1]
                    start = pos + 1
                    break
        else:
            yield marker_pos, text[marker_pos:]
            return


def scan_placeholders(path: Path, text: str, issues: list[dict[str, Any]]) -> None:
    for token, code in PLACEHOLDER_RULES.items():
        for match in re.finditer(re.escape(token), text, flags=re.IGNORECASE):
            add_issue(
                issues, "FAIL", code, f"发现占位符: {token}", path, line_number(text, match.start())
            )


def scan_internal_names(path: Path, text: str, issues: list[dict[str, Any]]) -> None:
    normalized = text.replace("\\", "/")
    for token, code in INTERNAL_RULES.items():
        for match in re.finditer(re.escape(token), normalized, flags=re.IGNORECASE):
            add_issue(
                issues,
                "FAIL",
                code,
                f"正文泄露内部名称或路径: {token}",
                path,
                line_number(normalized, match.start()),
            )
    for match in re.finditer(r"\bGate\s*[345]\b|\bA092\b", text, flags=re.IGNORECASE):
        add_issue(
            issues,
            "FAIL",
            "internal_gate_name",
            f"正文泄露内部 Gate 或任务名称: {match.group(0)}",
            path,
            line_number(text, match.start()),
        )


def scan_images(path: Path, text: str, issues: list[dict[str, Any]]) -> None:
    for match in IMAGE_PATTERN.finditer(text):
        image_path = (path.parent / match.group(1)).resolve()
        if not image_path.is_file():
            add_issue(
                issues,
                "FAIL",
                "missing_image",
                f"引用图片不存在: {image_path}",
                path,
                line_number(text, match.start()),
            )


def scan_captions(path: Path, text: str, issues: list[dict[str, Any]]) -> None:
    native_figure_calls = list(iter_balanced_calls(text, "#figure"))
    custom_figure_calls = list(iter_balanced_calls(text, "#paper-figure"))
    for position, call in native_figure_calls:
        if "caption:" not in call:
            add_issue(
                issues,
                "FAIL",
                "missing_figure_caption",
                "图缺少 caption",
                path,
                line_number(text, position),
            )

    for position, call in custom_figure_calls:
        if "caption:" not in call and call.count(",") < 2:
            add_issue(
                issues,
                "FAIL",
                "missing_figure_caption",
                "paper-figure 缺少第二个图题参数",
                path,
                line_number(text, position),
            )
        if re.search(r"text\s*\([^)]*size\s*:\s*(?:1[5-9]|[2-9]\d)(?:\.\d+)?pt", call):
            add_issue(
                issues,
                "WARN",
                "large_title_inside_figure",
                "图内存在 15pt 以上文字，可能与正文图题重复",
                path,
                line_number(text, position),
            )

    custom_tables = list(iter_balanced_calls(text, "#three-line-table"))
    for position, call in custom_tables:
        prefix = call.split(",", 1)[0]
        if "[" not in prefix or "]" not in prefix:
            add_issue(
                issues,
                "FAIL",
                "missing_table_caption",
                "三线表第一个参数必须是非空表题",
                path,
                line_number(text, position),
            )

    for position, call in iter_balanced_calls(text, "#table"):
        context = text[max(0, position - 120) : position]
        if "figure(" not in context and "caption:" not in call:
            add_issue(
                issues,
                "FAIL",
                "missing_table_caption",
                "直接使用的表格缺少表题包装",
                path,
                line_number(text, position),
            )

    ordered = sorted(
        (position, call) for position, call in native_figure_calls + custom_figure_calls
    )
    for (left_pos, left_call), (right_pos, _) in zip(ordered, ordered[1:]):
        middle = strip_comments(text[left_pos + len(left_call) : right_pos], path.suffix)
        middle = re.sub(r"[#\s\[\]{}()]", "", middle)
        if len(middle) < 40:
            add_issue(
                issues,
                "WARN",
                "consecutive_figures_without_explanation",
                "连续图表之间解释文字不足",
                path,
                line_number(text, right_pos),
            )


def scan_equation_references(sources: list[tuple[Path, str]], issues: list[dict[str, Any]]) -> None:
    labels: dict[str, tuple[Path, str, int]] = {}
    references: dict[str, tuple[Path, str, int]] = {}
    for path, text in sources:
        for match in EQUATION_LABEL_PATTERN.finditer(text):
            labels.setdefault(match.group("label"), (path, text, match.start()))
        for match in EQUATION_REF_PATTERN.finditer(text):
            references.setdefault(match.group("label"), (path, text, match.start()))

    for label in sorted(references.keys() - labels.keys()):
        path, text, position = references[label]
        add_issue(
            issues,
            "FAIL",
            "missing_equation_label",
            f"公式引用没有对应标签: {label}",
            path,
            line_number(text, position),
        )
    for label in sorted(labels.keys() - references.keys()):
        path, text, position = labels[label]
        add_issue(
            issues,
            "WARN",
            "unreferenced_equation",
            f"带编号公式未在正文引用: {label}",
            path,
            line_number(text, position),
        )


def scan_style_rules(path: Path, text: str, issues: list[dict[str, Any]]) -> None:
    heading_color = re.compile(
        r"(?:show|set)\s+heading[\s\S]{0,240}fill\s*:\s*([^,\)\]\n]+)",
        flags=re.IGNORECASE,
    )
    for match in heading_color.finditer(text):
        value = match.group(1).strip().lower().replace(" ", "")
        if value not in {"black", 'rgb("#000000")', "rgb(0,0,0)"}:
            add_issue(issues, "FAIL", "colored_heading", "发现非黑色章节标题设置", path)
            break
    for position, call in iter_balanced_calls(text, "#table"):
        if re.search(r"\bfill\s*:", call):
            add_issue(
                issues,
                "FAIL",
                "table_fill",
                "表格使用了底色",
                path,
                line_number(text, position),
            )


def scan_writing_warnings(path: Path, text: str, issues: list[dict[str, Any]]) -> None:
    for phrase in AI_WARNING_PHRASES:
        for match in re.finditer(re.escape(phrase), text):
            add_issue(
                issues,
                "WARN",
                "formulaic_phrase",
                f"可能模板化的表达: {phrase}",
                path,
                line_number(text, match.start()),
            )

    lines = text.splitlines()
    list_lines = [
        index
        for index, line in enumerate(lines, start=1)
        if re.match(r"^\s*(?:[-+]\s+|\d+[.)]\s+|#(?:list|enum)\b)", line)
    ]
    consecutive = 1
    max_consecutive = 0
    for left, right in zip(list_lines, list_lines[1:]):
        consecutive = consecutive + 1 if right == left + 1 else 1
        max_consecutive = max(max_consecutive, consecutive)
    if max_consecutive >= 5 or (lines and len(list_lines) / len(lines) > 0.35):
        add_issue(issues, "WARN", "over_listed", "正文可能过度列表化", path)


def check_paper_source(main_path: Path) -> dict[str, Any]:
    sources = collect_sources(main_path)
    issues: list[dict[str, Any]] = []
    readable_sources: list[Path] = []
    scanned_sources: list[tuple[Path, str]] = []

    for path in sources:
        if not path.is_file():
            add_issue(issues, "FAIL", "missing_include", f"include 文件不存在: {path}", main_path)
            continue
        readable_sources.append(path)
        text = strip_comments(path.read_text(encoding="utf-8"), path.suffix)
        scanned_sources.append((path, text))
        scan_placeholders(path, text, issues)
        scan_internal_names(path, text, issues)
        scan_images(path, text, issues)
        scan_captions(path, text, issues)
        scan_style_rules(path, text, issues)
        scan_writing_warnings(path, text, issues)

    scan_equation_references(scanned_sources, issues)
    for style_path in main_path.parent.rglob("*.typ"):
        resolved = style_path.resolve()
        if resolved in readable_sources:
            continue
        text = strip_comments(resolved.read_text(encoding="utf-8"), resolved.suffix)
        scan_style_rules(resolved, text, issues)

    failures = [item for item in issues if item["severity"] == "FAIL"]
    warnings = [item for item in issues if item["severity"] == "WARN"]
    return {
        "schema_version": "1.0.0",
        "passed": not failures,
        "main": str(main_path.resolve()),
        "main_sha256": sha256_file(main_path) if main_path.is_file() else None,
        "sources": [
            {"path": str(path.resolve()), "sha256": sha256_file(path)} for path in readable_sources
        ],
        "summary": {
            "files_checked": len(readable_sources),
            "failures": len(failures),
            "warnings": len(warnings),
        },
        "issues": issues,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查 Typst 论文源文件中的结构与文本问题")
    parser.add_argument("--main", type=Path, required=True, help="论文 main.typ")
    parser.add_argument("--output", type=Path, default=Path("paper_source_check.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = check_paper_source(args.main)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
