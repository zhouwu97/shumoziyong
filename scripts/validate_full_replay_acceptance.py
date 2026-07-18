"""验证完整官方旧题回放；简化代理或未实现 Validator 必须失败关闭。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from validate_problem_specific_evidence import (  # noqa: E402
    ProblemValidatorError,
    run_problem_validator,
)
from validate_semantic_map import validate_paper_semantics  # noqa: E402
from verify_materials import verify_materials  # noqa: E402


CONTRACT_PATH = ROOT / "runtime_contracts/competition_full_replay_acceptance_v1.json"
REQUIREMENTS_PATH = ROOT / "runtime_contracts/problem_replay_requirements_registry_v1.json"
VALIDATORS_PATH = ROOT / "runtime_contracts/problem_validator_registry_v1.json"
SEMANTICS_PATH = ROOT / "runtime_contracts/problem_semantics_registry_v1.json"


class FullReplayAcceptanceError(ValueError):
    """完整回放输入不可信或不满足结构合同。"""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FullReplayAcceptanceError(f"JSON 顶层必须是对象：{path}")
    return value


def _schema(value: Mapping[str, Any], name: str) -> None:
    schema = _load(ROOT / "schemas" / name)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise FullReplayAcceptanceError(f"{name} 校验失败：{location}: {error.message}")


def _safe(root: Path, relative: str, label: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative or ":" in relative:
        raise FullReplayAcceptanceError(f"{label} 路径不安全")
    path = root.joinpath(*pure.parts)
    try:
        path.resolve(strict=True).relative_to(root.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise FullReplayAcceptanceError(f"{label} 不存在或越出根目录") from exc
    return path


def _verify_ref(root: Path, ref: Mapping[str, Any], label: str) -> Path:
    path = _safe(root, str(ref["path"]), label)
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        raise FullReplayAcceptanceError(f"{label} SHA-256 漂移")
    return path


def _entry(registry: Mapping[str, Any], problem_id: str) -> Mapping[str, Any]:
    entries = [item for item in registry["problems"] if item["problem_id"] == problem_id]
    if len(entries) != 1:
        raise FullReplayAcceptanceError(f"{problem_id} 未在完整回放要求中唯一登记")
    return entries[0]


def evaluate_acceptance(manifest: Mapping[str, Any], *, workspace_root: Path) -> dict[str, Any]:
    """逐题执行官方材料、附件、专用复算和论文语义验收。"""
    _schema(manifest, "competition_full_replay_acceptance_manifest.schema.json")
    contract = _load(CONTRACT_PATH)
    _schema(contract, "competition_full_replay_acceptance.schema.json")
    requirements = _load(REQUIREMENTS_PATH)
    _schema(requirements, "problem_replay_requirements_registry.schema.json")
    validator_registry = _load(VALIDATORS_PATH)
    _schema(validator_registry, "problem_validator_registry.schema.json")
    semantics_registry = _load(SEMANTICS_PATH)
    _schema(semantics_registry, "problem_semantics_registry.schema.json")

    expected_contract = {
        "path": "runtime_contracts/competition_full_replay_acceptance_v1.json",
        "sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
    }
    if manifest["contract"] != expected_contract:
        raise FullReplayAcceptanceError("完整回放 manifest 未绑定当前准入合同")

    case_results: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        problem_id = str(case["problem_id"])
        requirement = _entry(requirements, problem_id)
        case_root = _safe(workspace_root, str(case["case_root"]), "case_root")
        material_root = _safe(workspace_root, str(case["material_root"]), "material_root")
        failures: set[str] = set()

        material_check = verify_materials(material_root, expected_problem_id=problem_id)
        materials_complete = bool(material_check.ready)
        if not materials_complete:
            failures.add("FRA_OFFICIAL_MATERIALS_INCOMPLETE")
        if set(case["subproblem_ids"]) != set(requirement["subproblem_ids"]):
            failures.add("FRA_ORIGINAL_SUBPROBLEMS_INCOMPLETE")

        output_ids = [str(item["output_id"]) for item in case["outputs"]]
        if len(output_ids) != len(set(output_ids)) or set(output_ids) != set(
            requirement["required_output_ids"]
        ):
            failures.add("FRA_REQUIRED_OUTPUT_SET_INCOMPLETE")
        output_refs: list[dict[str, str]] = []
        for output in case["outputs"]:
            _verify_ref(case_root, output["file"], f"输出 {output['output_id']}")
            output_refs.append(dict(output["file"]))

        validator_path = _verify_ref(case_root, case["validator_report"], "题目专用 Validator 报告")
        validator_report = _load(validator_path)
        try:
            verified_validator = run_problem_validator(
                validator_report,
                case_root=case_root,
                registry=validator_registry,
            )
            if verified_validator["status"] != "passed":
                failures.add("FRA_PROBLEM_VALIDATOR_FAILED")
        except ProblemValidatorError:
            failures.add("FRA_PROBLEM_VALIDATOR_FAILED")

        semantic_map_path = _verify_ref(case_root, case["semantic_map"], "论文语义映射")
        semantic_report = validate_paper_semantics(
            _load(semantic_map_path), semantics_registry, root=case_root
        )
        semantic_report_path = case_root / "paper_semantic_report_v1.json"
        semantic_report_path.write_text(
            json.dumps(semantic_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if semantic_report["status"] != "passed":
            failures.add("FRA_PAPER_SEMANTICS_FAILED")

        _verify_ref(case_root, case["paper_pdf"], "完整题目论文 PDF")
        case_results.append(
            {
                "problem_id": problem_id,
                "run_id": case["run_id"],
                "official_materials_complete": materials_complete,
                "all_original_subproblems": list(case["subproblem_ids"]),
                "required_outputs": output_refs,
                "problem_validator_report": dict(case["validator_report"]),
                "paper_semantic_report": {
                    "path": semantic_report_path.relative_to(case_root).as_posix(),
                    "sha256": hashlib.sha256(semantic_report_path.read_bytes()).hexdigest(),
                },
                "paper_pdf": dict(case["paper_pdf"]),
                "status": "failed" if failures else "passed",
                "failure_codes": sorted(failures),
            }
        )

    passed = bool(case_results) and all(item["status"] == "passed" for item in case_results)
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "competition_full_replay_acceptance_report_v1",
        "campaign_id": manifest["campaign_id"],
        "capability_id": "competition_production_v1",
        "contract": expected_contract,
        "cases": case_results,
        "status": "passed" if passed else "failed",
        "derived_lifecycle": (
            "full_replay_passed" if passed else "integration_fixture_campaign_passed"
        ),
        "new_problem_default_enabled": False,
    }
    _schema(report, "competition_full_replay_acceptance_report.schema.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate_acceptance(_load(args.manifest), workspace_root=args.workspace_root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, FullReplayAcceptanceError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
