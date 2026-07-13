"""trusted-local 执行模型的 Git 现场证明。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


EXECUTION_TRUST_MODEL = "trusted_local"
FORMAL_RESULT_ELIGIBILITY_SCOPE = "trusted_local"


def trusted_local_eligibility_scope(source: dict[str, Any]) -> dict[str, Any]:
    """从已验证摘要提取资格范围；裸 `eligible=true` 必须失败关闭。"""
    if source.get("formal_result_eligible") is not True:
        return {}
    git_head = source.get("git_head")
    if (
        source.get("formal_result_eligibility_scope")
        != FORMAL_RESULT_ELIGIBILITY_SCOPE
        or source.get("execution_trust_model") != EXECUTION_TRUST_MODEL
        or not isinstance(git_head, str)
        or len(git_head) != 40
        or any(character not in "0123456789abcdef" for character in git_head)
        or source.get("git_state_clean") is not True
        or source.get("targeted_host_read_controls_passed") is not True
        or source.get("default_deny_host_reads_verified") is not False
    ):
        raise ValueError("formal_result_eligible=true 缺少完整 trusted_local 资格范围")
    scope = {
        "formal_result_eligibility_scope": FORMAL_RESULT_ELIGIBILITY_SCOPE,
        "execution_trust_model": EXECUTION_TRUST_MODEL,
        "git_head": git_head,
        "git_state_clean": True,
        "targeted_host_read_controls_passed": True,
        "default_deny_host_reads_verified": False,
    }
    privacy = source.get("privacy_mode_available")
    if isinstance(privacy, bool):
        scope["privacy_mode_available"] = privacy
    return scope


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
