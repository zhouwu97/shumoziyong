"""同步并校验固定版本的 MathModelAgent 只读 Source Asset。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "UPSTREAM.lock.json"
MANIFEST_PATH = ROOT / "upstream" / "mathmodelagent.sha256.json"
VENDOR_PATH = ROOT / ".vendor" / "mathmodelagent"

PINNED_REPOSITORY = "https://github.com/jihe520/MathModelAgent.git"
PINNED_COMMIT = "be9c59c1aaa13c3dcb74452ea5cae11dada27589"
PINNED_LICENSE_PATH = "docs/md/License.md"
PINNED_LICENSE_SHA256 = (
    "138ed0a8abfa574b8c8b19fd53b18bb3c2854015f54cc24ce8f1952b82eab39d"
)
PINNED_MANIFEST_SHA256 = (
    "38a58dbbf1d0d2957ba446631d309241b4149cc9f418d27bad5efc46f0e5f07b"
)
PINNED_ALLOWED_PATHS: tuple[tuple[str, str, str], ...] = (
    ("docs/md/License.md", "blob", "756b0138f66897d34af884d4f84a11bcecb47b84"),
    ("skills/3coding-visual", "tree", "d7221ec92b56ab6f700a8e0a57c57847c78affb8"),
    ("skills/4drawio", "tree", "a5302d9dfa221fb554bb41d5f5fd80f7d80150cc"),
    ("skills/5writing", "tree", "20b8645b9eacc8ac789a753c382c0b14186e049b"),
    ("skills/6verity", "tree", "d643ff71fca23ab45b7b51d063468704c50f7492"),
    (
        "skills/_references/math_modeling_norms.md",
        "blob",
        "051276b8ebbe7c5ad5dc7b4903724715ff6a63e4",
    ),
)


class UpstreamIntegrityError(RuntimeError):
    """上游来源、锁或已物化文件不满足固定约束。"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json_object(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpstreamIntegrityError(f"JSON 无法解析：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpstreamIntegrityError(f"JSON 顶层必须是对象：{path}")
    return value, raw


def _expected_allowed_paths() -> list[dict[str, str]]:
    return [
        {"path": path, "object_type": object_type, "git_object": git_object}
        for path, object_type, git_object in PINNED_ALLOWED_PATHS
    ]


def _is_allowed_file(path: str) -> bool:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        return False
    for allowed, object_type, _git_object in PINNED_ALLOWED_PATHS:
        allowed_path = PurePosixPath(allowed)
        if object_type == "blob" and candidate == allowed_path:
            return True
        if object_type == "tree" and candidate.is_relative_to(allowed_path):
            return True
    return False


def validate_repository_metadata(
    lock: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_bytes: bytes,
) -> None:
    """验证提交到本仓的锁与文件清单完全匹配代码内固定值。"""
    if set(lock) != {
        "schema_version",
        "repository",
        "vendor_path",
        "manifest_path",
        "manifest_sha256",
        "allowed_paths",
        "policy",
    }:
        raise UpstreamIntegrityError("锁文件字段集合不匹配")
    expected_repository = {
        "url": PINNED_REPOSITORY,
        "commit": PINNED_COMMIT,
        "license_path": PINNED_LICENSE_PATH,
        "license_sha256": PINNED_LICENSE_SHA256,
    }
    if lock.get("schema_version") != "mathmodelagent_upstream_lock_v1":
        raise UpstreamIntegrityError("锁文件 schema_version 不匹配")
    if lock.get("repository") != expected_repository:
        raise UpstreamIntegrityError("锁文件的仓库、提交或许可固定值不匹配")
    if lock.get("vendor_path") != ".vendor/mathmodelagent":
        raise UpstreamIntegrityError("锁文件 vendor_path 不匹配")
    if lock.get("manifest_path") != "upstream/mathmodelagent.sha256.json":
        raise UpstreamIntegrityError("锁文件 manifest_path 不匹配")
    if lock.get("manifest_sha256") != PINNED_MANIFEST_SHA256:
        raise UpstreamIntegrityError("锁文件 manifest_sha256 不匹配")
    if lock.get("allowed_paths") != _expected_allowed_paths():
        raise UpstreamIntegrityError("锁文件允许路径或 Git 对象不匹配")
    expected_policy = {
        "execute_upstream_content": False,
        "materialize_allowlist_only": True,
        "read_only_source_asset": True,
    }
    if lock.get("policy") != expected_policy:
        raise UpstreamIntegrityError("锁文件 Source Asset 策略不匹配")

    actual_manifest_hash = _sha256(manifest_bytes)
    if actual_manifest_hash != PINNED_MANIFEST_SHA256:
        raise UpstreamIntegrityError("文件哈希清单自身的 SHA-256 不匹配")
    if manifest.get("schema_version") != "mathmodelagent_file_manifest_v1":
        raise UpstreamIntegrityError("文件清单 schema_version 不匹配")
    if set(manifest) != {
        "schema_version",
        "repository_url",
        "commit",
        "file_count",
        "files",
    }:
        raise UpstreamIntegrityError("文件清单字段集合不匹配")
    if manifest.get("repository_url") != PINNED_REPOSITORY:
        raise UpstreamIntegrityError("文件清单远端不匹配")
    if manifest.get("commit") != PINNED_COMMIT:
        raise UpstreamIntegrityError("文件清单提交不匹配")

    files = manifest.get("files")
    if not isinstance(files, list) or manifest.get("file_count") != len(files):
        raise UpstreamIntegrityError("文件清单数量字段不匹配")
    seen: set[str] = set()
    previous = ""
    license_hash: str | None = None
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise UpstreamIntegrityError("文件清单条目结构不合法")
        path = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")
        if not isinstance(path, str) or not _is_allowed_file(path):
            raise UpstreamIntegrityError(f"文件清单包含未允许路径：{path!r}")
        if path in seen or path <= previous:
            raise UpstreamIntegrityError("文件清单路径必须严格排序且唯一")
        if not isinstance(size, int) or size < 0:
            raise UpstreamIntegrityError(f"文件大小不合法：{path}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise UpstreamIntegrityError(f"文件 SHA-256 不合法：{path}")
        seen.add(path)
        previous = path
        if path == PINNED_LICENSE_PATH:
            license_hash = digest
    if license_hash != PINNED_LICENSE_SHA256:
        raise UpstreamIntegrityError("文件清单中的许可哈希不匹配")


def load_and_validate_metadata() -> tuple[dict[str, Any], dict[str, Any]]:
    lock, _lock_bytes = _load_json_object(LOCK_PATH)
    manifest, manifest_bytes = _load_json_object(MANIFEST_PATH)
    validate_repository_metadata(lock, manifest, manifest_bytes)
    return lock, manifest


def _run_git(repository: Path, args: Sequence[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise UpstreamIntegrityError(f"无法启动 Git：{exc}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise UpstreamIntegrityError(f"Git 命令失败：{' '.join(args)}: {stderr}")
    return completed.stdout


def _fetch_pinned_repository(repository: Path) -> None:
    _run_git(repository, ["init", "--bare"])
    _run_git(repository, ["remote", "add", "origin", PINNED_REPOSITORY])
    remote = _run_git(repository, ["remote", "get-url", "origin"]).decode().strip()
    if remote != PINNED_REPOSITORY:
        raise UpstreamIntegrityError("临时仓库远端不匹配")
    _run_git(repository, ["fetch", "--depth=1", "origin", PINNED_COMMIT])
    fetched = _run_git(repository, ["rev-parse", "FETCH_HEAD"]).decode().strip()
    if fetched != PINNED_COMMIT:
        raise UpstreamIntegrityError("Git 实际获取的提交不匹配")
    object_type = _run_git(repository, ["cat-file", "-t", PINNED_COMMIT]).decode().strip()
    if object_type != "commit":
        raise UpstreamIntegrityError("固定对象不是 Git commit")


def _manifest_entries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise UpstreamIntegrityError("文件清单 files 不是数组")
    return [dict(entry) for entry in files]


def _read_commit_blob(repository: Path, path: str) -> bytes:
    return _run_git(repository, ["cat-file", "blob", f"{PINNED_COMMIT}:{path}"])


def build_manifest_from_local_git(repository: Path) -> dict[str, Any]:
    """从本地已校验仓库生成确定性清单；仅供维护锁文件时使用。"""
    head = _run_git(repository, ["rev-parse", "HEAD"]).decode().strip()
    if head != PINNED_COMMIT:
        raise UpstreamIntegrityError("本地维护仓库不在固定提交")
    paths_raw = _run_git(
        repository,
        [
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            PINNED_COMMIT,
            "--",
            *(path for path, _object_type, _git_object in PINNED_ALLOWED_PATHS),
        ],
    )
    paths = sorted(
        part.decode("utf-8") for part in paths_raw.split(b"\0") if part
    )
    files = []
    for path in paths:
        if not _is_allowed_file(path):
            raise UpstreamIntegrityError(f"Git 返回未允许路径：{path}")
        content = _read_commit_blob(repository, path)
        files.append({"path": path, "size": len(content), "sha256": _sha256(content)})
    return {
        "schema_version": "mathmodelagent_file_manifest_v1",
        "repository_url": PINNED_REPOSITORY,
        "commit": PINNED_COMMIT,
        "file_count": len(files),
        "files": files,
    }


def _verify_git_objects(repository: Path) -> None:
    for path, expected_type, expected_object in PINNED_ALLOWED_PATHS:
        actual_type = _run_git(
            repository, ["cat-file", "-t", f"{PINNED_COMMIT}:{path}"]
        ).decode().strip()
        actual_object = _run_git(
            repository, ["rev-parse", f"{PINNED_COMMIT}:{path}"]
        ).decode().strip()
        if actual_type != expected_type or actual_object != expected_object:
            raise UpstreamIntegrityError(f"允许路径 Git 对象不匹配：{path}")


def _safe_managed_path(path: Path) -> Path:
    resolved_root = ROOT.resolve()
    resolved_vendor_parent = (ROOT / ".vendor").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_vendor_parent):
        raise UpstreamIntegrityError(f"拒绝操作工作区外路径：{resolved}")
    if resolved in {resolved_root, resolved_vendor_parent}:
        raise UpstreamIntegrityError(f"拒绝操作受保护目录：{resolved}")
    return resolved


def _make_writable(path: str) -> None:
    mode = stat.S_IRWXU if os.path.isdir(path) else stat.S_IWRITE | stat.S_IREAD
    os.chmod(path, mode)


def _remove_managed_tree(path: Path) -> None:
    resolved = _safe_managed_path(path)
    if not resolved.exists():
        return

    for child in sorted(resolved.rglob("*"), reverse=True):
        _make_writable(str(child))
    _make_writable(str(resolved))

    def handle_remove_error(
        function: Any, failed_path: str, _error: tuple[type[BaseException], BaseException, Any]
    ) -> None:
        _make_writable(failed_path)
        function(failed_path)

    shutil.rmtree(resolved, onerror=handle_remove_error)


def _set_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        elif os.name != "nt":
            path.chmod(
                stat.S_IREAD
                | stat.S_IEXEC
                | stat.S_IRGRP
                | stat.S_IXGRP
                | stat.S_IROTH
                | stat.S_IXOTH
            )
    if os.name != "nt":
        root.chmod(
            stat.S_IREAD
            | stat.S_IEXEC
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )


def _materialize_stage(
    repository: Path, stage: Path, manifest: Mapping[str, Any]
) -> None:
    expected_paths: set[str] = set()
    for entry in _manifest_entries(manifest):
        path = str(entry["path"])
        content = _read_commit_blob(repository, path)
        if len(content) != entry["size"] or _sha256(content) != entry["sha256"]:
            raise UpstreamIntegrityError(f"上游 blob 与文件清单不匹配：{path}")
        destination = stage.joinpath(*PurePosixPath(path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        expected_paths.add(path)

    provenance = {
        "schema_version": "mathmodelagent_source_asset_v1",
        "repository_url": PINNED_REPOSITORY,
        "commit": PINNED_COMMIT,
        "manifest_sha256": PINNED_MANIFEST_SHA256,
        "upstream_content_executed": False,
    }
    (stage / "SOURCE.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    actual_paths = set()
    for path in stage.rglob("*"):
        relative = path.relative_to(stage).as_posix()
        if path.is_file() and relative != "SOURCE.json":
            actual_paths.add(relative)
    if actual_paths != expected_paths:
        raise UpstreamIntegrityError("物化目录路径闭包与文件清单不一致")
    _set_read_only(stage)


def verify_vendor(manifest: Mapping[str, Any]) -> None:
    if not VENDOR_PATH.is_dir():
        raise UpstreamIntegrityError("本地 Source Asset 不存在，请先运行同步")
    expected = {str(entry["path"]): entry for entry in _manifest_entries(manifest)}
    actual: dict[str, Path] = {}
    for path in VENDOR_PATH.rglob("*"):
        relative = path.relative_to(VENDOR_PATH).as_posix()
        if path.is_file() and relative != "SOURCE.json":
            actual[relative] = path
    if set(actual) != set(expected):
        raise UpstreamIntegrityError("本地 Source Asset 路径闭包与清单不一致")
    for path, local_path in actual.items():
        content = local_path.read_bytes()
        entry = expected[path]
        if len(content) != entry["size"] or _sha256(content) != entry["sha256"]:
            raise UpstreamIntegrityError(f"本地 Source Asset 文件哈希不匹配：{path}")
    provenance_path = VENDOR_PATH / "SOURCE.json"
    if not provenance_path.is_file():
        raise UpstreamIntegrityError("本地 Source Asset 缺少 SOURCE.json")
    provenance, _raw = _load_json_object(provenance_path)
    expected_provenance = {
        "schema_version": "mathmodelagent_source_asset_v1",
        "repository_url": PINNED_REPOSITORY,
        "commit": PINNED_COMMIT,
        "manifest_sha256": PINNED_MANIFEST_SHA256,
        "upstream_content_executed": False,
    }
    if provenance != expected_provenance:
        raise UpstreamIntegrityError("本地 Source Asset 来源证明不匹配")


def sync() -> None:
    _lock, manifest = load_and_validate_metadata()
    VENDOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".mathmodelagent-stage-", dir=VENDOR_PATH.parent))
    backup = VENDOR_PATH.parent / ".mathmodelagent-backup"
    try:
        with tempfile.TemporaryDirectory(prefix="mathmodelagent-fetch-") as temporary:
            repository = Path(temporary) / "repository.git"
            repository.mkdir()
            _fetch_pinned_repository(repository)
            _verify_git_objects(repository)
            _materialize_stage(repository, stage, manifest)
        verify_target = VENDOR_PATH
        _remove_managed_tree(backup)
        if verify_target.exists():
            verify_target.rename(backup)
        try:
            stage.rename(verify_target)
        except BaseException:
            if backup.exists() and not verify_target.exists():
                backup.rename(verify_target)
            raise
        _remove_managed_tree(backup)
        verify_vendor(manifest)
    finally:
        if stage.exists():
            _remove_managed_tree(stage)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-lock", action="store_true", help="仅校验锁与清单")
    mode.add_argument(
        "--verify-vendor", action="store_true", help="校验锁、清单和本地 Source Asset"
    )
    args = parser.parse_args()
    try:
        _lock, manifest = load_and_validate_metadata()
        if args.verify_lock:
            print("[PASS] MathModelAgent 锁文件与哈希清单")
            return 0
        if args.verify_vendor:
            verify_vendor(manifest)
            print("[PASS] MathModelAgent 本地只读 Source Asset")
            return 0
        sync()
    except UpstreamIntegrityError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[PASS] 已同步到 {VENDOR_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
