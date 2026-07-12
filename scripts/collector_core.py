"""M2 Collector：隔离执行、独立验证，并原子产生 Formal Result 或 Blocker。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator

from canonical_json import CANONICALIZATION_VERSION
from collector_isolation import prepare_isolated_run
from validate_2024c_dryland import validate_decision


ROOT = Path(__file__).resolve().parents[1]
SCOPE = "2024-C-Q1-single-season-dryland-baseline"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象：{path}")
    return value


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _schema(value: dict, schema_name: str) -> None:
    schema = _load(ROOT / "schemas" / schema_name)
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise ValueError("；".join(error.message for error in errors))


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def collect(source_root: Path, result_root: Path) -> dict:
    """不接收 Candidate 路径；仅从白名单输入执行，成功时才原子写正式结果。"""
    collector_id = f"collector-{uuid4().hex}"
    spec_path = source_root / "execution_spec.json"
    spec_hash = _sha(spec_path) if spec_path.is_file() else "0" * 64
    try:
        isolated, input_hashes = prepare_isolated_run(source_root, result_root / "collector_runs")
        spec = _load(isolated / "execution_spec.json")
        task = spec["tasks"][0]
        if spec.get("network_access") is not False or any(".." in arg or Path(arg).is_absolute() for arg in task["argv"]):
            raise ValueError("INVALID_SPEC: 禁止网络、绝对路径和路径穿越")
        env_lock = _load(isolated / "environment_lock.json")
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "TZ": "UTC", "LC_ALL": "C"}
        command = [env_lock.get("python_executable", sys.executable), *task["argv"][1:]]
        completed = subprocess.run(command, cwd=isolated / "workspace", env=env, capture_output=True, timeout=task["timeout_seconds"], check=False)
        stdout = isolated / "stdout.log"; stderr = isolated / "stderr.log"
        stdout.write_bytes(completed.stdout); stderr.write_bytes(completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError("SOLVER_STATUS: 固定入口退出码非零")
        decision = isolated / "workspace" / "output" / "decision_variables.json"
        if not decision.is_file():
            raise RuntimeError("MISSING_DECISION_OUTPUT: 缺少正式决策变量")
        validation = validate_decision(decision, isolated / "materials" / "附件1.xlsx", isolated / "materials" / "附件2.xlsx", isolated / "materials" / "material_manifest.json")
        _schema(validation, "optimization_validation.schema.json")
        if not validation["feasible"]:
            raise RuntimeError("CONSTRAINT_VIOLATION: 独立数值验证失败")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        formal_id = f"formal-{uuid4().hex}"
        final_dir = result_root / "formal_results" / formal_id
        staging = result_root / ".formal-staging" / formal_id
        staging.mkdir(parents=True, exist_ok=False)
        shutil.copy2(decision, staging / "decision_variables.json")
        _write_atomic(staging / "optimization_validation.json", validation)
        manifest = {
            "contract_version": "formal_result_v1", "schema_version": "1.0.0", "scope": SCOPE,
            "formal_result_id": formal_id, "collector_run_id": collector_id, "task_id": task["task_id"],
            "execution_spec_sha256": _sha(isolated / "execution_spec.json"), "material_manifest_sha256": _sha(isolated / "materials" / "material_manifest.json"),
            "source_material_hashes": {key: value for key, value in input_hashes.items() if key.startswith("materials/")},
            "data_extraction_contract_sha256": validation["data_extraction_contract_sha256"], "model_route_sha256": _sha(isolated / "model_route_v2.json"),
            "code_commit": commit, "code_tree_sha256": _tree_hash(isolated / "workspace" / "code"), "environment_sha256": _sha(isolated / "environment_lock.json"),
            "validator_sha256": _sha(ROOT / "scripts" / "validate_2024c_dryland.py"), "collector_command": task["argv"],
            "solver": env_lock["solver"], "tie_break_policy": "lexicographic_plot_crop_v1",
            "decision_output": {"path": "decision_variables.json", "sha256": _sha(staging / "decision_variables.json")}, "decision_variables_hash": validation["decision_variables_sha256"],
            "metrics": {"recomputed_objective": validation["objective_recomputed"], "feasible": validation["feasible"]}, "validation": {"path": "optimization_validation.json", "sha256": _sha(staging / "optimization_validation.json")},
            "recomputed_objective": validation["objective_recomputed"], "reported_objective": validation["objective_reported"], "objective_difference": validation["objective_abs_error"], "max_capacity_residual": validation["max_capacity_violation"], "domain_violations": 0, "illegal_combinations": validation["invalid_assignment_count"], "validation_status": "passed", "stdout_hash": _sha(stdout), "stderr_hash": _sha(stderr), "canonicalization_version": CANONICALIZATION_VERSION, "created_by": "collector", "candidate_output_used": False,
        }
        _schema(manifest, "formal_result_manifest.schema.json")
        _write_atomic(staging / "formal_result_manifest.json", manifest)
        final_dir.parent.mkdir(parents=True, exist_ok=True); staging.replace(final_dir)
        return manifest
    except Exception as exc:
        code = str(exc).split(":", 1)[0] if ":" in str(exc) else "UNKNOWN"
        blocker = {"contract_version": "collector_blocker_v1", "schema_version": "1.0.0", "scope": SCOPE, "candidate_output_used": False, "collector_run_id": collector_id, "task_id": "Q1_DRYLAND_BASELINE", "execution_spec_sha256": spec_hash, "failed_phase": "independent_validation", "blocker_code": {"CONSTRAINT_VIOLATION": "CAPACITY_CONSTRAINT_VIOLATION"}.get(code, code if code in {"INVALID_SPEC", "SOLVER_STATUS", "MISSING_DECISION_OUTPUT"} else "UNKNOWN"), "message": str(exc), "expected": {}, "actual": {}, "input_hashes": {}, "retryable": False, "formal_result_generated": False, "unblock_conditions": ["修正合同、代码或输入后创建新的 Collector 运行" ]}
        _schema(blocker, "collector_blocker_manifest.schema.json")
        _write_atomic(result_root / "collector_blockers" / f"{collector_id}.json", blocker)
        return blocker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--result-root", required=True, type=Path)
    args = parser.parse_args()
    result = collect(args.source_root, args.result_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("contract_version") == "formal_result_v1" else 2


if __name__ == "__main__":
    raise SystemExit(main())
