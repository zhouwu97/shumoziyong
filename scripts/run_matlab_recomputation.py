"""执行 v2.1 MATLAB Level A/B 独立复算并生成机器可读报告。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
MATLAB_SOURCE_ROOT = ROOT / "matlab" / "v21"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def locate_matlab() -> Path | None:
    """只接受真实 MATLAB 可执行文件，不回退到 Python 或 Octave。"""
    candidates = [os.environ.get("MATLAB_EXE"), shutil.which("matlab"), r"E:\Matlab\bin\matlab.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def _checked_ref(
    run_dir: Path,
    ref: Mapping[str, Any],
    label: str,
    *,
    allow_workspace_external: bool = False,
) -> dict[str, str]:
    path_text = ref.get("path")
    expected_sha = ref.get("sha256")
    if not isinstance(path_text, str) or not path_text:
        raise ValueError(f"{label}.path 不能为空")
    path = (run_dir / path_text).resolve()
    if allow_workspace_external and not path.is_file():
        path = (ROOT / path_text).resolve()
    allowed = path.is_relative_to(run_dir.resolve()) or (
        allow_workspace_external and path.is_relative_to(ROOT.resolve())
    )
    if not allowed or not path.is_file():
        raise ValueError(f"{label} 不在当前 Run 内或文件不存在：{path_text}")
    actual_sha = sha256_file(path)
    if expected_sha != actual_sha:
        raise ValueError(f"{label} SHA-256 不匹配：{path_text}")
    return {"path": path_text.replace("\\", "/"), "sha256": actual_sha}


def validate_input(run_dir: Path, value: Mapping[str, Any], expected_level: str) -> dict[str, Any]:
    if value.get("schema_version") != "1.0.0":
        raise ValueError("MATLAB 复算输入 schema_version 必须为 1.0.0")
    if value.get("level") != expected_level:
        raise ValueError(f"MATLAB 复算输入 level 必须为 {expected_level}")
    if value.get("run_id") != json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8")).get("run_id"):
        raise ValueError("MATLAB 复算输入 run_id 与当前 Run 不一致")
    official_refs = [
        _checked_ref(
            run_dir,
            ref,
            f"official_input_refs[{index}]",
            allow_workspace_external=True,
        )
        for index, ref in enumerate(value.get("official_input_refs", []))
    ]
    if not official_refs:
        raise ValueError("MATLAB 复算至少需要一个官方输入引用")
    python_ref = _checked_ref(run_dir, value.get("python_result_ref", {}), "python_result_ref")
    tolerances = value.get("tolerances")
    if not isinstance(tolerances, dict) or not tolerances:
        raise ValueError("MATLAB 复算输入必须声明数值容差")
    additional_refs: dict[str, dict[str, str]] = {}
    if expected_level == "A" and value.get("model_kind") == "rgv_2018b":
        contract = value.get("rgv_contract")
        if not isinstance(contract, Mapping):
            raise ValueError("2018-B MATLAB Level A 必须包含 rgv_contract")
        for field in (
            "parameters_ref",
            "schedules_ref",
            "events_ref",
            "constraint_self_check_ref",
        ):
            additional_refs[field] = _checked_ref(
                run_dir,
                contract.get(field, {}),
                f"rgv_contract.{field}",
            )
        run_contracts = contract.get("run_contracts")
        if not isinstance(run_contracts, list) or not run_contracts:
            raise ValueError("2018-B MATLAB Level A 必须声明非空 run_contracts")
    return {
        "official_input_refs": official_refs,
        "python_result_ref": python_ref,
        "additional_input_refs": additional_refs,
    }


def _matlab_literal(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def copy_matlab_script(run_dir: Path, level: str) -> Path:
    source = MATLAB_SOURCE_ROOT / f"v21_level_{level.lower()}.m"
    if not source.is_file():
        raise FileNotFoundError(f"MATLAB 入口脚本不存在：{source}")
    target = run_dir / "matlab" / "scripts" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def write_blocker(output_path: Path, *, level: str, reason: str) -> Path:
    blocker_path = output_path.with_suffix(".blocker.json")
    write_json(
        blocker_path,
        {
            "schema_version": "1.0.0",
            "artifact_type": "matlab_recomputation_blocker",
            "level": level,
            "status": "blocked",
            "reason": reason,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )
    return blocker_path


def run_recomputation(run_dir: Path, input_path: Path, output_path: Path, level: str) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    value = json.loads(input_path.read_text(encoding="utf-8"))
    refs = validate_input(run_dir, value, level)
    matlab = locate_matlab()
    if matlab is None:
        raise RuntimeError("MATLAB executable not found；禁止用 Python/Octave 冒充 MATLAB 证据")

    script_path = copy_matlab_script(run_dir, level)
    raw_path = output_path.with_name(output_path.stem + ".raw.json")
    log_path = output_path.with_name(output_path.stem + ".matlab.log")
    function_name = f"v21_level_{level.lower()}"
    command = (
        f"addpath('{_matlab_literal(script_path.parent)}');"
        f"{function_name}('{_matlab_literal(input_path)}','{_matlab_literal(raw_path)}')"
    )
    completed = subprocess.run(
        [str(matlab), "-batch", command],
        cwd=run_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    log_path.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode != 0 or not raw_path.is_file():
        raise RuntimeError(f"MATLAB Level {level} 执行失败，日志：{log_path.relative_to(run_dir)}")

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    checks = raw.get("checks", [])
    if not isinstance(checks, list) or not checks:
        raise ValueError("MATLAB 未返回任何数值检查")
    status = "passed" if all(item.get("passed") is True for item in checks) else "failed"
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "matlab_recomputation",
        "run_id": value["run_id"],
        "backend": "matlab",
        "level": level,
        "independent_from_python": True,
        "official_input_refs": refs["official_input_refs"],
        "python_result_ref": refs["python_result_ref"],
        "checks": checks,
        "tolerances": value["tolerances"],
        "status": status,
        "full_model_solved": level == "C",
        "matlab_version": str(raw.get("matlab_version", "unknown")),
        "script_ref": {
            "path": script_path.relative_to(run_dir).as_posix(),
            "sha256": sha256_file(script_path),
        },
    }
    if refs["additional_input_refs"]:
        report["additional_input_refs"] = refs["additional_input_refs"]
    if level == "B":
        report["small_example_ids"] = [
            str(item["case_id"]) for item in value.get("small_examples", [])
        ]
    write_json(output_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行 v2.1 MATLAB Level A/B 独立复算")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--level", required=True, choices=("A", "B"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)
    output = Path(args.output) if args.output else run_dir / f"matlab_level_{args.level.lower()}_report.json"
    try:
        report = run_recomputation(run_dir, Path(args.input), output, args.level)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        blocker = write_blocker(output, level=args.level, reason=str(exc))
        print(f"[BLOCKED] {exc}\nblocker={blocker}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
