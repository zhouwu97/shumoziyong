from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

import render_submission as renderer  # noqa: E402


PROFILE = ROOT / "paper_profiles" / "cumcm_academic_v1.json"
TEMPLATE = ROOT / "paper_templates" / "cumcm_typst"


def fake_compile(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    output_pdf = Path(command[-1])
    output_pdf.write_bytes(b"%PDF-1.7\nproject-test\n%%EOF\n")
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_render_submission_writes_bound_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.typ").write_text(
        '#import "style.typ": apply-cumcm-style\n#show: apply-cumcm-style\n= 测试正文\n',
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts"
    output_pdf = artifacts / "submission.pdf"
    attestation_path = artifacts / "paper_render_attestation.json"
    monkeypatch.setattr(renderer, "renderer_version", lambda _: "typst 0.13.1")
    monkeypatch.setattr(renderer.subprocess, "run", fake_compile)

    attestation = renderer.render_submission(
        profile_path=PROFILE,
        template_dir=TEMPLATE,
        source_dir=source_dir,
        source_entry=Path("main.typ"),
        output_pdf=output_pdf,
        attestation_path=attestation_path,
    )

    schema = json.loads(
        (ROOT / "schemas/paper_render_attestation.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(attestation)
    assert attestation["compiled"] is True
    assert attestation["output_pdf"] == "submission.pdf"
    assert output_pdf.is_file()
    assert (artifacts / "paper_source_manifest.json").is_file()
    assert (artifacts / "paper_profile.snapshot.json").is_file()
    assert (artifacts / "paper_template_manifest.json").is_file()
    assert json.loads(attestation_path.read_text(encoding="utf-8")) == attestation


def test_render_submission_fails_closed_on_compile_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.typ").write_text("= 正文\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "renderer_version", lambda _: "typst 0.13.1")
    monkeypatch.setattr(
        renderer.subprocess,
        "run",
        lambda command, **_: subprocess.CompletedProcess(command, 1, stdout="", stderr="bad"),
    )
    attestation_path = tmp_path / "artifacts/paper_render_attestation.json"

    with pytest.raises(RuntimeError, match="submission 编译失败"):
        renderer.render_submission(
            profile_path=PROFILE,
            template_dir=TEMPLATE,
            source_dir=source_dir,
            source_entry=Path("main.typ"),
            output_pdf=tmp_path / "artifacts/submission.pdf",
            attestation_path=attestation_path,
        )

    assert not attestation_path.exists()


def test_source_cannot_override_protected_template_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.typ").write_text("= 正文\n", encoding="utf-8")
    (source_dir / "style.typ").write_text("#set text(fill: red)\n", encoding="utf-8")
    monkeypatch.setattr(renderer, "renderer_version", lambda _: "typst 0.13.1")

    with pytest.raises(ValueError, match="不得覆盖批准模板受保护文件"):
        renderer.render_submission(
            profile_path=PROFILE,
            template_dir=TEMPLATE,
            source_dir=source_dir,
            source_entry=Path("main.typ"),
            output_pdf=tmp_path / "artifacts/submission.pdf",
            attestation_path=tmp_path / "artifacts/paper_render_attestation.json",
        )
