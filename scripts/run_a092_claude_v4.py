"""使用冻结 Claude Code 权限配置执行 A092 v4 确认性运行。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from attempt_workspace import atomic_copy_directory, attempt_workspace
from process_tree import ProcessTreeTimeoutExpired, run_process_tree
from run_a092_stage3 import CASE_INSTRUCTIONS, MATERIAL_DIRS, RUNS, _copy_materials, _prompt_stack


ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT / "tmp" / "a092_confirmatory_v4"
ARCHIVE_ROOT = ROOT / "experiments" / "a092_confirmatory_v4" / "runs"
CLAUDE = "claude"
EXPECTED_CLI_VERSION = "2.1.207"
EXPECTED_MODEL = "claude-opus-4-8"
EXPECTED_PERMISSION_MODE = "bypassPermissions"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cli_version(raw_version: str) -> str:
    """提取 Claude CLI 输出中的标准版本号。"""

    return raw_version.strip().split(maxsplit=1)[0]


def verify_v4_freeze() -> dict[str, Any]:
    """执行前核对 v4 冻结组件、Claude 版本和干净工作区。"""

    path = ROOT / "protocols" / "a092_v4" / "protocol_freeze.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("protocol_id") != "A092-CONFIRMATORY-V4"
        or record.get("state") != "frozen_pre_execution"
        or record.get("execution_started") is not False
    ):
        raise RuntimeError("A092 v4 冻结记录状态不允许启动")
    mismatches = [
        relative
        for relative, expected in record.get("components", {}).items()
        if not (ROOT / relative).is_file() or _sha256(ROOT / relative) != expected
    ]
    if mismatches:
        raise RuntimeError(f"A092 v4 冻结组件哈希不匹配: {', '.join(mismatches)}")
    actual_version = _cli_version(
        subprocess.check_output([CLAUDE, "--version"], text=True, encoding="utf-8")
    )
    if actual_version != EXPECTED_CLI_VERSION:
        raise RuntimeError(f"Claude Code 版本漂移: {actual_version}")
    worktree = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    )
    if worktree.strip():
        raise RuntimeError("A092 v4 正式运行要求干净 Git 工作区")
    return record


def prepare(run_id: str) -> Path:
    verify_v4_freeze()
    spec = RUNS[run_id]
    run_dir = WORK_ROOT / "prepared" / run_id
    if run_dir.exists():
        raise FileExistsError(f"运行目录已存在，拒绝覆盖: {run_dir}")
    run_dir.mkdir(parents=True)
    problem = str(spec["problem"])
    _copy_materials(problem, run_dir / "materials")
    shutil.copy2(ROOT / "protocols" / "a092" / "formal_result_contract.md", run_dir)
    template = (ROOT / "protocols" / "a092" / "stage3_execution_prompt.md").read_text(
        encoding="utf-8"
    )
    prompt = (
        template.replace("{{RUN_ID}}", run_id)
        .replace("{{PROBLEM_ID}}", problem)
        .replace("{{SCOPE}}", str(spec["scope"]))
        .replace("{{CASE_INSTRUCTIONS}}", CASE_INSTRUCTIONS[problem])
        .replace("{{PROMPT_STACK}}", _prompt_stack(str(spec["arm"])))
    )
    (run_dir / "prompt_exact.md").write_text(prompt, encoding="utf-8", newline="\n")
    files = sorted(path for path in run_dir.rglob("*") if path.is_file())
    manifest = {
        "run_id": run_id,
        "protocol_id": "A092-CONFIRMATORY-V4",
        "execution_engine": {
            "cli": "Claude Code",
            "model": EXPECTED_MODEL,
            "permission_mode": EXPECTED_PERMISSION_MODE,
        },
        "problem_id": problem,
        "scope": spec["scope"],
        "files": {path.relative_to(run_dir).as_posix(): _sha256(path) for path in files},
    }
    (run_dir / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return run_dir


def _parse_events(
    path: Path,
) -> tuple[str | None, dict[str, Any], str | None, str | None, str | None]:
    session_id = None
    usage: dict[str, Any] = {}
    model = None
    cli_version = None
    permission_mode = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            session_id = event.get("session_id")
            model = event.get("model")
            cli_version = event.get("claude_code_version")
            permission_mode = event.get("permissionMode")
        if event.get("type") == "result":
            usage = event.get("usage", {})
    return session_id, usage, model, cli_version, permission_mode


def execute(run_id: str) -> int:
    verify_v4_freeze()
    spec = RUNS[run_id]
    prepared_dir = WORK_ROOT / "prepared" / run_id
    official_dir = WORK_ROOT / "runs" / run_id
    if not (prepared_dir / "prompt_exact.md").is_file():
        raise FileNotFoundError(f"运行尚未准备: {prepared_dir}")
    if official_dir.exists():
        raise FileExistsError(f"正式结果目录已存在，拒绝再次执行: {official_dir}")

    with attempt_workspace(WORK_ROOT, run_id, prepared_dir) as attempt:
        run_dir = attempt.path
        events = run_dir / "runner_events.jsonl"
        stderr = run_dir / "runner_stderr.log"
        started = datetime.now(timezone.utc).isoformat()
        command = [
            CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--permission-mode", EXPECTED_PERMISSION_MODE,
            "--effort", "high", "--model", EXPECTED_MODEL,
        ]
        timeout_error: ProcessTreeTimeoutExpired | None = None
        return_code: int | None = None
        with events.open("w", encoding="utf-8", newline="\n") as stdout_file, stderr.open(
            "w", encoding="utf-8", newline="\n"
        ) as stderr_file:
            try:
                completed = run_process_tree(
                    command,
                    input=(run_dir / "prompt_exact.md").read_text(encoding="utf-8"),
                    text=True,
                    encoding="utf-8",
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=int(spec.get("time_limit_seconds", 3600)),
                    check=False,
                    env={**os.environ, "PYTHONUTF8": "1"},
                    cwd=run_dir,
                )
                return_code = completed.returncode
            except ProcessTreeTimeoutExpired as exc:
                timeout_error = exc

        session_id, usage, model, cli_version, permission_mode = _parse_events(events)
        engine_valid = (
            isinstance(model, str)
            and model.split("[", 1)[0] == EXPECTED_MODEL
            and cli_version == EXPECTED_CLI_VERSION
            and permission_mode == EXPECTED_PERMISSION_MODE
        )
        metadata = {
            "run_id": run_id,
            "protocol_id": "A092-CONFIRMATORY-V4",
            "attempt_id": attempt.attempt_id,
            "problem_id": spec["problem"],
            "scope": spec["scope"],
            "execution_engine": "Claude Code",
            "cli_version_expected": EXPECTED_CLI_VERSION,
            "cli_version_observed": cli_version,
            "model_expected": EXPECTED_MODEL,
            "model_observed": model,
            "permission_mode_expected": EXPECTED_PERMISSION_MODE,
            "permission_mode_observed": permission_mode,
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "execution_status": "timeout" if timeout_error else "completed" if return_code == 0 and engine_valid else "failed",
            "return_code": return_code,
            "session_id": session_id,
            "usage": usage,
            "engine_valid": engine_valid,
            "prompt_sha256": _sha256(run_dir / "prompt_exact.md"),
            "process_tree_terminated": timeout_error.process_tree_terminated if timeout_error else None,
            "termination_details": timeout_error.termination_details if timeout_error else None,
        }
        (run_dir / "runner_metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if timeout_error is not None:
            if not timeout_error.process_tree_terminated:
                attempt.retain_lock("进程树清理证明失败；需人工确认后释放")
                return 125
            return 124
        if return_code != 0 or not engine_valid:
            return int(return_code or 1)
        attempt.promote(official_dir)
        return 0


def collect(run_id: str) -> Path:
    verify_v4_freeze()
    source = WORK_ROOT / "runs" / run_id
    destination = ARCHIVE_ROOT / run_id
    staging_source = WORK_ROOT / "archive_staging" / run_id
    if destination.exists() or staging_source.exists():
        raise FileExistsError("归档目标或暂存目录已存在")
    shutil.copytree(source, staging_source, ignore=shutil.ignore_patterns("materials"))
    material_manifest = source / "materials" / "material_manifest.json"
    if material_manifest.is_file():
        shutil.copy2(material_manifest, staging_source / "material_manifest.snapshot.json")
    try:
        return atomic_copy_directory(staging_source, destination)
    finally:
        shutil.rmtree(staging_source, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="A092 Claude Code v4 隔离运行")
    parser.add_argument("action", choices=("prepare", "execute", "collect"))
    parser.add_argument("run_id", choices=tuple(RUNS))
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare(args.run_id))
        return 0
    if args.action == "execute":
        return execute(args.run_id)
    print(collect(args.run_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
