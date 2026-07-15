from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.89


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_is_blank(page: Any) -> bool | None:
    """低分辨率渲染检测近似空白页；不可用时返回 None。"""
    try:
        import fitz

        pixmap = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
    except (ImportError, RuntimeError):
        return None
    samples = pixmap.samples
    if not samples:
        return True
    dark = sum(1 for value in samples if value < 245)
    return dark / len(samples) < 0.0005


def inspect_with_pymupdf(pdf_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("检查 PDF 元数据需要 PyMuPDF") from exc

    document = fitz.open(pdf_path)
    pages: list[dict[str, Any]] = []
    fonts: set[str] = set()
    try:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            index = page_index + 1
            rectangle = page.rect
            page_text = page.get_text("text")
            for font in page.get_fonts(full=True):
                if len(font) > 3 and font[3]:
                    fonts.add(str(font[3]))
            pages.append(
                {
                    "page": index,
                    "width_pt": round(rectangle.width, 3),
                    "height_pt": round(rectangle.height, 3),
                    "rotation": page.rotation,
                    "blank": page_is_blank(page),
                    "text_characters": len(page_text.strip()) if isinstance(page_text, str) else 0,
                }
            )
    finally:
        document.close()
    return pages, sorted(fonts)


def is_a4(width: float, height: float, tolerance: float = 3.0) -> bool:
    direct = math.isclose(width, A4_WIDTH_PT, abs_tol=tolerance) and math.isclose(
        height, A4_HEIGHT_PT, abs_tol=tolerance
    )
    rotated = math.isclose(height, A4_WIDTH_PT, abs_tol=tolerance) and math.isclose(
        width, A4_HEIGHT_PT, abs_tol=tolerance
    )
    return direct or rotated


def check_pdf_metadata(pdf_path: Path, pages_dir: Path | None = None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        return {
            "schema_version": "1.0.0",
            "passed": False,
            "pdf": str(pdf_path.resolve()),
            "issues": [{"severity": "FAIL", "code": "empty_pdf", "message": "PDF 不存在或为空"}],
        }

    try:
        pages, fonts = inspect_with_pymupdf(pdf_path)
    except (RuntimeError, ValueError) as exc:
        return {
            "schema_version": "1.0.0",
            "passed": False,
            "pdf": str(pdf_path.resolve()),
            "pdf_sha256": sha256_file(pdf_path),
            "issues": [{"severity": "FAIL", "code": "unreadable_pdf", "message": str(exc)}],
        }

    if not pages:
        issues.append({"severity": "FAIL", "code": "no_pages", "message": "PDF 没有页面"})
    for page in pages:
        if not is_a4(float(page["width_pt"]), float(page["height_pt"])):
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "unexpected_page_size",
                    "page": page["page"],
                    "message": f"页面尺寸异常: {page['width_pt']} x {page['height_pt']} pt",
                }
            )
        if page["blank"] is True:
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "blank_page",
                    "page": page["page"],
                    "message": "检测到近似空白页",
                }
            )
        elif page["blank"] is None:
            issues.append(
                {
                    "severity": "WARN",
                    "code": "blank_check_not_run",
                    "page": page["page"],
                    "message": "无法执行空白页像素检查",
                }
            )

    if not fonts:
        issues.append(
            {"severity": "WARN", "code": "font_info_empty", "message": "未读取到字体信息"}
        )

    exported_pages: list[str] = []
    if pages_dir is not None:
        exported_pages = [str(path.resolve()) for path in sorted(pages_dir.glob("page-*.png"))]
        if len(exported_pages) != len(pages):
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "incomplete_page_export",
                    "message": f"PDF 共 {len(pages)} 页，但页面目录中有 {len(exported_pages)} 张 PNG",
                }
            )

    failures = [item for item in issues if item["severity"] == "FAIL"]
    warnings = [item for item in issues if item["severity"] == "WARN"]
    return {
        "schema_version": "1.0.0",
        "passed": not failures,
        "pdf": str(pdf_path.resolve()),
        "pdf_sha256": sha256_file(pdf_path),
        "file_size_bytes": pdf_path.stat().st_size,
        "page_count": len(pages),
        "pages": pages,
        "fonts": fonts,
        "exported_pages": exported_pages,
        "summary": {"failures": len(failures), "warnings": len(warnings)},
        "issues": issues,
        "visual_review_required": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查 PDF 页数、页面尺寸、空白页和字体信息")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("pdf_metadata_check.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = check_pdf_metadata(args.pdf, args.pages_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report.get("summary", {"failures": 1}), ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
