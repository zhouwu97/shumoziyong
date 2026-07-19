"""独立执行每问 Checker，并生成与当前 Result 摘要绑定的 Verification。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .result_ledger import load_json, result_digest, stable_json_bytes, validate_result


def _normalise_check(check_id: str, value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"status": "failed", "summary": f"Checker 未返回对象：{check_id}"}
    status = str(value.get("status", "failed"))
    if status not in {"passed", "failed"}:
        status = "failed"
    return {"status": status, "summary": str(value.get("summary", "未提供摘要"))}


def _resource_check(run_dir: Path, result: dict[str, Any]) -> dict[str, str]:
    missing: list[str] = []
    for field in ("tables", "figures", "attachments"):
        for resource in result.get(field, []):
            relative = resource.get("path") if isinstance(resource, dict) else resource
            if not (run_dir / str(relative)).is_file():
                missing.append(str(relative))
    if missing:
        return {"status": "failed", "summary": "缺少声明资源：" + ", ".join(missing)}
    return {"status": "passed", "summary": "Result 声明的资源均存在"}


def _run_checker(run_dir: Path, question_dir: Path, checker: str) -> dict[str, Any]:
    checker_path = (run_dir / checker).resolve()
    try:
        checker_path.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Checker 必须位于运行目录内：{checker}") from exc
    if not checker_path.is_file():
        raise FileNotFoundError(f"Checker 不存在：{checker}")
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(checker_path), "--run-dir", str(run_dir), "--question-dir", str(question_dir)],
        cwd=run_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Checker 退出码 {completed.returncode}：{completed.stderr.strip()}")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict) or not isinstance(value.get("checks"), dict):
        raise ValueError("Checker 标准输出必须是含 checks 对象的 JSON")
    return value


def verify_question(run_dir: Path, question: dict[str, Any], mode: str) -> dict[str, Any]:
    qid = str(question["id"]).lower()
    question_dir = run_dir / "questions" / qid
    result_path = question_dir / "results" / "result.json"
    result = validate_result(load_json(result_path), qid)
    checks: dict[str, dict[str, str]] = {
        "result_integrity": {"status": "passed", "summary": "Result 结构与数值类型有效"},
        "declared_resources": _resource_check(run_dir, result),
    }
    checker = question.get("checker")
    if checker:
        try:
            returned = _run_checker(run_dir, question_dir, str(checker))
            for check_id, value in returned["checks"].items():
                checks[str(check_id)] = _normalise_check(str(check_id), value)
        except Exception as exc:  # Verification 必须将 Checker 故障记录为检查失败。
            checks["checker_execution"] = {"status": "failed", "summary": str(exc)}

    requested = {str(item["id"]) for item in result.get("check_requests", [])}
    requested.update(str(item) for item in question.get("required_checks", []) if mode == "contest_standard")
    for check_id in sorted(requested):
        if check_id not in checks:
            checks[check_id] = {"status": "failed", "summary": "所需检查未由 Checker 提供"}

    verification = {
        "question_id": qid,
        "checked_result_digest": result_digest(result),
        "checker": str(checker or "contest_v2.verification.generic"),
        "checks": {key: checks[key] for key in sorted(checks)},
    }
    output = result_path.with_name("verification.json")
    output.write_bytes(stable_json_bytes(verification))
    return verification
