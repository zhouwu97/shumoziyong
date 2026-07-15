"""在父进程控制下执行可信 Gate 3 Validator 并生成执行证明。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SCHEMA_PATH = ROOT / "schemas" / "gate_3_validator_contract.schema.json"
INPUT_MANIFEST_SCHEMA_PATH = ROOT / "schemas" / "gate_3_input_manifest.schema.json"
EXECUTION_ATTESTATION_SCHEMA_PATH = (
    ROOT / "schemas" / "gate_3_execution_attestation.schema.json"
)
EVIDENCE_FILENAME = "gate_3_check_evidence.json"
VALIDATION_DIRNAME = "validation"
INPUT_MANIFEST_FILENAME = "input_manifest.json"
REPORT_FILENAME = "report.json"
ATTESTATION_FILENAME = "execution_attestation.json"
STDOUT_FILENAME = "stdout.log"
STDERR_FILENAME = "stderr.log"


class Gate3ExecutionError(RuntimeError):
    """父进程无法建立可信 Gate 3 执行链时抛出。"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _schema_errors(value: Any, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
        for error in errors
    ]


def _resolve_within(root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative.strip():
        return None
    path = (root / relative).resolve()
    return path if path.is_relative_to(root.resolve()) else None


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Gate3ExecutionError(f"{label} 无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise Gate3ExecutionError(f"{label} 必须是 JSON 对象")
    return value


def _load_trusted_contract(
    contract_relative: str,
) -> tuple[Path, dict[str, Any], Path, Path]:
    validator_root = (ROOT / "validators").resolve()
    contract_path = _resolve_within(ROOT, contract_relative)
    if contract_path is None or not contract_path.is_relative_to(validator_root):
        raise Gate3ExecutionError("Validator Contract 不在可信 validators 目录内")
    if not contract_path.is_file():
        raise Gate3ExecutionError("Validator Contract 文件不存在")
    contract = _load_object(contract_path, "Validator Contract")
    schema_errors = _schema_errors(contract, CONTRACT_SCHEMA_PATH)
    if schema_errors:
        raise Gate3ExecutionError("Validator Contract 不符合 Schema：" + "；".join(schema_errors))

    validator_path = _resolve_within(ROOT, contract["validator_path"])
    if validator_path is None or not validator_path.is_relative_to(validator_root):
        raise Gate3ExecutionError("Validator 不在可信 validators 目录内")
    if not validator_path.is_file() or _sha256(validator_path) != contract["validator_sha256"]:
        raise Gate3ExecutionError("Validator SHA-256 与可信 Contract 不一致")

    report_schema_path = _resolve_within(ROOT, contract["report_schema_path"])
    if report_schema_path is None or not report_schema_path.is_relative_to(validator_root):
        raise Gate3ExecutionError("Validator 报告 Schema 不在可信 validators 目录内")
    if (
        not report_schema_path.is_file()
        or _sha256(report_schema_path) != contract["report_schema_sha256"]
    ):
        raise Gate3ExecutionError("Validator 报告 Schema SHA-256 与可信 Contract 不一致")
    try:
        Draft202012Validator.check_schema(
            json.loads(report_schema_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise Gate3ExecutionError(f"Validator 报告 Schema 无效：{exc}") from exc

    supported = set(contract["supported_check_ids"])
    for field in ("required_observations", "check_types", "observation_rules"):
        declared = set(contract[field])
        if declared != supported:
            raise Gate3ExecutionError(
                f"Validator Contract.{field} 必须精确覆盖 supported_check_ids"
            )
    for check_id in supported:
        required = set(contract["required_observations"][check_id])
        rules = set(contract["observation_rules"][check_id])
        if required != rules:
            raise Gate3ExecutionError(
                f"Validator Contract.{check_id} 的 observation 规则集合不完整"
            )
    for role, limits in contract["required_input_roles"].items():
        maximum = limits.get("max_items")
        if maximum is not None and int(maximum) < int(limits["min_items"]):
            raise Gate3ExecutionError(
                f"Validator Contract 输入角色 {role} 的 max_items 小于 min_items"
            )
    return contract_path, contract, validator_path, report_schema_path


def _build_input_manifest(
    run_dir: Path,
    contract: Mapping[str, Any],
    input_artifacts: Mapping[str, Sequence[str]],
) -> dict[str, object]:
    if not input_artifacts:
        raise Gate3ExecutionError("Gate 3 输入集合不能为空")
    required_roles = contract["required_input_roles"]
    assert isinstance(required_roles, Mapping)
    actual_roles = set(input_artifacts)
    expected_roles = set(required_roles)
    if contract["exact_input_set"]:
        extra_roles = actual_roles - expected_roles
        if extra_roles:
            raise Gate3ExecutionError(f"Gate 3 存在额外输入角色：{sorted(extra_roles)}")

    artifacts: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    run_root = run_dir.resolve()
    validation_root = (run_root / VALIDATION_DIRNAME).resolve()
    roles_to_process = list(required_roles)
    if not contract["exact_input_set"]:
        roles_to_process.extend(sorted(actual_roles - expected_roles))
    for role in roles_to_process:
        limits_value = required_roles.get(role, {})
        limits = limits_value if isinstance(limits_value, Mapping) else {}
        paths = input_artifacts.get(role, ())
        if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence):
            raise Gate3ExecutionError(f"Gate 3 输入角色 {role} 必须绑定路径列表")
        minimum = int(limits.get("min_items", 0))
        maximum_value = limits.get("max_items")
        maximum = int(maximum_value) if maximum_value is not None else None
        if len(paths) < minimum:
            raise Gate3ExecutionError(
                f"Gate 3 输入角色 {role} 至少需要 {minimum} 项，实际 {len(paths)} 项"
            )
        if maximum is not None and len(paths) > maximum:
            raise Gate3ExecutionError(
                f"Gate 3 输入角色 {role} 最多允许 {maximum} 项，实际 {len(paths)} 项"
            )
        for relative in paths:
            path = _resolve_within(run_root, relative)
            if path is None:
                raise Gate3ExecutionError(f"Gate 3 输入路径越出当前 Run：{relative!r}")
            if path.is_relative_to(validation_root):
                raise Gate3ExecutionError(f"Gate 3 输入不得引用父进程输出目录：{relative}")
            if not path.is_file():
                raise Gate3ExecutionError(f"Gate 3 输入文件不存在：{relative}")
            normalized = path.relative_to(run_root).as_posix()
            if normalized in seen_paths:
                raise Gate3ExecutionError(f"Gate 3 输入文件重复绑定：{normalized}")
            seen_paths.add(normalized)
            artifacts.append({"role": role, "path": normalized, "sha256": _sha256(path)})

    manifest: dict[str, object] = {
        "schema_version": "1.0.0",
        "artifacts": artifacts,
    }
    errors = _schema_errors(manifest, INPUT_MANIFEST_SCHEMA_PATH)
    if errors:
        raise Gate3ExecutionError("父进程生成的 Input Manifest 无效：" + "；".join(errors))
    return manifest


def _sanitized_environment() -> dict[str, str]:
    allowed = (
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def _captured_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _comparison_holds(value: float, comparison: str, threshold: float) -> bool:
    if comparison == "le":
        return value <= threshold
    if comparison == "lt":
        return value < threshold
    if comparison == "ge":
        return value >= threshold
    if comparison == "gt":
        return value > threshold
    if comparison == "eq":
        return value == threshold
    if comparison == "ne":
        return value != threshold
    raise Gate3ExecutionError(f"Validator Contract comparison 非法：{comparison!r}")


def _build_evidence(
    contract_relative: str,
    contract_path: Path,
    contract: Mapping[str, Any],
    report: Mapping[str, Any],
    attestation_path: Path,
    attestation: Mapping[str, Any],
) -> dict[str, object]:
    report_checks = report.get("checks")
    if not isinstance(report_checks, list):
        raise Gate3ExecutionError("Validator Report 缺少 checks 列表")
    sections: dict[str, Mapping[str, Any]] = {}
    for item in report_checks:
        if not isinstance(item, Mapping) or not isinstance(item.get("check_id"), str):
            raise Gate3ExecutionError("Validator Report 包含非法检查区段")
        check_id = str(item["check_id"])
        if check_id in sections:
            raise Gate3ExecutionError(f"Validator Report 检查区段重复：{check_id}")
        sections[check_id] = item
    supported = list(contract["supported_check_ids"])
    if set(sections) != set(supported):
        raise Gate3ExecutionError("Validator Report 必须精确覆盖 Contract supported_check_ids")

    checks: list[dict[str, object]] = []
    for check_id in supported:
        raw_observations = sections[check_id].get("observations")
        if not isinstance(raw_observations, list):
            raise Gate3ExecutionError(f"Validator Report.{check_id} 缺少 observations")
        values: dict[str, float] = {}
        for item in raw_observations:
            if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
                raise Gate3ExecutionError(f"Validator Report.{check_id} observation 非法")
            name = str(item["name"])
            if name in values or not isinstance(item.get("value"), (int, float)):
                raise Gate3ExecutionError(
                    f"Validator Report.{check_id} observation 重复或数值非法：{name}"
                )
            values[name] = float(item["value"])
        required = list(contract["required_observations"][check_id])
        if set(values) != set(required):
            raise Gate3ExecutionError(
                f"Validator Report.{check_id} 必须精确包含 Contract observations"
            )
        observations: list[dict[str, object]] = []
        for name in required:
            rule = contract["observation_rules"][check_id][name]
            comparison = str(rule["comparison"])
            threshold = float(rule["threshold"])
            value = values[name]
            passed = _comparison_holds(value, comparison, threshold)
            observations.append(
                {
                    "name": name,
                    "value": value,
                    "comparison": comparison,
                    "threshold": threshold,
                    "passed": passed,
                }
            )
        checks.append(
            {
                "check_id": check_id,
                "check_type": contract["check_types"][check_id],
                "validator_path": contract["validator_path"],
                "validator_sha256": contract["validator_sha256"],
                "validator_contract_path": contract_relative,
                "validator_contract_sha256": _sha256(contract_path),
                "input_manifest_path": attestation["input_manifest_path"],
                "input_manifest_sha256": attestation["input_manifest_sha256"],
                "report_path": attestation["report_path"],
                "report_sha256": attestation["report_sha256"],
                "exit_code": attestation["exit_code"],
                "observations": observations,
                "passed": all(bool(item["passed"]) for item in observations),
            }
        )
    return {
        "schema_version": "1.0.0",
        "execution_attestation_path": f"{VALIDATION_DIRNAME}/{ATTESTATION_FILENAME}",
        "execution_attestation_sha256": _sha256(attestation_path),
        "checks": checks,
    }


def execute_gate_3_validator(
    run_dir: Path,
    validator_contract_path: str,
    input_artifacts: Mapping[str, Sequence[str]],
) -> dict[str, object]:
    """从 Run 已绑定文件构造输入，执行可信 Validator 并生成最终 Evidence。"""
    run_root = run_dir.resolve()
    if not run_root.is_dir():
        run_root.mkdir(parents=True, exist_ok=True)
    contract_path, contract, validator_path, report_schema_path = _load_trusted_contract(
        validator_contract_path
    )
    canonical_contract_path = contract_path.relative_to(ROOT.resolve()).as_posix()
    input_manifest = _build_input_manifest(run_root, contract, input_artifacts)

    validation_dir = run_root / VALIDATION_DIRNAME
    validation_dir.mkdir(exist_ok=True)
    input_manifest_path = validation_dir / INPUT_MANIFEST_FILENAME
    report_path = validation_dir / REPORT_FILENAME
    attestation_path = validation_dir / ATTESTATION_FILENAME
    stdout_path = validation_dir / STDOUT_FILENAME
    stderr_path = validation_dir / STDERR_FILENAME
    evidence_path = run_root / EVIDENCE_FILENAME
    for stale_path in (
        input_manifest_path,
        report_path,
        attestation_path,
        stdout_path,
        stderr_path,
        evidence_path,
    ):
        if stale_path.exists():
            if not stale_path.is_file():
                raise Gate3ExecutionError(f"父进程输出路径不是普通文件：{stale_path}")
            stale_path.unlink()
    _write_json(input_manifest_path, input_manifest)

    argv = [
        sys.executable,
        str(validator_path),
        "--input-manifest",
        INPUT_MANIFEST_FILENAME,
        "--report",
        REPORT_FILENAME,
    ]
    started_at = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    status = "completed"
    exit_code = 0
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            argv,
            cwd=validation_dir,
            env=_sanitized_environment(),
            timeout=float(contract["timeout_seconds"]),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        if exit_code != 0:
            status = "nonzero_exit"
    except subprocess.TimeoutExpired as exc:
        status = "timed_out"
        exit_code = -1
        stdout = _captured_text(exc.stdout)
        stderr = _captured_text(exc.stderr)
    ended_at = datetime.now(timezone.utc)
    duration = time.monotonic() - started_clock
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    report: dict[str, Any] | None = None
    if status == "completed":
        if not report_path.is_file():
            status = "missing_report"
        else:
            report = _load_object(report_path, "Validator Report")
            report_errors = _schema_errors(report, report_schema_path)
            if report_errors:
                status = "invalid_report"

    attestation: dict[str, object] = {
        "schema_version": "1.0.0",
        "status": status,
        "validator_path": contract["validator_path"],
        "validator_sha256": contract["validator_sha256"],
        "validator_contract_path": canonical_contract_path,
        "validator_contract_sha256": _sha256(contract_path),
        "argv": argv,
        "cwd": VALIDATION_DIRNAME,
        "python_executable": sys.executable,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": duration,
        "exit_code": exit_code,
        "stdout_path": f"{VALIDATION_DIRNAME}/{STDOUT_FILENAME}",
        "stdout_sha256": _sha256(stdout_path),
        "stderr_path": f"{VALIDATION_DIRNAME}/{STDERR_FILENAME}",
        "stderr_sha256": _sha256(stderr_path),
        "input_manifest_path": f"{VALIDATION_DIRNAME}/{INPUT_MANIFEST_FILENAME}",
        "input_manifest_sha256": _sha256(input_manifest_path),
        "report_path": f"{VALIDATION_DIRNAME}/{REPORT_FILENAME}",
        "report_sha256": _sha256(report_path) if report_path.is_file() else None,
    }
    attestation_errors = _schema_errors(attestation, EXECUTION_ATTESTATION_SCHEMA_PATH)
    if attestation_errors:
        raise Gate3ExecutionError("父进程生成的执行证明无效：" + "；".join(attestation_errors))
    _write_json(attestation_path, attestation)

    if status == "timed_out":
        raise Gate3ExecutionError(
            f"Gate 3 Validator 执行超时：{contract['timeout_seconds']} 秒"
        )
    if status == "nonzero_exit":
        raise Gate3ExecutionError(f"Gate 3 Validator 退出码不是 0：{exit_code}")
    if status == "missing_report":
        raise Gate3ExecutionError("Gate 3 Validator 未生成新 Report")
    if status == "invalid_report":
        assert report is not None
        raise Gate3ExecutionError(
            "Gate 3 Validator Report 不符合可信 Schema："
            + "；".join(_schema_errors(report, report_schema_path))
        )
    assert report is not None

    evidence = _build_evidence(
        canonical_contract_path,
        contract_path,
        contract,
        report,
        attestation_path,
        attestation,
    )
    _write_json(evidence_path, evidence)
    from gate3_evidence import validate_gate_3_check_evidence

    evidence_errors = validate_gate_3_check_evidence(evidence, run_root)
    if evidence_errors:
        evidence_path.unlink(missing_ok=True)
        raise Gate3ExecutionError("执行后 Gate 3 Evidence 复核失败：" + "；".join(evidence_errors))
    return evidence
