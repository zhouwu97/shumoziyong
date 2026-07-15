from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUTPUTS = ROOT / "outputs"
EVIDENCE = RESULTS / "language_execution"
MATLAB_DEFAULT = Path(r"E:\Matlab\bin\matlab.exe")

PYTHON_COMMANDS = [
    [sys.executable, "code/run_training.py"],
    [sys.executable, "code/final_human_audit.py", "audit"],
    [sys.executable, "code/final_human_audit.py", "excel"],
]
MATLAB_BATCH = "addpath('code/matlab'); run_cross_language_validation(pwd)"

SHARED_INPUTS = [
    ROOT / "materials" / "附件1 近5年402家供应商的相关数据.xlsx",
    ROOT / "materials" / "附件2 近5年8家转运商的相关数据.xlsx",
]

EVIDENCE_FILENAMES = [
    "dual_language_execution.json",
    "cross_language_validation.json",
    "dual_language_check.json",
    "python_execution_record.json",
    "matlab_execution_record.json",
    "python_source_manifest.json",
    "matlab_source_manifest.json",
    "shared_input_manifest.json",
    "python_output_manifest.json",
    "matlab_output_manifest.json",
    "python.stdout.log",
    "python.stderr.log",
    "matlab.stdout.log",
    "matlab.stderr.log",
]


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return payload


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": relative(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def write_manifest(path: Path, manifest_id: str, files: list[Path]) -> dict[str, str]:
    missing = [str(item) for item in files if not item.is_file()]
    if missing:
        raise FileNotFoundError(f"Manifest 文件缺失: {missing}")
    payload = {
        "schema_version": "1.0.0",
        "manifest_id": manifest_id,
        "generated_at": iso_time(now_local()),
        "root": ".",
        "files": [file_record(item) for item in sorted(files, key=relative)],
    }
    write_json(path, payload)
    return {"path": relative(path), "sha256": sha256(path)}


def assert_manifest_files_current(path: Path) -> None:
    manifest = read_json(path)
    mismatches = []
    for item in manifest.get("files", []):
        source = ROOT / item["path"]
        actual = sha256(source) if source.is_file() else None
        if actual != item.get("sha256"):
            mismatches.append(
                {"path": item.get("path"), "expected": item.get("sha256"), "actual": actual}
            )
    if mismatches:
        raise RuntimeError(f"Manifest 文件在执行期间发生漂移: {mismatches}")


def archive_previous_evidence() -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = now_local().strftime("%Y%m%dT%H%M%S%z")
    archive = EVIDENCE / "archive" / f"pre_attempt_02_{stamp}"
    candidates = [EVIDENCE / name for name in EVIDENCE_FILENAMES]
    candidates.extend(
        [
            RESULTS / "cross_language_validation.json",
            RESULTS / "cross_language_validation.csv",
            RESULTS / "matlab_execution_record.json",
        ]
    )
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        return archive
    archive.mkdir(parents=True, exist_ok=False)
    for source in existing:
        target = archive / source.name
        if target.exists():
            target = archive / f"results_{source.name}"
        shutil.move(str(source), str(target))
    return archive


def source_files(pattern: str) -> list[Path]:
    return [path for path in ROOT.glob(pattern) if path.is_file()]


def command_display(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def run_commands(
    commands: list[list[str]], stdout_path: Path, stderr_path: Path
) -> tuple[datetime, datetime, int]:
    started = now_local()
    exit_code = 0
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        for index, command in enumerate(commands, start=1):
            marker = f"===== command {index}: {command_display(command)} =====\n".encode("utf-8")
            stdout_handle.write(marker)
            stderr_handle.write(marker)
            result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
            stdout_handle.write(result.stdout)
            stderr_handle.write(result.stderr)
            stdout_handle.write(b"\n")
            stderr_handle.write(b"\n")
            stdout_handle.flush()
            stderr_handle.flush()
            exit_code = result.returncode
            if exit_code != 0:
                break
    return started, now_local(), exit_code


def package_records() -> list[dict[str, str]]:
    records = []
    for distribution in ("numpy", "scipy", "pandas", "openpyxl", "matplotlib"):
        records.append(
            {"name": distribution, "version": importlib.metadata.version(distribution)}
        )
    return records


def python_output_files() -> list[Path]:
    excluded = {
        RESULTS / "cross_language_validation.json",
        RESULTS / "matlab_execution_record.json",
    }
    files = [path for path in RESULTS.glob("*.json") if path not in excluded]
    files.extend(OUTPUTS.glob("*.xlsx"))
    files.extend([ROOT / "assumptions.json", ROOT / "score.json"])
    return [path for path in files if path.is_file()]


def matlab_output_files() -> list[Path]:
    return [
        RESULTS / "cross_language_validation.json",
        RESULTS / "cross_language_validation.csv",
        RESULTS / "matlab_execution_record.json",
    ]


def execution_record(
    *,
    language: str,
    role: str,
    version: str,
    packages_key: str,
    packages: list[dict[str, str]],
    commands: list[list[str]],
    started: datetime,
    ended: datetime,
    exit_code: int,
    stdout_path: Path,
    stderr_path: Path,
    source_manifest: dict[str, str],
    input_manifest: dict[str, str],
    output_manifest: dict[str, str],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "language": language,
        "role": role,
        "status": "executed",
        "verification_status": "verified" if exit_code == 0 else "not_verified",
        "execution_observed": True,
        "version": version,
        packages_key: packages,
        "command": [command_display(command) for command in commands],
        "cwd": str(ROOT),
        "started_at": iso_time(started),
        "ended_at": iso_time(ended),
        "duration_seconds": round((ended - started).total_seconds(), 6),
        "exit_code": exit_code,
        "stdout_path": relative(stdout_path),
        "stdout_sha256": sha256(stdout_path),
        "stderr_path": relative(stderr_path),
        "stderr_sha256": sha256(stderr_path),
        "source_manifest": source_manifest,
        "input_manifest": input_manifest,
        "output_manifest": output_manifest,
    }
    if language == "matlab":
        record["isolation"] = {
            "invokes_python": False,
            "reads_python_intermediates": False,
            "input_origin": "shared_official_inputs",
        }
    return record


def find_comparison(raw: dict[str, Any], metric: str) -> dict[str, Any]:
    for comparison in raw.get("comparisons", []):
        if comparison.get("metric") == metric:
            return comparison
    raise KeyError(f"缺少跨语言比较项: {metric}")


def max_python_violation(part: dict[str, Any]) -> float:
    checks = part.get("checks", {})
    values = [float(item.get("max_violation", 0.0)) for item in checks.values()]
    return max(values, default=0.0)


def build_cross_language_contract(
    evidence_id: str,
    python_output: dict[str, str],
    matlab_output: dict[str, str],
) -> dict[str, Any]:
    raw = read_json(RESULTS / "cross_language_validation.json")
    constraints = read_json(RESULTS / "constraint_validation.json")
    objective = find_comparison(raw, "problem2_purchase_cost_24week")

    hard_constraints = []
    for part in ("2", "3", "4"):
        python_part = constraints["by_problem"][part]
        matlab_part = raw["constraints"][f"problem{part}"]
        hard_constraints.append(
            {
                "constraint_id": f"problem{part}_all_hard_constraints",
                "python": {
                    "satisfied": bool(python_part.get("passed")),
                    "max_violation": max_python_violation(python_part),
                },
                "matlab": {
                    "satisfied": matlab_part.get("totalHardViolations") == 0,
                    "max_violation": float(matlab_part.get("maxViolationMagnitude", 0.0)),
                },
                "violation_tolerance": 1e-6,
            }
        )

    aggregates = []
    for metric, aggregate_id, absolute_tolerance in (
        ("problem2_minimum_supplier_count", "selected_supplier_count", 0.0),
        ("problem2_transport_loss_24week", "problem2_transport_loss_24week", 1e-6),
        ("problem3_total_raw_24week", "problem3_total_raw_24week", 1e-6),
        ("problem4_maximum_weekly_capacity", "problem4_weekly_capacity", 1e-6),
    ):
        comparison = find_comparison(raw, metric)
        aggregates.append(
            {
                "aggregate_id": aggregate_id,
                "python_value": comparison["python_value"],
                "matlab_value": comparison["matlab_value"],
                "absolute_tolerance": absolute_tolerance,
                "relative_tolerance": 1e-9,
            }
        )

    solver_status = read_json(RESULTS / "solver_status.json")
    python_optimal = all(item.get("optimality_proven") is True for item in solver_status["models"])
    matlab_optimal = all(
        flag > 0
        for flag in (
            raw["problem2"]["exitflags"]
            + raw["problem3"]["exitflags"]
            + [raw["problem4"]["exitflag"]]
        )
    )
    return {
        "schema_version": "1.0.0",
        "validation_id": f"{evidence_id}-cross-validation",
        "example_only": False,
        "execution_evidence_id": evidence_id,
        "output_manifests": {
            "python_sha256": python_output["sha256"],
            "matlab_sha256": matlab_output["sha256"],
        },
        "objective": {
            "metric": "problem2_purchase_cost_24week",
            "direction": "minimize",
            "python_value": objective["python_value"],
            "matlab_value": objective["matlab_value"],
            "absolute_tolerance": 1e-6,
            "relative_tolerance": 1e-9,
        },
        "hard_constraints": hard_constraints,
        "business_aggregates": aggregates,
        "optimality": {
            "python_status": "proven_optimal" if python_optimal else "not_proven",
            "matlab_status": "proven_optimal" if matlab_optimal else "not_proven",
        },
        "decision_variables": {
            "comparison_mode": "equivalent_optimum",
            "python_manifest_sha256": python_output["sha256"],
            "matlab_manifest_sha256": matlab_output["sha256"],
        },
    }


def write_blocked_matlab_evidence(
    evidence_id: str,
    python_record: dict[str, Any],
    matlab_executable: Path,
) -> None:
    stderr_path = EVIDENCE / "matlab.stderr.log"
    stdout_path = EVIDENCE / "matlab.stdout.log"
    stdout_path.write_bytes(b"")
    stderr_path.write_text(f"MATLAB executable not found: {matlab_executable}\n", encoding="utf-8")
    matlab_record = {
        "language": "matlab",
        "role": "independent_reproducer",
        "status": "blocked_environment",
        "verification_status": "not_verified",
        "execution_observed": False,
        "environment_blocker": {
            "reason": "MATLAB executable not found",
            "probe_command": [str(matlab_executable), "-batch", "version"],
            "observed_stderr_sha256": sha256(stderr_path),
        },
    }
    write_json(EVIDENCE / "matlab_execution_record.json", matlab_record)
    write_json(
        EVIDENCE / "dual_language_execution.json",
        {
            "schema_version": "1.0.0",
            "evidence_id": evidence_id,
            "example_only": False,
            "profile": {
                "profile_id": "cumcm_2021c_python_matlab_v1",
                "required_languages": ["python", "matlab"],
                "language_roles": {
                    "python": "primary_solver",
                    "matlab": "independent_reproducer",
                },
            },
            "executions": {"python": python_record, "matlab": matlab_record},
        },
    )
    write_json(
        EVIDENCE / "cross_language_validation.json",
        {
            "schema_version": "1.0.0",
            "validation_id": f"{evidence_id}-blocked",
            "example_only": False,
            "execution_evidence_id": evidence_id,
        },
    )


def main() -> int:
    archive_previous_evidence()
    evidence_id = f"2021c-attempt02-{now_local().strftime('%Y%m%dT%H%M%S%z')}"

    python_source = write_manifest(
        EVIDENCE / "python_source_manifest.json",
        f"{evidence_id}-python-source",
        source_files("code/**/*.py") + [Path(__file__).resolve()],
    )
    matlab_source = write_manifest(
        EVIDENCE / "matlab_source_manifest.json",
        f"{evidence_id}-matlab-source",
        source_files("code/matlab/*.m"),
    )
    shared_input = write_manifest(
        EVIDENCE / "shared_input_manifest.json",
        f"{evidence_id}-shared-input",
        SHARED_INPUTS,
    )

    python_stdout = EVIDENCE / "python.stdout.log"
    python_stderr = EVIDENCE / "python.stderr.log"
    py_started, py_ended, py_exit = run_commands(
        PYTHON_COMMANDS, python_stdout, python_stderr
    )
    python_output = write_manifest(
        EVIDENCE / "python_output_manifest.json",
        f"{evidence_id}-python-output",
        python_output_files(),
    )
    python_record = execution_record(
        language="python",
        role="primary_solver",
        version=f"Python {platform.python_version()}",
        packages_key="dependencies",
        packages=package_records(),
        commands=PYTHON_COMMANDS,
        started=py_started,
        ended=py_ended,
        exit_code=py_exit,
        stdout_path=python_stdout,
        stderr_path=python_stderr,
        source_manifest=python_source,
        input_manifest=shared_input,
        output_manifest=python_output,
    )
    write_json(EVIDENCE / "python_execution_record.json", python_record)
    if py_exit != 0:
        raise RuntimeError(f"Python 执行失败，退出码 {py_exit}")

    matlab_executable = Path(os.environ.get("MATLAB_EXE", MATLAB_DEFAULT))
    if not matlab_executable.is_file():
        write_blocked_matlab_evidence(evidence_id, python_record, matlab_executable)
        return 2

    matlab_command = [str(matlab_executable), "-batch", MATLAB_BATCH]
    matlab_stdout = EVIDENCE / "matlab.stdout.log"
    matlab_stderr = EVIDENCE / "matlab.stderr.log"
    ml_started, ml_ended, ml_exit = run_commands(
        [matlab_command], matlab_stdout, matlab_stderr
    )
    matlab_output = write_manifest(
        EVIDENCE / "matlab_output_manifest.json",
        f"{evidence_id}-matlab-output",
        matlab_output_files(),
    )
    raw_matlab_record = read_json(RESULTS / "matlab_execution_record.json")
    matlab_record = execution_record(
        language="matlab",
        role="independent_reproducer",
        version=f"MATLAB {raw_matlab_record['matlab_version']}",
        packages_key="toolboxes",
        packages=[
            {
                "name": "Optimization Toolbox",
                "version": str(raw_matlab_record["optimization_toolbox_version"]),
            }
        ],
        commands=[matlab_command],
        started=ml_started,
        ended=ml_ended,
        exit_code=ml_exit,
        stdout_path=matlab_stdout,
        stderr_path=matlab_stderr,
        source_manifest=matlab_source,
        input_manifest=shared_input,
        output_manifest=matlab_output,
    )
    write_json(EVIDENCE / "matlab_execution_record.json", matlab_record)
    if ml_exit != 0:
        raise RuntimeError(f"MATLAB 执行失败，退出码 {ml_exit}")

    dual_language = {
        "schema_version": "1.0.0",
        "evidence_id": evidence_id,
        "example_only": False,
        "profile": {
            "profile_id": "cumcm_2021c_python_matlab_v1",
            "required_languages": ["python", "matlab"],
            "language_roles": {
                "python": "primary_solver",
                "matlab": "independent_reproducer",
            },
        },
        "executions": {"python": python_record, "matlab": matlab_record},
    }
    write_json(EVIDENCE / "dual_language_execution.json", dual_language)
    write_json(
        EVIDENCE / "cross_language_validation.json",
        build_cross_language_contract(evidence_id, python_output, matlab_output),
    )
    for manifest_path in (
        EVIDENCE / "python_source_manifest.json",
        EVIDENCE / "matlab_source_manifest.json",
        EVIDENCE / "shared_input_manifest.json",
        EVIDENCE / "python_output_manifest.json",
        EVIDENCE / "matlab_output_manifest.json",
    ):
        assert_manifest_files_current(manifest_path)
    print(f"双语言执行证据已生成: {EVIDENCE}")
    return 0


def locked_main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    lock_path = EVIDENCE / ".execution.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"已有统一执行器实例运行: {lock_path}") from error
    try:
        os.write(lock_fd, f"pid={os.getpid()}\n".encode("ascii"))
        return main()
    finally:
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    started = time.perf_counter()
    try:
        raise SystemExit(locked_main())
    finally:
        print(f"统一执行器总耗时: {time.perf_counter() - started:.3f} s")
