"""trusted-local 执行模型的 Git 现场证明。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


EXECUTION_TRUST_MODEL = "trusted_local"


def collect_git_state(repository_root: Path) -> dict[str, Any]:
    """记录 HEAD、未暂存/已暂存差异和包含未跟踪文件的 porcelain 状态。"""

    def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )

    head = run(["rev-parse", "HEAD"])
    status = run(["status", "--porcelain=v1", "--untracked-files=all"])
    unstaged = run(["diff", "--exit-code"])
    staged = run(["diff", "--cached", "--exit-code"])
    git_head = head.stdout.strip()
    clean = (
        head.returncode == 0
        and len(git_head) == 40
        and status.returncode == 0
        and not status.stdout.strip()
        and unstaged.returncode == 0
        and staged.returncode == 0
    )
    return {
        "git_head": git_head,
        "git_state_clean": clean,
        "status_porcelain_v1": status.stdout,
        "status_exit_code": status.returncode,
        "diff_exit_code": unstaged.returncode,
        "diff_cached_exit_code": staged.returncode,
    }


def require_clean_git_state(repository_root: Path) -> dict[str, Any]:
    state = collect_git_state(repository_root)
    if not state["git_state_clean"]:
        raise RuntimeError("trusted-local 执行要求 Git HEAD 固定且工作区、暂存区、未跟踪文件均为空")
    return state
