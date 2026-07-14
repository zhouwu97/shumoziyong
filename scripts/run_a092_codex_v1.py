"""使用冻结 Codex 配置执行 A092 Codex V1 探针和正式运行。"""

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
WORK_ROOT = ROOT / "tmp" / "a092_confirmatory_codex_v1"
ARCHIVE_ROOT = ROOT / "experiments" / "a092_confirmatory_codex_v1" / "runs"
PROTOCOL_ID = "A092-CONFIRMATORY-CODEX-V1"
EXPECTED_CLI_VERSION = "0.144.2"
EXPECTED_MODEL = "gpt-5.6-sol"
EXPECTED_EFFORT = "high"
EXPECTED_APPROVAL = "never"
EXPECTED_SANDBOX = "danger-full-access"
FORMAL_RUNS = ("R01", "R02")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_codex() -> Path:
    """只选择版本与冻结协议一致的本机 Codex 可执行文件。"""

    candidates: list[Path] = []
    if os.environ.get("A092_CODEX_CLI"):
        candidates.append(Path(os.environ["A092_CODEX_CLI"]))
    local_bin = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    if local_bin.is_dir():
        candidates.extend(sorted(local_bin.glob("*/codex.exe"), reverse=True))
    which = shutil.which("codex")
    if which:
        candidates.append(Path(which))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        raw = subprocess.check_output([str(candidate), "--version"], text=True, encoding="utf-8")
        if raw.strip().split()[-1] == EXPECTED_CLI_VERSION:
            return candidate.resolve()
    raise RuntimeError(f"未找到 Codex CLI {EXPECTED_CLI_VERSION}")


def verify_freeze(*, require_clean: bool = True) -> dict[str, Any]:
    """执行前核对冻结组件、Codex 版本和 Git 工作区。"""

    path = ROOT / "protocols" / "a092_codex_v1" / "protocol_freeze.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("protocol_id") != PROTOCOL_ID or record.get("state") != "frozen_pre_execution" or record.get("execution_started") is not False:
        raise RuntimeError("A092 Codex V1 冻结记录状态不允许启动")
    mismatches = [
        relative for relative, expected in record.get("components", {}).items()
        if not (ROOT / relative).is_file() or _sha256(ROOT / relative) != expected
    ]
    if mismatches:
        raise RuntimeError(f"A092 Codex V1 冻结组件哈希不匹配: {', '.join(mismatches)}")
    _resolve_codex()
    if require_clean:
        worktree = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=ROOT, text=True, encoding="utf-8",
        )
        if worktree.strip():
            raise RuntimeError("A092 Codex V1 运行要求干净 Git 工作区")
    return record


def _render_input(run_id: str, destination: Path, *, protocol_id: str = PROTOCOL_ID) -> Path:
    spec = RUNS[run_id]
    destination.mkdir(parents=True, exist_ok=False)
    problem = str(spec["problem"])
    _copy_materials(problem, destination / "materials")
    shutil.copy2(ROOT / "protocols" / "a092" / "formal_result_contract.md", destination)
    template = (ROOT / "protocols" / "a092" / "stage3_execution_prompt.md").read_text(encoding="utf-8")
    prompt = (
        template.replace("{{RUN_ID}}", run_id)
        .replace("{{PROBLEM_ID}}", problem)
        .replace("{{SCOPE}}", str(spec["scope"]))
        .replace("{{CASE_INSTRUCTIONS}}", CASE_INSTRUCTIONS[problem])
        .replace("{{PROMPT_STACK}}", _prompt_stack(str(spec["arm"])))
    )
    (destination / "prompt_exact.md").write_text(prompt, encoding="utf-8", newline="\n")
    files = sorted(path for path in destination.rglob("*") if path.is_file())
    manifest = {
        "run_id": run_id,
        "protocol_id": protocol_id,
        "problem_id": problem,
        "scope": spec["scope"],
        "arm": spec["arm"],
        "files": {path.relative_to(destination).as_posix(): _sha256(path) for path in files},
    }
    (destination / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def prepare(run_id: str) -> Path:
    verify_freeze()
    if run_id not in FORMAL_RUNS:
        raise ValueError("Codex V1 当前执行序列只开放 R01/R02")
    destination = WORK_ROOT / "prepared" / run_id
    if destination.exists():
        raise FileExistsError(f"运行目录已存在，拒绝覆盖: {destination}")
    return _render_input(run_id, destination)


def _parse_events(path: Path) -> tuple[str | None, dict[str, Any], bool]:
    thread_id = None
    usage: dict[str, Any] = {}
    turn_completed = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
        if event.get("type") == "turn.completed":
            usage = event.get("usage", {})
            turn_completed = True
    return thread_id, usage, turn_completed


def _run_attempt(run_id: str, prepared_dir: Path, official_dir: Path, *, evidence_class: str) -> int:
    spec = RUNS[run_id]
    codex = _resolve_codex()
    with attempt_workspace(WORK_ROOT, official_dir.name, prepared_dir) as attempt:
        run_dir = attempt.path
        events = run_dir / "runner_events.jsonl"
        stderr = run_dir / "runner_stderr.log"
        started = datetime.now(timezone.utc).isoformat()
        command = [
            str(codex), "-a", EXPECTED_APPROVAL, "exec", "--ephemeral",
            "--skip-git-repo-check", "--json", "--output-last-message",
            str(run_dir / "runner_last_message.txt"), "-m", EXPECTED_MODEL,
            "-c", f'model_reasoning_effort="{EXPECTED_EFFORT}"',
            "-s", EXPECTED_SANDBOX, "-C", str(run_dir), "-",
        ]
        timeout_error: ProcessTreeTimeoutExpired | None = None
        return_code: int | None = None
        with events.open("w", encoding="utf-8", newline="\n") as stdout_file, stderr.open("w", encoding="utf-8", newline="\n") as stderr_file:
            try:
                completed = run_process_tree(
                    command,
                    input=(run_dir / "prompt_exact.md").read_text(encoding="utf-8"),
                    text=True, encoding="utf-8", stdout=stdout_file, stderr=stderr_file,
                    timeout=int(spec.get("time_limit_seconds", 3600)), check=False,
                    env={**os.environ, "PYTHONUTF8": "1"}, cwd=run_dir,
                )
                return_code = completed.returncode
            except ProcessTreeTimeoutExpired as exc:
                timeout_error = exc
        thread_id, usage, turn_completed = _parse_events(events)
        formal_result = run_dir / "results" / "formal_result.json"
        formal_result_valid_json = False
        if formal_result.is_file():
            try:
                json.loads(formal_result.read_text(encoding="utf-8"))
                formal_result_valid_json = True
            except json.JSONDecodeError:
                pass
        engine_valid = (
            timeout_error is None and return_code == 0 and thread_id is not None
            and turn_completed and formal_result_valid_json
        )
        metadata = {
            "run_id": run_id,
            "protocol_id": PROTOCOL_ID,
            "evidence_class": evidence_class,
            "attempt_id": attempt.attempt_id,
            "problem_id": spec["problem"],
            "scope": spec["scope"],
            "arm": spec["arm"],
            "execution_engine": "Codex",
            "cli_path": str(codex),
            "cli_version_expected": EXPECTED_CLI_VERSION,
            "cli_version_observed": EXPECTED_CLI_VERSION,
            "model_expected": EXPECTED_MODEL,
            "model_observed": EXPECTED_MODEL,
            "model_observed_source": "parent_invocation",
            "model_reasoning_effort": EXPECTED_EFFORT,
            "approval_policy_observed": EXPECTED_APPROVAL,
            "sandbox_observed": EXPECTED_SANDBOX,
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "execution_status": "timeout" if timeout_error else "completed" if engine_valid else "failed",
            "return_code": return_code,
            "thread_id": thread_id,
            "turn_completed": turn_completed,
            "usage": usage,
            "formal_result_present": formal_result.is_file(),
            "formal_result_valid_json": formal_result_valid_json,
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
        if not engine_valid:
            return int(return_code or 1)
        attempt.promote(official_dir)
        return 0


def probe() -> int:
    verify_freeze()
    prepared = WORK_ROOT / "probe" / "prepared" / "R01"
    official = WORK_ROOT / "probe" / "runs" / "FULL_COMPLETION"
    if prepared.exists() or official.exists():
        raise FileExistsError("Codex V1 非正式探针目录已存在，拒绝重复运行")
    _render_input("R01", prepared, protocol_id=f"{PROTOCOL_ID}-INFORMAL-PROBE")
    return _run_attempt("R01", prepared, official, evidence_class="informal_full_completion_probe")


def execute(run_id: str) -> int:
    verify_freeze()
    prepared = WORK_ROOT / "prepared" / run_id
    official = WORK_ROOT / "runs" / run_id
    if not (prepared / "prompt_exact.md").is_file():
        raise FileNotFoundError(f"运行尚未准备: {prepared}")
    if official.exists():
        raise FileExistsError(f"正式结果目录已存在，拒绝再次执行: {official}")
    return _run_attempt(run_id, prepared, official, evidence_class="formal_confirmatory")


def collect(run_id: str) -> Path:
    verify_freeze()
    source = WORK_ROOT / "runs" / run_id
    destination = ARCHIVE_ROOT / run_id
    staging = WORK_ROOT / "archive_staging" / run_id
    if destination.exists() or staging.exists():
        raise FileExistsError("归档目标或暂存目录已存在")
    shutil.copytree(source, staging, ignore=shutil.ignore_patterns("materials"))
    material_manifest = source / "materials" / "material_manifest.json"
    if material_manifest.is_file():
        shutil.copy2(material_manifest, staging / "material_manifest.snapshot.json")
    try:
        return atomic_copy_directory(staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="A092 Codex V1 隔离运行")
    parser.add_argument("action", choices=("probe", "prepare", "execute", "collect"))
    parser.add_argument("run_id", nargs="?", choices=FORMAL_RUNS)
    args = parser.parse_args()
    if args.action == "probe":
        if args.run_id is not None:
            parser.error("probe 不接受 run_id")
        return probe()
    if args.run_id is None:
        parser.error(f"{args.action} 必须提供 run_id")
    if args.action == "prepare":
        print(prepare(args.run_id))
        return 0
    if args.action == "execute":
        return execute(args.run_id)
    print(collect(args.run_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
