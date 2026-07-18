from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_workflow import (  # noqa: E402
    _paper_content_contract_binding,
    extend_paper_content_evidence_requirements,
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


def test_unmatched_problem_has_no_implicit_legacy_content_binding() -> None:
    version, contract_id, merged_sha, resolution, source_hashes, path = (
        _paper_content_contract_binding("unregistered-problem", "prediction")
    )

    assert version == "1.0.0"
    assert contract_id is None
    assert merged_sha is None
    assert resolution is None
    assert source_hashes is None
    assert path is None


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
