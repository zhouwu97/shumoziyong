"""准备、执行并归档 A092 阶段三隔离确认性运行。"""

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


ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT / "tmp" / "a092_confirmatory_v1"
ARCHIVE_ROOT = ROOT / "experiments" / "a092_confirmatory_v1" / "runs"
V2_WORK_ROOT = ROOT / "tmp" / "a092_confirmatory_v2"
V2_ARCHIVE_ROOT = ROOT / "experiments" / "a092_confirmatory_v2" / "runs"
CODEX = Path.home() / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "a7c12ebff69fb123" / "codex.exe"

RUNS: dict[str, dict[str, str | int]] = {
    "R01": {"sequence": 1, "problem": "2024-C", "scope": "full_problem", "arm": "baseline", "pair": "positive_1"},
    "R02": {"sequence": 2, "problem": "2024-C", "scope": "full_problem", "arm": "treatment", "pair": "positive_1"},
    "R03": {"sequence": 3, "problem": "2024-C", "scope": "full_problem", "arm": "treatment", "pair": "positive_2"},
    "R04": {"sequence": 4, "problem": "2024-C", "scope": "full_problem", "arm": "baseline", "pair": "positive_2"},
    "R05": {"sequence": 5, "problem": "2023-B", "scope": "questions_1_and_2_only", "arm": "treatment", "pair": "boundary_1"},
    "R06": {"sequence": 6, "problem": "2023-B", "scope": "questions_1_and_2_only", "arm": "baseline", "pair": "boundary_1"},
    "R07": {"sequence": 7, "problem": "2023-B", "scope": "questions_1_and_2_only", "arm": "baseline", "pair": "boundary_2"},
    "R08": {"sequence": 8, "problem": "2023-B", "scope": "questions_1_and_2_only", "arm": "treatment", "pair": "boundary_2"},
    "R09": {"sequence": 9, "problem": "2016-C", "scope": "full_problem", "arm": "baseline", "pair": "negative_1"},
    "R10": {"sequence": 10, "problem": "2016-C", "scope": "full_problem", "arm": "treatment", "pair": "negative_1"},
}

CASE_INSTRUCTIONS = {
    "2024-C": """完成问题 1 的两种销售情形、问题 2 的冻结不确定性口径和问题 3 的相关性模拟比较。必须实际读取两个附件、生成 2024—2030 全部方案、运行求解代码并填写 results/formal_result.json。另保存 q3 模拟样本、风险指标和与 q2 的比较证据。可使用线性/混合整数规划或其他可复算方法；若求解未达到全局证书，只能按证据表述。""",
    "2023-B": """严格只完成问题一、问题二，不做问题三、四。推导覆盖宽度公式，实际计算题面两张表，生成 result1.xlsx、result2.xlsx 和 results/formal_result.json。该范围没有方案优化，不得为了补齐内容引入基线优化、敏感性或最优性声明。""",
    "2016-C": """完成三个问题：各电流放电曲线初等函数拟合与 MRE、20A—100A 任意电流模型及 55A 曲线、衰减状态3剩余放电时间预测。必须实际读取附件工作簿、运行拟合代码并输出用于独立复算 MRE 的逐点真值与预测值。本题不是工程设计优化，不得制造设计变量、方案评价器或全局最优声明。""",
}

MATERIAL_DIRS = {"2024-C": "2024_C", "2023-B": "2023_B", "2016-C": "2016_C"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _roots(protocol_version: str) -> tuple[Path, Path]:
    if protocol_version == "v1":
        return WORK_ROOT, ARCHIVE_ROOT
    if protocol_version == "v2":
        return V2_WORK_ROOT, V2_ARCHIVE_ROOT
    raise ValueError(f"不支持的协议版本: {protocol_version}")


def verify_v2_freeze() -> dict[str, Any]:
    """执行前现场核对 v2 冻结组件，拒绝协议后改。"""

    path = ROOT / "protocols" / "a092_v2" / "protocol_freeze.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("protocol_id") != "A092-CONFIRMATORY-V2"
        or record.get("state") != "frozen_pre_execution"
        or record.get("execution_started") is not False
    ):
        raise RuntimeError("A092 v2 冻结记录状态不允许启动")
    mismatches = [
        relative
        for relative, expected in record.get("components", {}).items()
        if not (ROOT / relative).is_file() or _sha256(ROOT / relative) != expected
    ]
    if mismatches:
        raise RuntimeError(f"A092 v2 冻结组件哈希不匹配: {', '.join(mismatches)}")
    worktree = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    )
    if worktree.strip():
        raise RuntimeError("A092 v2 正式运行要求干净 Git 工作区")
    return record


def _copy_materials(problem: str, destination: Path) -> None:
    source = ROOT / "official_materials" / MATERIAL_DIRS[problem]
    destination.mkdir(parents=True, exist_ok=False)
    names = {
        "2024-C": ("manifest.md", "material_manifest.json", "problem", "attachments", "templates"),
        "2023-B": ("manifest.md", "material_manifest.json", "problem", "attachments", "templates"),
        "2016-C": ("manifest.md", "material_manifest.json", "problem", "data"),
    }[problem]
    for name in names:
        item = source / name
        if item.is_dir():
            shutil.copytree(item, destination / name)
        else:
            shutil.copy2(item, destination / name)


def _prompt_stack(arm: str) -> str:
    components = [
        ROOT / "prompt_base" / "prompt_base_v1.0.md",
        ROOT / "prompt_plugins" / "plugin_optimization_v1.md",
    ]
    if arm == "treatment":
        components.append(ROOT / "prompt_patches" / "patch_A092_engineering_optimization.md")
    blocks = []
    for path in components:
        blocks.append(f"\n--- BEGIN {path.name} ---\n{path.read_text(encoding='utf-8')}\n--- END {path.name} ---")
    return "\n".join(blocks)


def prepare(run_id: str, protocol_version: str = "v1") -> Path:
    if protocol_version == "v2":
        verify_v2_freeze()
    work_root, _ = _roots(protocol_version)
    spec = RUNS[run_id]
    run_dir = work_root / "prepared" / run_id
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
        "protocol_id": f"A092-CONFIRMATORY-{protocol_version.upper()}",
        "problem_id": problem,
        "scope": spec["scope"],
        "files": {path.relative_to(run_dir).as_posix(): _sha256(path) for path in files},
    }
    (run_dir / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return run_dir


def _parse_events(path: Path) -> tuple[str | None, dict[str, Any]]:
    thread_id = None
    usage: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
        if event.get("type") == "turn.completed":
            usage = event.get("usage", {})
    return thread_id, usage


def execute(run_id: str, protocol_version: str = "v1") -> int:
    if protocol_version == "v2":
        verify_v2_freeze()
    work_root, _ = _roots(protocol_version)
    spec = RUNS[run_id]
    prepared_dir = work_root / "prepared" / run_id
    official_dir = work_root / "runs" / run_id
    if not (prepared_dir / "prompt_exact.md").is_file():
        raise FileNotFoundError(f"运行尚未准备: {prepared_dir}")
    if official_dir.exists():
        raise FileExistsError(f"正式结果目录已存在，拒绝再次执行: {official_dir}")

    with attempt_workspace(work_root, run_id, prepared_dir) as attempt:
        run_dir = attempt.path
        events = run_dir / "runner_events.jsonl"
        stderr = run_dir / "runner_stderr.log"
        started = datetime.now(timezone.utc).isoformat()
        command = [
            str(CODEX),
            "-a",
            "never",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--json",
            "--output-last-message",
            str(run_dir / "runner_last_message.txt"),
            "-m",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="high"',
            "-s",
            "danger-full-access",
            "-C",
            str(run_dir),
            "-",
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

        thread_id, usage = _parse_events(events)
        execution_status = (
            "timeout"
            if timeout_error is not None
            else "completed" if return_code == 0 else "failed"
        )
        metadata = {
            "run_id": run_id,
            "protocol_id": f"A092-CONFIRMATORY-{protocol_version.upper()}",
            "attempt_id": attempt.attempt_id,
            "problem_id": spec["problem"],
            "scope": spec["scope"],
            "model": "gpt-5.6-sol",
            "model_reasoning_effort": "high",
            "sampling_control": "codex_cli_model_default",
            "codex_cli_version": "0.144.0-alpha.4",
            "sandbox": "danger-full-access",
            "web_search": False,
            "human_confirmation": False,
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "execution_status": execution_status,
            "return_code": return_code,
            "thread_id": thread_id,
            "usage": usage,
            "prompt_sha256": _sha256(run_dir / "prompt_exact.md"),
            "process_tree_terminated": (
                timeout_error.process_tree_terminated if timeout_error is not None else None
            ),
            "termination_details": (
                timeout_error.termination_details if timeout_error is not None else None
            ),
        }
        (run_dir / "runner_metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if timeout_error is not None:
            if not timeout_error.process_tree_terminated:
                attempt.retain_lock("进程树清理证明失败；需人工确认后释放")
                return 125
            return 124
        if return_code != 0:
            return int(return_code or 1)
        attempt.promote(official_dir)
        return 0


def collect(run_id: str, protocol_version: str = "v1") -> Path:
    if protocol_version == "v2":
        verify_v2_freeze()
    work_root, archive_root = _roots(protocol_version)
    source = work_root / "runs" / run_id
    destination = archive_root / run_id
    if destination.exists():
        raise FileExistsError(f"归档目录已存在，拒绝覆盖: {destination}")
    staging_source = work_root / "archive_staging" / run_id
    if staging_source.exists():
        raise FileExistsError(f"归档暂存目录已存在，拒绝覆盖: {staging_source}")
    shutil.copytree(
        source,
        staging_source,
        ignore=shutil.ignore_patterns("materials"),
    )
    material_manifest = source / "materials" / "material_manifest.json"
    if material_manifest.is_file():
        shutil.copy2(material_manifest, staging_source / "material_manifest.snapshot.json")
    try:
        return atomic_copy_directory(staging_source, destination)
    finally:
        shutil.rmtree(staging_source, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="A092 阶段三隔离运行")
    parser.add_argument("action", choices=("prepare", "execute", "collect"))
    parser.add_argument("run_id", choices=tuple(RUNS))
    parser.add_argument("--protocol-version", choices=("v1", "v2"), default="v1")
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare(args.run_id, args.protocol_version))
        return 0
    if args.action == "execute":
        return execute(args.run_id, args.protocol_version)
    print(collect(args.run_id, args.protocol_version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
