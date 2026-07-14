from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from check_pdf_metadata import check_pdf_metadata  # noqa: E402
from rasterize_pdf import rasterize_pdf  # noqa: E402


def create_text_pdf(path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page(width=595.276, height=841.89)
    page.insert_text((72, 72), "CUMCM paper toolkit test")
    document.save(path)
    document.close()


def test_rasterize_and_metadata_check_cover_all_pages(tmp_path: Path) -> None:
    pdf = tmp_path / "sample.pdf"
    pages_dir = tmp_path / "pages"
    create_text_pdf(pdf)

    raster_report = rasterize_pdf(pdf, pages_dir, dpi=100)
    metadata_report = check_pdf_metadata(pdf, pages_dir)

    assert raster_report["page_count"] == 1
    assert len(raster_report["pages"][0]["sha256"]) == 64
    assert metadata_report["passed"] is True
    assert metadata_report["page_count"] == 1
    assert metadata_report["visual_review_required"] is True


def test_metadata_check_detects_missing_page_exports(tmp_path: Path) -> None:
    pdf = tmp_path / "sample.pdf"
    pages_dir = tmp_path / "empty-pages"
    pages_dir.mkdir()
    create_text_pdf(pdf)

    report = check_pdf_metadata(pdf, pages_dir)

    assert report["passed"] is False
    assert any(issue["code"] == "incomplete_page_export" for issue in report["issues"])
