"""在 Docker 中执行断网、只读的 Paper Reader 输入包。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_bytes


def sha256_bytes(value: bytes) -> str:
    """计算审计字段使用的小写 SHA-256。"""
    return hashlib.sha256(value).hexdigest()


def load_workspace_manifest(workspace: Path) -> dict[str, Any]:
    """验证 Reader 容器只会看到既定输入包。"""
    manifest_path = workspace / "workspace_manifest.json"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("workspace_manifest.json 必须为 JSON 对象")
    allowed = value.get("allowlist")
    expected = {
        "problem_statement.pdf",
        "submission_paper.pdf",
        "review_contract.json",
        "review_prompt.txt",
    }
    if not isinstance(allowed, list) or set(allowed) != expected:
        raise ValueError("Reader workspace allowlist 不完整或包含额外输入")
    actual = {path.name for path in workspace.iterdir() if path.is_file()}
    if actual != expected | {"workspace_manifest.json"}:
        raise ValueError("Reader workspace 存在 allowlist 外文件")
    for name in expected:
        if not (workspace / name).is_file():
            raise ValueError(f"Reader workspace 缺少 {name}")
    return value


def _image_id(image: str) -> str:
    """读取已拉取镜像 ID，避免将可变标签当作可复核身份。"""
    completed = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise ValueError(f"Docker 镜像不可用：{image}；请先显式拉取并审核镜像")
    return completed.stdout.strip()


def execute_reader_workspace(
    workspace: Path,
    *,
    image: str,
    command: list[str],
    output: Path,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """以只读 bind mount 和 --network none 执行预装 Reader，写出可复核执行证明。"""
    workspace = workspace.resolve()
    output = output.resolve()
    if not workspace.is_dir():
        raise ValueError("--workspace 必须是存在的目录")
    if not command:
        raise ValueError("必须提供容器内 Reader command")
    manifest = load_workspace_manifest(workspace)
    image_id = _image_id(image)
    if output.is_relative_to(workspace):
        raise ValueError("执行证明不得写入 Reader 输入工作区")

    docker_command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "64",
        "--memory",
        "512m",
        "--user",
        "65534:65534",
        "--workdir",
        "/tmp",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--mount",
        f"type=bind,src={workspace},dst=/review,readonly",
        # Reader 的可执行文件必须覆盖镜像的默认入口，避免服务镜像将审核命令误解析为自身参数。
        "--entrypoint",
        command[0],
        image,
        *command[1:],
    ]
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        completed = subprocess.run(
            docker_command,
            text=False,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        timed_out = True
    status = "workspace_enforced" if exit_code == 0 and not timed_out else "failed"
    attestation: dict[str, Any] = {
        "schema_version": "1.0.0",
        "executor": "docker_read_only_network_none_v1",
        "executed_at": started_at,
        "image": image,
        "image_id": image_id,
        "entrypoint": command[0],
        "command": command,
        "workspace_manifest_sha256": sha256_bytes((workspace / "workspace_manifest.json").read_bytes()),
        "input_allowlist": manifest["allowlist"],
        "repository_mounted": False,
        "parent_context_inherited": False,
        "network_access": False,
        "read_only_root_filesystem": True,
        "mount": {"source": str(workspace), "destination": "/review", "read_only": True},
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_sha256": sha256_bytes(stdout),
        "stderr_sha256": sha256_bytes(stderr),
        "isolation_status": status,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(output, (json.dumps(attestation, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return attestation


def parse_args() -> argparse.Namespace:
    """解析显式 Docker Reader 执行参数。"""
    parser = argparse.ArgumentParser(description="在 Docker 断网只读容器中执行 Paper Reader")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="使用 -- 后提供容器内命令")
    return parser.parse_args()


def main() -> None:
    """命令行入口。"""
    args = parse_args()
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        result = execute_reader_workspace(
            Path(args.workspace),
            image=args.image,
            command=command,
            output=Path(args.output),
            timeout_seconds=args.timeout,
        )
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
