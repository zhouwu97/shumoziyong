"""不可变审核记录与追加式哈希账本的通用持久化工具。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from atomic_io import atomic_write_bytes


CANONICALIZATION_VERSION = "1.0.0"
HISTORY_EVENT_VERSION = "1.0.0"


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """生成与缩进、换行和字典遍历顺序无关的 JSON 字节。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """返回小写十六进制 SHA-256。"""
    return hashlib.sha256(value).hexdigest()


def _event_with_hash(event: Mapping[str, Any], previous_event_sha256: str | None) -> dict[str, Any]:
    payload = dict(event)
    payload["previous_event_sha256"] = previous_event_sha256
    payload.pop("event_sha256", None)
    payload["event_sha256"] = sha256_bytes(canonical_json_bytes(payload))
    return payload


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} 无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return value


def _read_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} 第 {line_no} 行不是合法 JSON：{exc}") from exc
        if not isinstance(entry, dict):
            raise ValueError(f"{path.name} 第 {line_no} 行必须是 JSON 对象")
        entries.append(entry)
    return entries


def verify_history(run_dir: Path, history_filename: str) -> tuple[list[dict[str, Any]], str | None]:
    """验证 history 的前缀、路径、文件哈希和事件哈希链。"""
    history_path = run_dir / history_filename
    entries = _read_history(history_path)
    previous: str | None = None
    seen_ids: set[str] = set()
    expected_attempt = 1
    for index, entry in enumerate(entries, start=1):
        for field in ("history_event_version", "canonicalization_version", "review_id", "attempt", "path", "sha256", "decision", "reviewed_at"):
            if field not in entry:
                raise ValueError(f"{history_filename} 第 {index} 条缺少 {field}")
        if entry["history_event_version"] != HISTORY_EVENT_VERSION:
            raise ValueError(f"{history_filename} 第 {index} 条 history_event_version 不支持")
        if entry["canonicalization_version"] != CANONICALIZATION_VERSION:
            raise ValueError(f"{history_filename} 第 {index} 条 canonicalization_version 不支持")
        review_id = entry["review_id"]
        if not isinstance(review_id, str) or not review_id or review_id in seen_ids:
            raise ValueError(f"{history_filename} 第 {index} 条 review_id 非法或重复")
        seen_ids.add(review_id)
        if entry["attempt"] != expected_attempt:
            raise ValueError(f"{history_filename} 第 {index} 条 attempt 不连续")
        expected_attempt += 1
        relative = entry["path"]
        if not isinstance(relative, str) or not re.fullmatch(r"reviews/[A-Za-z0-9_./-]+\.json", relative):
            raise ValueError(f"{history_filename} 第 {index} 条 path 非法")
        review_path = (run_dir / relative).resolve()
        if not review_path.is_relative_to(run_dir.resolve()) or not review_path.is_file():
            raise ValueError(f"{history_filename} 第 {index} 条引用的审核文件不存在")
        if entry["sha256"] != sha256_bytes(review_path.read_bytes()):
            raise ValueError(f"{history_filename} 第 {index} 条审核文件 SHA-256 不匹配")
        expected = _event_with_hash(entry, previous)
        if entry.get("previous_event_sha256") != previous:
            raise ValueError(f"{history_filename} 第 {index} 条 previous_event_sha256 不匹配")
        if entry.get("event_sha256") != expected["event_sha256"]:
            raise ValueError(f"{history_filename} 第 {index} 条 event_sha256 不匹配")
        previous = str(entry["event_sha256"])
    return entries, previous


@contextmanager
def acquire_run_write_lock(run_dir: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """取得跨进程单 Run 排他锁，锁文件本身可保留但锁状态不可继承。"""
    lock_path = run_dir / ".review-ledger.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - Windows 开发环境之外的兼容分支
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"无法取得单 Run 审核写锁：{lock_path}") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - Windows 开发环境之外的兼容分支
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _history_event(review: Mapping[str, Any], relative_path: str, raw: bytes) -> dict[str, Any]:
    """从审核记录生成与具体 Reviewer 类型无关的账本事件。"""
    event: dict[str, Any] = {
        "history_event_version": HISTORY_EVENT_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "review_id": review["review_id"],
        "attempt": review["attempt"],
        "path": relative_path,
        "sha256": sha256_bytes(raw),
        "decision": review["decision"],
        "reviewed_at": review["reviewed_at"],
    }
    for field in ("candidate_id", "candidate_manifest_sha256", "review_type"):
        if field in review:
            event[field] = review[field]
    return event


def reconcile_orphan_reviews(
    run_dir: Path,
    *,
    review_directory: str,
    history_filename: str,
    validate_review: Callable[[dict[str, Any]], None],
) -> tuple[list[dict[str, Any]], str | None]:
    """将已原子发布但尚未入账的审核文件恢复为严格连续的 history 事件。"""
    entries, head = verify_history(run_dir, history_filename)
    recorded_paths = {str(entry["path"]) for entry in entries}
    recorded_ids = {str(entry["review_id"]) for entry in entries}
    review_root = run_dir / review_directory
    if not review_root.exists():
        return entries, head
    orphan_paths = sorted(
        path for path in review_root.glob("*.json") if path.relative_to(run_dir).as_posix() not in recorded_paths
    )
    for review_path in orphan_paths:
        review = _read_json_object(review_path, review_path.name)
        validate_review(review)
        review_id = review.get("review_id")
        if review_id != review_path.stem:
            raise ValueError(f"孤立审核 {review_path.name} 的文件名必须与 review_id 一致")
        if not isinstance(review_id, str) or review_id in recorded_ids:
            raise ValueError(f"孤立审核 {review_path.name} 的 review_id 重复或非法")
        expected_attempt = len(entries) + 1
        if review.get("attempt") != expected_attempt:
            raise ValueError(
                f"孤立审核 {review_path.name} 的 attempt 必须为 {expected_attempt}，实际为 {review.get('attempt')!r}"
            )
        relative = review_path.relative_to(run_dir).as_posix()
        event = _event_with_hash(_history_event(review, relative, review_path.read_bytes()), head)
        entries.append(event)
        recorded_ids.add(review_id)
        head = str(event["event_sha256"])
    if orphan_paths:
        serialized = "".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries)
        atomic_write_bytes(run_dir / history_filename, serialized.encode("utf-8"))
    return entries, head


def append_immutable_review(
    run_dir: Path,
    review: Mapping[str, Any],
    *,
    review_directory: str,
    history_filename: str,
    validate_review: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """发布不可覆盖审核文件，并以原子替换提交其完整 history 前缀。"""
    payload = dict(review)
    entries, head = reconcile_orphan_reviews(
        run_dir,
        review_directory=review_directory,
        history_filename=history_filename,
        validate_review=validate_review,
    )
    payload["attempt"] = len(entries) + 1
    validate_review(payload)
    review_id = payload.get("review_id")
    if not isinstance(review_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{2,127}", review_id):
        raise ValueError("review_id 必须为 3-128 位安全标识")
    review_path = run_dir / review_directory / f"{review_id}.json"
    if review_path.exists():
        raise FileExistsError(f"审核记录不可覆盖：{review_path}")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(review_path, raw)
    relative = review_path.relative_to(run_dir).as_posix()
    event = _event_with_hash(_history_event(payload, relative, raw), head)
    entries.append(event)
    serialized = "".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries)
    atomic_write_bytes(run_dir / history_filename, serialized.encode("utf-8"))
    return {
        "review": payload,
        "path": relative,
        "sha256": sha256_bytes(raw),
        "history_path": history_filename,
        "history_sha256": sha256_bytes((run_dir / history_filename).read_bytes()),
        "history_head_sha256": event["event_sha256"],
        "attempt": payload["attempt"],
    }
