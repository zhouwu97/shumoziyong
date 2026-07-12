"""Collector 的输入白名单与物理隔离准备；不读取 Candidate 目录。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any


ALLOWED_ROOTS = {"execution_spec.json", "model_route_v2.json", "environment_lock.json", "workspace", "materials", "contracts"}
FORBIDDEN_NAMES = {"candidate", "candidate_execution_record.json", "candidate_execution_logs", "formal_results", "paper"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_links_and_forbidden(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"白名单输入禁止符号链接或 junction：{path}")
        if any(part.lower() in FORBIDDEN_NAMES for part in path.relative_to(root).parts):
            raise ValueError(f"Collector 白名单包含 Candidate 或正式输出路径：{path}")


def prepare_isolated_run(source_root: Path, collector_root: Path) -> tuple[Path, dict[str, str]]:
    """新建空 Collector 目录，只复制审批过的输入并返回复制后哈希。"""
    source_root = source_root.resolve()
    collector_root = collector_root.resolve()
    if source_root == collector_root or source_root in collector_root.parents:
        raise ValueError("Collector 输出目录不得位于输入目录内")
    unexpected = {path.name for path in source_root.iterdir()} - ALLOWED_ROOTS
    if unexpected:
        raise ValueError(f"Collector 输入目录含未声明项目：{sorted(unexpected)}")
    required = {"execution_spec.json", "model_route_v2.json", "environment_lock.json", "workspace", "materials"}
    missing = [name for name in sorted(required) if not (source_root / name).exists()]
    if missing:
        raise ValueError(f"Collector 缺少白名单输入：{missing}")
    _reject_links_and_forbidden(source_root)
    target = collector_root / f"collector-{uuid.uuid4().hex}"
    target.mkdir(parents=True, exist_ok=False)
    hashes: dict[str, str] = {}
    for name in sorted(ALLOWED_ROOTS & {path.name for path in source_root.iterdir()}):
        source = source_root / name
        destination = target / name
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=False)
            for file in sorted(path for path in destination.rglob("*") if path.is_file()):
                hashes[file.relative_to(target).as_posix()] = _sha256(file)
        else:
            shutil.copy2(source, destination)
            hashes[name] = _sha256(destination)
    for path, expected in hashes.items():
        if _sha256(target / path) != expected:
            raise ValueError(f"Collector 复制后哈希不一致：{path}")
        os.chmod(target / path, 0o444)
    (target / "workspace" / "output").mkdir()
    (target / "manifest.json").write_text(json.dumps({"input_hashes": hashes}, ensure_ascii=False), encoding="utf-8")
    return target, hashes
