"""汇总 A092 阶段三确认性实验并生成可提交证据。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = ROOT / "experiments" / "a092_confirmatory_v1"
RUN_ROOT = EXPERIMENT_ROOT / "runs"
WORK_ROOT = ROOT / "tmp" / "a092_confirmatory_v1"
R10_ROOT = ROOT / "tmp" / "a092_confirmatory_v1" / "R10"

RUN_SPECS: dict[str, dict[str, Any]] = {
    "R01": {"sequence": 1, "problem": "2024-C", "arm": "baseline", "pair": "positive_1"},
    "R02": {"sequence": 2, "problem": "2024-C", "arm": "treatment", "pair": "positive_1"},
    "R03": {"sequence": 3, "problem": "2024-C", "arm": "treatment", "pair": "positive_2"},
    "R04": {"sequence": 4, "problem": "2024-C", "arm": "baseline", "pair": "positive_2"},
    "R05": {"sequence": 5, "problem": "2023-B", "arm": "treatment", "pair": "boundary_1"},
    "R06": {"sequence": 6, "problem": "2023-B", "arm": "baseline", "pair": "boundary_1"},
    "R07": {"sequence": 7, "problem": "2023-B", "arm": "baseline", "pair": "boundary_2"},
    "R08": {"sequence": 8, "problem": "2023-B", "arm": "treatment", "pair": "boundary_2"},
    "R09": {"sequence": 9, "problem": "2016-C", "arm": "baseline", "pair": "negative_1"},
    "R10": {"sequence": 10, "problem": "2016-C", "arm": "treatment", "pair": "negative_1"},
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    """用固定 LF 写出聚合证据，保证跨平台哈希稳定。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _artifact(run_id: str, relative_path: str) -> Path:
    """优先读取归档；归档早于外部审计时回退到同 run_id 工作副本。"""

    archived = RUN_ROOT / run_id / relative_path
    if archived.is_file():
        return archived
    working = WORK_ROOT / run_id / relative_path
    if working.is_file():
        return working
    raise FileNotFoundError(f"运行 {run_id} 缺少证据文件: {relative_path}")


def _completed_run(run_id: str) -> dict[str, Any]:
    metadata_path = _artifact(run_id, "runner_metadata.json")
    validator_path = _artifact(run_id, "gate3/validator_independent.json")
    isolation_path = _artifact(run_id, "gate5/isolation_audit.json")
    metadata = _load(metadata_path)
    validator = _load(validator_path)
    isolation = _load(isolation_path)
    entry = {
        **RUN_SPECS[run_id],
        "run_id": run_id,
        "execution_status": "completed",
        "return_code": metadata["return_code"],
        "model": metadata["model"],
        "model_reasoning_effort": metadata["model_reasoning_effort"],
        "sampling_control": metadata["sampling_control"],
        "prompt_sha256": metadata["prompt_sha256"],
        "runner_metadata_sha256": _sha256(metadata_path),
        "validator_sha256": _sha256(validator_path),
        "independent_validator_valid": validator["valid"],
        "isolation_valid": isolation["valid"],
        "usage": metadata.get("usage", {}),
    }
    if run_id in {"R01", "R02"}:
        entry["classification"] = "solution_p0"
        entry["reason"] = "四个正控场景均未通过目标复算，且部分场景存在关键约束违约。"
    elif run_id in {"R05", "R06", "R07", "R08"}:
        entry["classification"] = "solution_p0"
        entry["max_absolute_difference"] = validator["max_absolute_difference"]
        entry["reason"] = "边界题正式结果未通过冻结解析适配器。"
    else:
        entry["classification"] = "experiment_invalid"
        entry["reason"] = "同一会话内不同脚本版本并发执行并覆盖正式产物。"
        entry["eligible_for_patch_effect_estimate"] = False
    return entry


def _r10_attempt() -> dict[str, Any]:
    metadata_path = R10_ROOT / "runner_metadata.json"
    events_path = R10_ROOT / "runner_events.jsonl"
    stderr_path = R10_ROOT / "runner_stderr.log"
    metadata = _load(metadata_path)
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    error_message = next(
        event["message"] for event in events if event.get("type") == "error" and "usage limit" in event.get("message", "")
    )
    return {
        **RUN_SPECS["R10"],
        "run_id": "R10",
        "execution_status": "failed_before_model_work",
        "classification": "experiment_invalid",
        "return_code": metadata["return_code"],
        "model": metadata["model"],
        "model_reasoning_effort": metadata["model_reasoning_effort"],
        "sampling_control": metadata["sampling_control"],
        "prompt_sha256": metadata["prompt_sha256"],
        "runner_metadata_sha256": _sha256(metadata_path),
        "runner_events_sha256": _sha256(events_path),
        "runner_stderr_sha256": _sha256(stderr_path),
        "usage": metadata.get("usage", {}),
        "reason": "Codex 用量上限导致 turn.failed；提示可在 2026-07-20 08:31 后重试。",
        "error_message": error_message,
        "eligible_for_patch_effect_estimate": False,
    }


def build() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    runs = [_completed_run(run_id) for run_id in ("R01", "R02")]
    for run_id in ("R03", "R04"):
        runs.append(
            {
                **RUN_SPECS[run_id],
                "run_id": run_id,
                "execution_status": "skipped_by_frozen_screening_rule",
                "classification": "not_run",
                "reason": "R02 Treatment 出现 Solution P0，按协议停止正控后续重复。",
            }
        )
    runs.extend(_completed_run(run_id) for run_id in ("R05", "R06", "R07", "R08", "R09"))
    runs.append(_r10_attempt())
    manifest = {
        "schema_version": "1.0.0",
        "experiment_id": "a092_confirmatory_v1",
        "private_mapping": True,
        "runs": runs,
    }
    aggregate = {
        "schema_version": "1.0.0",
        "experiment_id": "a092_confirmatory_v1",
        "completed_model_runs": 7,
        "skipped_runs": ["R03", "R04"],
        "invalid_runs": ["R09", "R10"],
        "solution_p0_runs": ["R01", "R02", "R05", "R06", "R07", "R08"],
        "clean_valid_pairs": [],
        "positive_screening": {
            "status": "failed",
            "treatment_solution_p0": True,
            "second_pair_skipped": True,
        },
        "boundary_confirmatory": {
            "status": "failed",
            "completed_pairs": 2,
            "all_independent_validators_failed": True,
            "adapter_scope_risk": "四次最大偏差均约 705.584，需在下一轮预注册前复核方向定义。",
        },
        "negative_control": {
            "status": "experiment_invalid",
            "baseline_numeric_validator_valid": True,
            "baseline_semantics_safe": True,
            "treatment_completed": False,
        },
        "blind_scoring": {
            "status": "not_performed",
            "reason": "无干净有效配对可用于晋级，且独立 Codex 评审在 R10 前已触发用量上限。",
            "promotion_impact": "不影响失败结论；硬门槛已明确不满足。",
        },
        "promotion_conditions_met": False,
        "final_patch_status": "review_ready",
        "decision": "do_not_promote",
        "required_follow_up": [
            "在下一轮预注册前复核 2023-B 方向与深度符号约定。",
            "修复长命令超时后孤立子进程并发覆盖问题。",
            "额度恢复后以冻结或重新预注册的完整协议重跑负控 Treatment。",
            "修订 A092 后重新 Pilot，再启动新的确认性实验版本。",
        ],
    }
    blind_status = aggregate["blind_scoring"]
    return manifest, aggregate, blind_status


def main() -> int:
    manifest, aggregate, blind_status = build()
    evidence_snapshots: dict[str, Any] = {}
    for run_id in ("R01", "R02", "R05", "R06", "R07", "R08", "R09"):
        snapshot = {
            "runner_metadata": _load(_artifact(run_id, "runner_metadata.json")),
            "validator_independent": _load(_artifact(run_id, "gate3/validator_independent.json")),
            "isolation_audit": _load(_artifact(run_id, "gate5/isolation_audit.json")),
        }
        external = RUN_ROOT / run_id / "gate5" / "external_experiment_validity.json"
        if external.is_file():
            snapshot["external_experiment_validity"] = _load(external)
        evidence_snapshots[run_id] = snapshot
    evidence_snapshots["R10"] = next(run for run in manifest["runs"] if run["run_id"] == "R10")
    outputs = {
        EXPERIMENT_ROOT / "experiment_manifest_private.json": manifest,
        EXPERIMENT_ROOT / "aggregate_results.json": aggregate,
        EXPERIMENT_ROOT / "blind_scoring_status.json": blind_status,
        EXPERIMENT_ROOT / "evidence_snapshots.json": evidence_snapshots,
        EXPERIMENT_ROOT / "invalid_attempts" / "R10_usage_limit" / "attempt_summary.json": next(
            run for run in manifest["runs"] if run["run_id"] == "R10"
        ),
    }
    for path, payload in outputs.items():
        _write_json(path, payload)
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
