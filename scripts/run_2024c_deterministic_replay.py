"""在独立工作目录中复跑 2024-C 正式入口并记录确定性证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_frozen_file(source: Path, target: Path) -> dict[str, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {"path": target.as_posix(), "sha256": sha256(target)}


def run_replay(run_dir: Path) -> dict[str, object]:
    run_dir = run_dir.resolve()
    source_workspace = run_dir / "workspace"
    replay_workspace = run_dir / "replay_workspace"
    if replay_workspace.exists():
        shutil.rmtree(replay_workspace)

    copied: list[dict[str, str]] = []
    for relative in ("code/formal_solve.py", "code/run_pipeline.py"):
        source = source_workspace / relative
        target = replay_workspace / relative
        item = copy_frozen_file(source, target)
        item["path"] = target.relative_to(run_dir).as_posix()
        copied.append(item)
    for filename in ("附件1.xlsx", "附件2.xlsx"):
        source = source_workspace / "materials" / "attachments" / filename
        target = replay_workspace / "input" / "attachments" / filename
        item = copy_frozen_file(source, target)
        item["path"] = target.relative_to(run_dir).as_posix()
        copied.append(item)

    expected_output = run_dir / "workspace" / "output" / "result.json"
    expected_sha256 = sha256(expected_output)
    execution_id = f"deterministic-replay-{uuid.uuid4().hex}"
    challenge = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONHASHSEED": "20240713",
            "SHUMO_EXECUTION_SEED": "20240713",
            "SHUMO_EXECUTION_CHALLENGE": challenge,
            "SHUMO_RUN_ID": run_dir.name,
            "SHUMO_EXECUTION_ID": execution_id,
        }
    )

    stdout_path = run_dir / "deterministic_replay.stdout.log"
    stderr_path = run_dir / "deterministic_replay.stderr.log"
    started_at = datetime.now().astimezone()
    completed = subprocess.run(
        [sys.executable, "code/formal_solve.py"],
        cwd=replay_workspace,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    completed_at = datetime.now().astimezone()
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    output_path = replay_workspace / "output" / "result.json"
    if completed.returncode != 0:
        raise RuntimeError(
            f"确定性复跑失败，退出码 {completed.returncode}；见 {stderr_path.name}"
        )
    if not output_path.is_file():
        raise RuntimeError("确定性复跑未生成 output/result.json")
    output_sha256 = sha256(output_path)
    if output_sha256 != expected_sha256:
        raise RuntimeError(
            "确定性复跑结果与 Sandbox Formal Result 原始输出哈希不一致"
        )

    record: dict[str, object] = {
        "schema_version": "1.0.0",
        "artifact_type": "deterministic_replay_record",
        "run_id": run_dir.name,
        "execution_id": execution_id,
        "seed": 20240713,
        "command": f"{sys.executable} code/formal_solve.py",
        "working_directory": "replay_workspace",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "exit_code": completed.returncode,
        "source_files": copied,
        "expected_output_ref": {
            "path": "workspace/output/result.json",
            "sha256": expected_sha256,
        },
        "output_ref": {
            "path": output_path.relative_to(run_dir).as_posix(),
            "sha256": output_sha256,
        },
        "stdout_ref": {
            "path": stdout_path.relative_to(run_dir).as_posix(),
            "sha256": sha256(stdout_path),
        },
        "stderr_ref": {
            "path": stderr_path.relative_to(run_dir).as_posix(),
            "sha256": sha256(stderr_path),
        },
        "python_executable": sys.executable,
        "python_executable_sha256": sha256(Path(sys.executable)),
        "deterministic_match": True,
    }
    write_json(run_dir / "deterministic_replay_record.json", record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    record = run_replay(args.run_dir)
    print(
        "deterministic replay passed:",
        record["output_ref"]["sha256"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
