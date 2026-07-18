from __future__ import annotations

import json
import sys
from argparse import Namespace
from hashlib import sha256
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_workflow import (  # noqa: E402
    _paper_content_contract_binding,
    create_full_replay_run,
    extend_paper_content_evidence_requirements,
    verify_run,
)


def test_2025c_prediction_run_binding_freezes_merged_and_source_hashes() -> None:
    version, contract_id, merged_sha, resolution, source_hashes, path = (
        _paper_content_contract_binding("2025-C", "prediction")
    )

    assert version == "1.0.0"
    assert contract_id == "2025_C_prediction_nipt_v1"
    assert merged_sha and len(merged_sha) == 64
    assert resolution == "1.0.0"
    assert source_hashes and "2025_C_prediction_nipt_v1" in source_hashes
    assert path is not None and path.name == "2025_C_prediction_nipt_v1.yaml"


def test_unmatched_prediction_problem_fails_closed_before_run_creation() -> None:
    with pytest.raises(ValueError, match="缺少唯一论文内容合同"):
        _paper_content_contract_binding("unregistered-problem", "prediction")


def test_unregistered_prediction_run_is_rejected_before_creating_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="缺少唯一论文内容合同"):
        create_full_replay_run(
            Namespace(
                run_id="unregistered_prediction",
                output_root=str(tmp_path / "runs"),
                problem="unregistered-problem",
                profile="prediction",
                gates="0-5",
                materials=str(tmp_path / "materials"),
                candidate_patch=[],
                exclude_patch=[],
                material_file=[],
                promotion_evidence=False,
                experiment_group_id=None,
                experiment_role=None,
                target_patch=None,
                workflow="full_replay",
                mode="standard",
            )
        )
    assert not (tmp_path / "runs").exists()


def test_bound_prediction_run_initializes_before_future_gate_f_files_exist(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    materials.mkdir()
    problem = b"2025-C fixture problem"
    (materials / "problem.pdf").write_bytes(problem)
    (materials / "material_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "1.0.0",
                "problem_id": "2025-C",
                "material_root": ".",
                "source": {"kind": "official", "reference": "https://example.com"},
                "contains_answer_or_solution": False,
                "categories": {
                    "problem": {
                        "required": True,
                        "files": [{"path": "problem.pdf", "sha256": sha256(problem).hexdigest()}],
                    },
                    "attachments": {"required": False, "files": []},
                    "templates": {"required": False, "files": []},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run_dir, ready = create_full_replay_run(
        Namespace(
            run_id="bound_2025c_initialization",
            output_root=str(tmp_path / "runs"),
            problem="2025-C",
            profile="prediction",
            gates="0-5",
            materials=str(materials),
            candidate_patch=[],
            exclude_patch=[],
            material_file=[],
            promotion_evidence=False,
            experiment_group_id=None,
            experiment_role=None,
            target_patch=None,
            workflow="full_replay",
            mode="standard",
        )
    )

    assert ready is True
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["paper_content_contract_id"] == "2025_C_prediction_nipt_v1"
    evidence = json.loads((run_dir / "run_evidence_manifest.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in evidence["artifacts"]}
    assert "paper_content_contract" in roles
    assert "paper_evidence_role_registry" not in roles
    assert not (run_dir / "paper_gate_f_status.json").exists()
    report = verify_run(run_dir)
    assert not any("paper_gate_f_status.json" in error for error in report["promotion_readiness_errors"])


def test_bound_run_adds_gate_f_artifacts_to_final_evidence_requirements(tmp_path: Path) -> None:
    (tmp_path / "run_manifest.json").write_text(
        json.dumps({"paper_content_contract_id": "2025_C_prediction_nipt_v1"}),
        encoding="utf-8",
    )
    required: dict[str, str] = {}
    extend_paper_content_evidence_requirements(tmp_path, required)

    assert required == {
        "paper_content_contract": "paper_content_contract.yaml",
        "paper_evidence_role_registry": "paper_evidence_role_registry.json",
        "paper_substantive_completeness_report": "paper_substantive_completeness_report.json",
        "paper_content_delta_report": "paper_content_delta_report.json",
        "paper_gate_f_status": "paper_gate_f_status.json",
    }
