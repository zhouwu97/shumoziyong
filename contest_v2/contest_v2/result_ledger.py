"""Result 解析与派生 Ledger 的唯一实现。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any


METRIC_ID = re.compile(r"[a-z][a-z0-9_]*$")
QUESTION_ID = re.compile(r"q[1-9][0-9]*$")
FORBIDDEN_ASSERTIONS = {"verified", "verification_passed", "checks_passed"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 对象存在重复键：{key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    """读取 JSON，并拒绝会被普通解析器静默覆盖的重复键。"""
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError(f"顶层必须是 JSON 对象：{path}")
    return value


def stable_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def result_digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(stable_json_bytes(value)).hexdigest()


def _relative_path(value: str, field: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"{field} 必须是运行目录内相对路径：{value}")
    return path.as_posix()


def _assert_no_self_verification(value: Any, location: str = "result") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_ASSERTIONS:
                raise ValueError(f"Result 禁止自行声明验证通过：{location}.{key}")
            _assert_no_self_verification(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_self_verification(child, f"{location}[{index}]")


@dataclass(frozen=True)
class ResultEntry:
    question_id: str
    metric_id: str
    value: int | float | str | bool
    unit: str
    format: dict[str, Any]
    display_value: str
    verification: str

    @property
    def key(self) -> str:
        return f"{self.question_id}_{self.metric_id}"


def format_metric(value: int | float | str | bool, spec: dict[str, Any]) -> str:
    scale = spec.get("scale", 1)
    decimals = spec.get("decimals")
    suffix = str(spec.get("suffix", "")).strip()
    if isinstance(value, bool):
        text = "是" if value else "否"
    elif isinstance(value, (int, float)):
        shown = value / scale
        if decimals is None:
            text = str(shown if not float(shown).is_integer() else int(shown))
        else:
            text = f"{shown:.{decimals}f}"
    else:
        text = value
    return f"{text} {suffix}".strip()


def validate_result(value: dict[str, Any], expected_question_id: str | None = None) -> dict[str, Any]:
    _assert_no_self_verification(value)
    question_id = str(value.get("question_id", "")).lower()
    if not QUESTION_ID.fullmatch(question_id):
        raise ValueError(f"非法 question_id：{question_id!r}")
    if expected_question_id and question_id != expected_question_id.lower():
        raise ValueError(f"Result question_id={question_id}，预期 {expected_question_id.lower()}")
    if value.get("status") != "complete":
        raise ValueError("Result status 必须是 complete")
    metrics = value.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("Result metrics 必须是非空对象")
    for metric_id, metric in metrics.items():
        if not METRIC_ID.fullmatch(metric_id):
            raise ValueError(f"非法指标名：{metric_id}")
        if not isinstance(metric, dict) or "value" not in metric:
            raise ValueError(f"指标 {metric_id} 缺少 value")
        raw = metric["value"]
        if not isinstance(raw, (int, float, str, bool)) or raw is None:
            raise ValueError(f"指标 {metric_id} 的 value 类型不受支持")
        if isinstance(raw, float) and not math.isfinite(raw):
            raise ValueError(f"指标 {metric_id} 必须是有限浮点数")
        if not isinstance(metric.get("unit", ""), str):
            raise ValueError(f"指标 {metric_id} 的 unit 必须是字符串")
        spec = metric.get("format", {})
        if not isinstance(spec, dict):
            raise ValueError(f"指标 {metric_id} 的 format 必须是对象")
        scale = spec.get("scale", 1)
        if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not math.isfinite(float(scale)) or scale == 0:
            raise ValueError(f"指标 {metric_id} 的 scale 必须是有限非零数")
        decimals = spec.get("decimals")
        if decimals is not None and (not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 10):
            raise ValueError(f"指标 {metric_id} 的 decimals 必须是 0--10 的整数")
        if not isinstance(spec.get("suffix", ""), str):
            raise ValueError(f"指标 {metric_id} 的 suffix 必须是字符串")
    requests = value.get("check_requests", [])
    if not isinstance(requests, list):
        raise ValueError("check_requests 必须是数组")
    request_ids: set[str] = set()
    for request in requests:
        if not isinstance(request, dict) or not METRIC_ID.fullmatch(str(request.get("id", ""))):
            raise ValueError(f"非法 check_request：{request!r}")
        request_id = str(request["id"])
        if request_id in request_ids:
            raise ValueError(f"重复 check_request：{request_id}")
        request_ids.add(request_id)
    for field in ("tables", "figures", "attachments"):
        resources = value.get(field, [])
        if not isinstance(resources, list):
            raise ValueError(f"{field} 必须是数组")
        for resource in resources:
            path = resource.get("path") if isinstance(resource, dict) else resource
            _relative_path(str(path), field)
    if not isinstance(value.get("warnings", []), list):
        raise ValueError("warnings 必须是数组")
    return value


def verification_status(result: dict[str, Any], verification_path: Path) -> str:
    if not verification_path.is_file():
        return "unchecked"
    try:
        verification = load_json(verification_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return "failed"
    if verification.get("checked_result_digest") != result_digest(result):
        return "stale"
    requested = {str(item["id"]) for item in result.get("check_requests", [])}
    checks = verification.get("checks", {})
    if not isinstance(checks, dict):
        return "failed"
    # 一次 Verification 快照中的任何失败都必须使整问失败，不能被请求列表掩盖。
    if any(not isinstance(check, dict) or check.get("status") != "passed" for check in checks.values()):
        return "failed"
    required_snapshot = requested | {"result_integrity", "declared_resources"}
    if any(checks.get(check_id, {}).get("status") != "passed" for check_id in required_snapshot):
        return "failed"
    return "verified"


def load_question_configs(run_dir: Path, contest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """读取唯一的问级配置源，并拒绝 contest.json 内嵌副本。"""
    contest = contest or load_json(run_dir / "contest.json")
    if "questions" in contest:
        raise ValueError("contest.json 不得内嵌 questions；请只声明 question_ids")
    question_ids = contest.get("question_ids")
    if not isinstance(question_ids, list) or not question_ids:
        raise ValueError("contest.json question_ids 必须是非空数组")
    normalised = [str(item).lower() for item in question_ids]
    if len(normalised) != len(set(normalised)):
        raise ValueError("contest.json question_ids 不得重复")
    questions: list[dict[str, Any]] = []
    for qid in normalised:
        if not QUESTION_ID.fullmatch(qid):
            raise ValueError(f"非法 question id：{qid}")
        question = load_json(run_dir / "questions" / qid / "question.json")
        if str(question.get("id", "")).lower() != qid:
            raise ValueError(f"{qid}/question.json 的 id 不一致")
        questions.append(question)
    return questions


class ResultLedger:
    """可删除后完整重建的当前结果快照。"""

    def __init__(self, contest_id: str, entries: list[ResultEntry]) -> None:
        self.contest_id = contest_id
        self.entries = sorted(entries, key=lambda item: (item.question_id, item.metric_id))
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("Ledger 指标键冲突")

    def to_dict(self) -> dict[str, Any]:
        return {"version": "2.0", "contest_id": self.contest_id, "entries": [asdict(item) | {"key": item.key} for item in self.entries]}

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stable_json_bytes(self.to_dict()))

    @classmethod
    def load(cls, path: Path) -> "ResultLedger":
        value = load_json(path)
        if value.get("version") != "2.0" or "append_only" in value:
            raise ValueError("不支持的 Ledger 版本或旧 append-only Ledger")
        entries = []
        for raw in value.get("entries", []):
            data = {key: raw[key] for key in ("question_id", "metric_id", "value", "unit", "format", "display_value", "verification")}
            entries.append(ResultEntry(**data))
        return cls(str(value["contest_id"]), entries)


def build_ledger(run_dir: Path) -> ResultLedger:
    contest = load_json(run_dir / "contest.json")
    entries: list[ResultEntry] = []
    for question in sorted(load_question_configs(run_dir, contest), key=lambda item: str(item["id"])):
        qid = str(question["id"]).lower()
        result_path = run_dir / "questions" / qid / "results" / "result.json"
        if not result_path.is_file():
            if question.get("required", True):
                raise FileNotFoundError(f"必答问题缺少 Result：{qid}")
            continue
        result = validate_result(load_json(result_path), qid)
        state = verification_status(result, result_path.with_name("verification.json"))
        for metric_id, metric in result["metrics"].items():
            spec = dict(metric.get("format", {}))
            entries.append(ResultEntry(qid, metric_id, metric["value"], metric.get("unit", ""), spec, format_metric(metric["value"], spec), state))
    return ResultLedger(str(contest.get("contest_id", run_dir.name)), entries)


def rebuild_ledger(run_dir: Path) -> ResultLedger:
    ledger = build_ledger(run_dir)
    ledger.write(run_dir / "result_ledger.json")
    return ledger
