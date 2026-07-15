from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except (ImportError, OSError):
        return None, None


def rasterize_with_pdftoppm(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    executable = shutil.which("pdftoppm")
    if not executable:
        return []
    prefix = output_dir / "page"
    completed = subprocess.run(
        [executable, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        # Windows 上某些命令包装器只在宿主进程中有效，此时交给 PyMuPDF 回退。
        return []
    return sorted(output_dir.glob("page-*.png"))


def rasterize_with_pymupdf(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("未找到 pdftoppm，且 PyMuPDF 不可用") from exc

    document = fitz.open(pdf_path)
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    pages: list[Path] = []
    try:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            index = page_index + 1
            target = output_dir / f"page-{index:03d}.png"
            page.get_pixmap(matrix=matrix, alpha=False).save(target)
            pages.append(target)
    finally:
        document.close()
    return pages


def rasterize_pdf(pdf_path: Path, output_dir: Path, dpi: int = 160) -> dict[str, Any]:
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise ValueError(f"PDF 不存在或为空: {pdf_path}")
    if dpi < 72 or dpi > 600:
        raise ValueError("DPI 必须在 72 到 600 之间")

    output_dir.mkdir(parents=True, exist_ok=True)
    for old_page in output_dir.glob("page-*.png"):
        old_page.unlink()

    pages = rasterize_with_pdftoppm(pdf_path, output_dir, dpi)
    engine = "pdftoppm"
    if not pages:
        pages = rasterize_with_pymupdf(pdf_path, output_dir, dpi)
        engine = "pymupdf"
    if not pages:
        raise RuntimeError("PDF 没有导出任何页面")

    page_records = []
    for index, page in enumerate(pages, start=1):
        width, height = image_dimensions(page)
        page_records.append(
            {
                "page": index,
                "file": str(page.resolve()),
                "sha256": sha256_file(page),
                "width_px": width,
                "height_px": height,
            }
        )

    return {
        "schema_version": "1.0.0",
        "pdf": str(pdf_path.resolve()),
        "pdf_sha256": sha256_file(pdf_path),
        "dpi": dpi,
        "engine": engine,
        "page_count": len(page_records),
        "pages": page_records,
        "visual_review_required": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将 PDF 每页导出为 PNG 并记录 SHA-256")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--dpi", type=int, default=160)
    parser.add_argument("--output", type=Path, default=Path("rasterize_report.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = rasterize_pdf(args.pdf, args.output_dir, args.dpi)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"page_count": report["page_count"], "engine": report["engine"]}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
