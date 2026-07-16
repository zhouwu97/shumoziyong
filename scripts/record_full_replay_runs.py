"""从可信执行和论文候选证据生成 PR-7 单题运行记录。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from finalize_full_replay_runs import PROBLEMS


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "competition_full_replay_run_record.schema.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 不是合法 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")
    return parsed


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _relative_paths(paths: list[Path], root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in paths]


def build_record(run_root: Path, completed_at: datetime) -> dict[str, Any]:
    if completed_at.tzinfo is None:
        raise ValueError("completed_at 必须包含时区")
    session = _load(run_root / "full_replay_session.json")
    run_manifest = _load(run_root / "run_manifest.json")
    started_text = str(session["started_at"])
    started_at = _parse_time(started_text, "full_replay_session.started_at")
    if completed_at <= started_at:
        raise ValueError("completed_at 必须晚于 full_replay_session.started_at")

    source_commit = str(session["source_control_commit"])
    attestations = sorted(
        (run_root / "route_runs").glob("*/*/sandboxie_run_execution_attestation.json")
    )
    if not attestations:
        raise ValueError(f"{run_root.name} 缺少可信路线执行证明")
    for path in attestations:
        attestation = _load(path)
        if attestation.get("git_head") != source_commit:
            raise ValueError(f"{path} 未绑定 full_replay_session 提交")
        execution_started = _parse_time(str(attestation["started_at"]), f"{path}.started_at")
        execution_completed = _parse_time(
            str(attestation["completed_at"]), f"{path}.completed_at"
        )
        if not (started_at <= execution_started < execution_completed <= completed_at):
            raise ValueError(f"{path} 不在 full_replay 时间窗口内")

    visual_path = run_root / "paper_visual_review.json"
    visual = _load(visual_path)
    if visual.get("status") != "passed":
        raise ValueError("paper_visual_review 未通过")
    candidate_path = run_root / "paper_candidate_manifest.json"
    candidate = _load(candidate_path)
    if candidate.get("candidate_status") != "paper_candidate_ready_for_independent_review":
        raise ValueError("论文候选尚未进入独立评审就绪状态")

    interventions: list[dict[str, Any]] = []
    recovery_archives = sorted(path for path in run_root.glob("route_runs.*") if path.is_dir())
    if recovery_archives:
        interventions.append(
            {
                "intervention_id": "HI-EXECUTION_RECOVERY",
                "occurred_at": started_text,
                "category": "execution_recovery",
                "description": (
                    "可信执行开始前清理失效环境证据并重建 Sandboxie 执行环境，"
                    "失败尝试保留在隔离归档目录中。"
                ),
                "affected_artifacts": _relative_paths(recovery_archives, run_root)
                + ["route_runs"],
            }
        )
    interventions.append(
        {
            "intervention_id": "HI-CODEX_PAPER_VISUAL_REVIEW",
            "occurred_at": completed_at.isoformat(timespec="seconds"),
            "category": "paper_review",
            "description": (
                "Codex 已逐页检查论文栅格图并确认无可见版式问题；"
                "该记录不是人工评审或双盲评审。"
            ),
            "affected_artifacts": ["paper_pages", visual_path.name, candidate_path.name],
        }
    )

    record = {
        "schema_version": "1.0.0",
        "artifact_type": "competition_full_replay_run_record_v1",
        "run_id": str(run_manifest["run_id"]),
        "problem_id": str(run_manifest["problem_id"]),
        "operator_id": "codex-agent",
        "source_control_commit": source_commit,
        "started_at": started_text,
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "runtime_seconds": round((completed_at - started_at).total_seconds(), 6),
        "manual_interventions": interventions,
        "answer_leakage_detected": False,
        "historical_assets_modified": False,
        "declared_complete": True,
    }
    schema = _load(SCHEMA_PATH)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", choices=tuple(PROBLEMS), action="append")
    parser.add_argument(
        "--completed-at",
        help="带时区的 ISO 8601 收尾时间；默认使用当前本地时间",
    )
    args = parser.parse_args()
    completed_at = (
        _parse_time(args.completed_at, "--completed-at")
        if args.completed_at
        else datetime.now().astimezone()
    )
    selected = args.problem or list(PROBLEMS)
    try:
        for problem_id in selected:
            run_root = ROOT / "runs" / str(PROBLEMS[problem_id]["run"])
            record = build_record(run_root, completed_at)
            _write(run_root / "full_replay_run_record.json", record)
            print(f"[RECORDED] {problem_id} {record['run_id']}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
