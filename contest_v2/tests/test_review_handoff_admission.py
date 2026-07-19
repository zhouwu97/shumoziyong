from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "examples" / "2024_C" / "build_review_handoff.py"
SPEC = importlib.util.spec_from_file_location("build_review_handoff", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_admission(run_dir: Path, *, status: str, paper_type: str, digest: str) -> None:
    path = run_dir / "review" / "paper_admission.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "paper_admission": status,
                "paper_type": paper_type,
                "pdf_sha256": f"sha256:{digest}",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_rejects_failed_admission(tmp_path: Path) -> None:
    paper = tmp_path / "paper" / "submission.pdf"
    paper.parent.mkdir(parents=True)
    paper.write_bytes(b"pdf")
    write_admission(tmp_path, status="fail", paper_type="technical_report", digest=MODULE.sha256(paper))

    with pytest.raises(ValueError, match="Paper Admission 未通过"):
        MODULE.require_current_paper_admission(tmp_path, paper)


def test_rejects_stale_admission(tmp_path: Path) -> None:
    paper = tmp_path / "paper" / "submission.pdf"
    paper.parent.mkdir(parents=True)
    paper.write_bytes(b"current pdf")
    write_admission(tmp_path, status="pass", paper_type="submission_candidate", digest="0" * 64)

    with pytest.raises(ValueError, match="已过期"):
        MODULE.require_current_paper_admission(tmp_path, paper)


def test_accepts_current_submission_candidate(tmp_path: Path) -> None:
    paper = tmp_path / "paper" / "submission.pdf"
    paper.parent.mkdir(parents=True)
    paper.write_bytes(b"current pdf")
    digest = MODULE.sha256(paper)
    write_admission(tmp_path, status="pass", paper_type="submission_candidate", digest=digest)

    admission = MODULE.require_current_paper_admission(tmp_path, paper)

    assert admission["paper_admission"] == "pass"
    assert admission["pdf_sha256"] == f"sha256:{digest}"
