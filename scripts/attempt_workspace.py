"""候选运行 attempt 的独占、隔离与原子提升。"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class ActiveAttemptError(RuntimeError):
    """同一 Run 已存在活动 attempt。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attempt_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"attempt-{timestamp}-{uuid.uuid4().hex[:12]}"


@dataclass
class AttemptWorkspace:
    root: Path
    run_id: str
    attempt_id: str
    path: Path
    lock_path: Path
    owner_token: str
    promoted_to: Path | None = None
    release_lock_on_exit: bool = True

    def promote(self, destination: Path) -> Path:
        """将完整 attempt 以一次目录重命名提升为正式结果。"""
        if self.promoted_to is not None:
            raise RuntimeError(f"attempt 已提升到 {self.promoted_to}")
        destination = destination.resolve()
        if destination.exists():
            raise FileExistsError(f"正式结果目录已存在，拒绝覆盖: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.path.stat().st_dev != destination.parent.stat().st_dev:
            raise OSError("attempt 与正式结果目录不在同一文件系统，无法原子提升")
        os.replace(self.path, destination)
        self.promoted_to = destination
        return destination

    def retain_lock(self, reason: str) -> None:
        """清理证明失败时保留 Run 锁，阻止后续 attempt 并发启动。"""
        payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        if payload.get("owner_token") != self.owner_token:
            raise RuntimeError("active attempt 锁所有权已变化")
        payload["lock_retained"] = True
        payload["retained_reason"] = reason
        payload["retained_at"] = _now()
        self.lock_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        self.release_lock_on_exit = False


def _write_lock(lock_path: Path, payload: dict[str, object]) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    attempt: AttemptWorkspace | None = None
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        try:
            existing = lock_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = "锁文件正在由另一进程写入"
        raise ActiveAttemptError(
            f"run 已存在 active attempt: {lock_path} ({existing.strip()})"
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _release_lock(lock_path: Path, owner_token: str) -> None:
    if not lock_path.is_file():
        return
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if payload.get("owner_token") == owner_token:
        lock_path.unlink()


@contextmanager
def attempt_workspace(
    root: Path,
    run_id: str,
    prepared_dir: Path,
) -> Iterator[AttemptWorkspace]:
    """获取 Run 独占权，并从冻结输入创建唯一 attempt 工作目录。"""
    root = root.resolve()
    prepared_dir = prepared_dir.resolve()
    if not prepared_dir.is_dir():
        raise FileNotFoundError(f"冻结输入目录不存在: {prepared_dir}")
    attempt_id = _attempt_id()
    owner_token = uuid.uuid4().hex
    lock_path = root / "active_attempts" / f"{run_id}.json"
    _write_lock(
        lock_path,
        {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "owner_token": owner_token,
            "owner_pid": os.getpid(),
            "started_at": _now(),
        },
    )
    attempt_dir = root / "attempts" / run_id / attempt_id
    try:
        attempt_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(prepared_dir, attempt_dir)
        attempt = AttemptWorkspace(
            root=root,
            run_id=run_id,
            attempt_id=attempt_id,
            path=attempt_dir,
            lock_path=lock_path,
            owner_token=owner_token,
        )
        yield attempt
    finally:
        if attempt is None or attempt.release_lock_on_exit:
            _release_lock(lock_path, owner_token)


def atomic_copy_directory(source: Path, destination: Path) -> Path:
    """先复制到同级暂存目录，再原子发布只读归档。"""
    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"目标目录已存在，拒绝覆盖: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.staging"
    try:
        shutil.copytree(source, staging)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination
