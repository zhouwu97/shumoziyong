"""Paper Reader Docker 隔离执行器的命令构造回归测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import paper_reader_executor  # noqa: E402


def _workspace(tmp_path: Path) -> Path:
    """创建执行器所需的最小只读输入包。"""
    workspace = tmp_path / "reader-workspace"
    workspace.mkdir()
    allowlist = [
        "problem_statement.pdf",
        "submission_paper.pdf",
        "review_contract.json",
        "review_prompt.txt",
    ]
    for name in allowlist:
        (workspace / name).write_bytes(name.encode("utf-8"))
    (workspace / "workspace_manifest.json").write_text(
        json.dumps({"allowlist": allowlist}, ensure_ascii=False), encoding="utf-8"
    )
    return workspace


def test_executor_overrides_image_entrypoint(monkeypatch, tmp_path: Path) -> None:
    """审核命令必须替换服务镜像的默认 ENTRYPOINT。"""
    workspace = _workspace(tmp_path)
    captured: list[str] = []

    monkeypatch.setattr(paper_reader_executor, "_image_id", lambda _image: "sha256:test")

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured.extend(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"review complete", stderr=b"")

    monkeypatch.setattr(paper_reader_executor.subprocess, "run", fake_run)
    output = tmp_path / "attestations" / "reader.json"
    result = paper_reader_executor.execute_reader_workspace(
        workspace,
        image="example/service-image:latest",
        command=["/opt/reader/bin/review", "--input", "/review"],
        output=output,
    )

    image_index = captured.index("example/service-image:latest")
    assert captured[image_index - 2 : image_index] == ["--entrypoint", "/opt/reader/bin/review"]
    assert captured[image_index + 1 :] == ["--input", "/review"]
    assert result["entrypoint"] == "/opt/reader/bin/review"
    assert result["isolation_status"] == "workspace_enforced"
