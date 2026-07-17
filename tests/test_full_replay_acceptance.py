from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_integration_fixture_campaign import _material  # noqa: E402
from test_paper_semantic_map import _fixture as semantic_fixture  # noqa: E402
from test_problem_specific_validator import _report as validator_report_fixture  # noqa: E402
from validate_full_replay_acceptance import CONTRACT_PATH, evaluate_acceptance  # noqa: E402


def _write_json(path: Path, value: object) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": path.relative_to(path.parents[0]).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _ref(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_scaffold_validator_blocks_full_replay_promotion(tmp_path: Path) -> None:
    _material(tmp_path, "2023-B", "2023_B")
    semantic_map, _registry = semantic_fixture(tmp_path)
    semantic_path = tmp_path / "semantic_map.json"
    semantic_path.write_text(json.dumps(semantic_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    variables = tmp_path / "variables.json"
    variables.write_text('{"direction": 90, "overlap": 0.15}\n', encoding="utf-8")
    output_ids = ["result1.xlsx", "result2.xlsx", "q3_route_plan", "q4_route_plan_and_coverage"]
    outputs = []
    for output_id in output_ids:
        output_path = tmp_path / "outputs" / output_id
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"fixture-{output_id}".encode())
        outputs.append({"output_id": output_id, "file": _ref(tmp_path, output_path)})

    validator_report = validator_report_fixture()
    validator_report["official_materials"] = _ref(
        tmp_path, tmp_path / "official_materials/2023_B/material_manifest.json"
    )
    validator_report["decision_variables"] = _ref(tmp_path, variables)
    validator_report["required_outputs"] = [outputs[0]["file"]]
    validator_path = tmp_path / "validator_report.json"
    validator_path.write_text(
        json.dumps(validator_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paper_pdf = tmp_path / "paper.pdf"
    paper_pdf.write_bytes(b"%PDF-1.4 fixture")

    manifest = {
        "schema_version": "1.0.0",
        "campaign_id": "full-replay-test-2023b",
        "contract": {
            "path": "runtime_contracts/competition_full_replay_acceptance_v1.json",
            "sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
        },
        "cases": [
            {
                "problem_id": "2023-B",
                "run_id": "full-replay-test-2023b",
                "case_root": ".",
                "material_root": "official_materials/2023_B",
                "subproblem_ids": ["Q1", "Q2", "Q3", "Q4"],
                "outputs": outputs,
                "validator_report": _ref(tmp_path, validator_path),
                "semantic_map": _ref(tmp_path, semantic_path),
                "paper_pdf": _ref(tmp_path, paper_pdf),
            }
        ],
    }
    report = evaluate_acceptance(manifest, workspace_root=tmp_path)
    assert report["status"] == "failed"
    assert report["derived_lifecycle"] == "integration_fixture_campaign_passed"
    assert report["cases"][0]["failure_codes"] == ["FRA_PROBLEM_VALIDATOR_FAILED"]
