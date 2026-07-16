from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_SCRIPT_PATH = "skills/6verity/scripts/writing_check.sh"
PLACEHOLDER_RE = re.compile(r"PLACEHOLDER|TODO|TBD|XXX|待补充|待续写|这里补|示例数据|待完善")
INTERNAL_TERMS = (
    "RESULTS_REPORT",
    "ANALYSIS_MODELING_REPORT.md",
    "PROBLEM_ANALYSIS.md",
    "CLAUDE.md",
    "figures/*.json",
    "_tmp/",
    ".vendor/",
    "runtime_contracts/",
)


class ExternalPrecheckError(ValueError):
    """只读外部兼容预检无法可靠完成。"""


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} 不存在：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ExternalPrecheckError(f"{label} 必须是 JSON 对象：{path}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _paper_files(paper_root: Path) -> list[Path]:
    files = sorted(
        path
        for path in paper_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".typ", ".tex"}
    )
    if not files:
        raise ExternalPrecheckError("论文目录中没有 .typ 或 .tex 正文文件")
    return files


def snapshot_body(paper_root: Path) -> dict[str, Any]:
    records = [
        {
            "path": path.relative_to(paper_root).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in _paper_files(paper_root)
    ]
    canonical = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "file_count": len(records),
        "files": records,
    }


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _balanced_typst_calls(text: str, name: str) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    for match in re.finditer(r"#" + re.escape(name) + r"\s*\(", text):
        open_position = text.find("(", match.start())
        depth = 0
        in_string = False
        escaped = False
        for index in range(open_position, len(text)):
            character = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    calls.append((match.start(), text[open_position + 1 : index]))
                    break
    return calls


def _finding(
    findings: list[dict[str, Any]],
    *,
    code: str,
    severity: str,
    path: str,
    line: int,
    message: str,
) -> None:
    findings.append(
        {
            "code": code,
            "severity": severity,
            "path": path,
            "line": line,
            "message": message,
            "repair_id": "",
        }
    )


def scan_paper(paper_root: Path, extra_internal_terms: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    internal_terms = tuple(dict.fromkeys((*INTERNAL_TERMS, *extra_internal_terms)))
    for path in _paper_files(paper_root):
        relative = path.relative_to(paper_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), 1):
            if PLACEHOLDER_RE.search(line):
                _finding(
                    findings,
                    code="placeholder_text",
                    severity="blocking",
                    path=relative,
                    line=line_number,
                    message="正文仍包含占位文本",
                )
            for term in internal_terms:
                if term in line:
                    _finding(
                        findings,
                        code="internal_term_leak",
                        severity="blocking",
                        path=relative,
                        line=line_number,
                        message=f"正文泄漏内部术语：{term}",
                    )

        if path.suffix.lower() == ".typ":
            for match in re.finditer(r'image\(\s*"([^"]+)"', text):
                reference = match.group(1)
                if not (path.parent / reference).resolve().is_file():
                    _finding(
                        findings,
                        code="missing_image",
                        severity="blocking",
                        path=relative,
                        line=_line_number(text, match.start()),
                        message=f"图片引用不存在：{reference}",
                    )
            for offset, body in _balanced_typst_calls(text, "figure"):
                if "caption:" not in body:
                    _finding(
                        findings,
                        code="missing_figure_caption",
                        severity="blocking",
                        path=relative,
                        line=_line_number(text, offset),
                        message="Typst figure 缺少 caption",
                    )
        else:
            for match in re.finditer(
                r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", text
            ):
                reference = match.group(1)
                if not (path.parent / reference).resolve().is_file():
                    _finding(
                        findings,
                        code="missing_image",
                        severity="blocking",
                        path=relative,
                        line=_line_number(text, match.start()),
                        message=f"图片引用不存在：{reference}",
                    )
            for match in re.finditer(r"\\begin\{figure\}.*?\\end\{figure\}", text, re.DOTALL):
                if not re.search(r"\\caption\s*\{", match.group(0)):
                    _finding(
                        findings,
                        code="missing_figure_caption",
                        severity="blocking",
                        path=relative,
                        line=_line_number(text, match.start()),
                        message="LaTeX figure 缺少 caption",
                    )

    findings.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["code"])))
    for index, item in enumerate(findings, 1):
        item["repair_id"] = f"repair_{index:04d}"
    return findings


def _upstream_source() -> dict[str, Any]:
    lock = load_json_object(ROOT / "UPSTREAM.lock.json", "上游锁")
    manifest = load_json_object(
        ROOT / "upstream" / "mathmodelagent.sha256.json",
        "上游文件哈希清单",
    )
    matches = [
        record
        for record in manifest.get("files", [])
        if isinstance(record, dict) and record.get("path") == UPSTREAM_SCRIPT_PATH
    ]
    if len(matches) != 1:
        raise ExternalPrecheckError("上游写作检查脚本必须在哈希清单中唯一存在")
    return {
        "repository": lock["repository"]["url"],
        "commit": lock["repository"]["commit"],
        "path": UPSTREAM_SCRIPT_PATH,
        "sha256": matches[0]["sha256"],
        "executed": False,
    }


def _repair_suggestion(finding: dict[str, Any]) -> str:
    suggestions = {
        "placeholder_text": "用当前 Run 的已验证内容替换占位文本，并重新执行本预检。",
        "internal_term_leak": "改写为面向评审者的学术表述，删除仓库或工作流内部术语。",
        "missing_image": "修正相对路径或补齐已登记图件，不得生成虚构图件。",
        "missing_figure_caption": "补充与图中证据一致的图注。",
        "paper_body_mutated": "恢复预检开始时的正文，或在修改后重新启动一次完整预检。",
    }
    return suggestions[str(finding["code"])]


def run_external_precheck(
    *,
    paper_root: Path,
    report_path: Path,
    suggestions_path: Path,
    extra_internal_terms: tuple[str, ...] = (),
) -> dict[str, Any]:
    """执行本仓只读重实现；绝不运行或修改上游 Skill。"""
    paper_root = paper_root.resolve()
    before = snapshot_body(paper_root)
    findings = scan_paper(paper_root, extra_internal_terms)
    after = snapshot_body(paper_root)
    mutation_detected = before != after
    if mutation_detected:
        first_path = str(before["files"][0]["path"])
        _finding(
            findings,
            code="paper_body_mutated",
            severity="blocking",
            path=first_path,
            line=1,
            message="预检期间正文哈希发生变化",
        )
        findings.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["code"])))
        for index, item in enumerate(findings, 1):
            item["repair_id"] = f"repair_{index:04d}"

    repairs = {
        "schema_version": "suggested_repairs_v1",
        "paper_body_sha256": str(before["sha256"]),
        "automatic_apply": False,
        "repairs": [
            {
                "repair_id": finding["repair_id"],
                "finding_code": finding["code"],
                "path": finding["path"],
                "line": finding["line"],
                "suggestion": _repair_suggestion(finding),
            }
            for finding in findings
        ],
    }
    repairs_schema = load_json_object(
        ROOT / "schemas" / "suggested_repairs.schema.json",
        "建议修复 Schema",
    )
    Draft202012Validator(repairs_schema).validate(repairs)
    write_json(suggestions_path, repairs)

    status = "mutation_detected" if mutation_detected else ("issues_found" if findings else "passed")
    report = {
        "schema_version": "paper_external_precheck_report_v1",
        "adapter_id": "native_writing_check_adapter_v1",
        "upstream_source": _upstream_source(),
        "paper_root": str(paper_root),
        "body_before": before,
        "body_after": after,
        "mutation_detected": mutation_detected,
        "status": status,
        "authority": {
            "modify_paper": False,
            "rerun_results": False,
            "decide_gate4_pass": False,
        },
        "findings": findings,
        "suggested_repairs": {
            "path": suggestions_path.name,
            "sha256": sha256_file(suggestions_path),
            "automatic_apply": False,
        },
    }
    report_schema = load_json_object(
        ROOT / "schemas" / "paper_external_precheck_report.schema.json",
        "论文外部兼容预检 Schema",
    )
    Draft202012Validator(report_schema).validate(report)
    write_json(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行只读论文外部兼容预检")
    parser.add_argument("--paper-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--suggestions", type=Path, required=True)
    parser.add_argument("--internal-term", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_external_precheck(
        paper_root=args.paper_root,
        report_path=args.report,
        suggestions_path=args.suggestions,
        extra_internal_terms=tuple(args.internal_term),
    )
    print(
        json.dumps(
            {"status": report["status"], "findings": len(report["findings"])},
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
