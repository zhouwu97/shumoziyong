from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_state_consistency import (  # noqa: E402
    check_state_consistency,
    validate_training_log,
)
from render_current_status import (  # noqa: E402
    EVIDENCE_PATH,
    OUTPUT_PATH,
    build_status_model,
    render_current_status,
)


def _evidence() -> dict[str, object]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def _write_evidence(tmp_path: Path, evidence: dict[str, object]) -> Path:
    path = tmp_path / "evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    return path


def _valid_training_log() -> str:
    return (
        "# 历史\n\n历史标签 verified_candidate，不构成当前 Qualification。\n\n"
        "## 当前状态说明\n\n"
        "当前状态由 docs/status/CURRENT_STATUS.md 展示。\n"
        "机器状态源包括 runtime_profiles/engineering_optimization.json。\n"
        "下方历史记录中的 candidate+、stable candidate、verified_candidate 和 L4 "
        "均为旧训练流程标签，不构成当前机器状态或 Profile Qualification。\n"
    )


def test_committed_status_matches_byte_exact_render() -> None:
    assert OUTPUT_PATH.read_bytes() == render_current_status().encode("utf-8")


def test_manual_status_edit_is_rejected(tmp_path: Path) -> None:
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text(render_current_status() + "人工编辑\n", encoding="utf-8")
    errors = check_state_consistency(status_path=status)
    assert any("现场重新渲染结果不一致" in error for error in errors)


def test_missing_evidence_fails_closed(tmp_path: Path) -> None:
    errors = check_state_consistency(evidence_path=tmp_path / "missing.json")
    assert any("缺少Capability Evidence" in error for error in errors)


def test_invalid_evidence_schema_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence()
    del evidence["benchmark"]
    errors = check_state_consistency(evidence_path=_write_evidence(tmp_path, evidence))
    assert any("不符合 Schema" in error for error in errors)


def test_historical_label_is_allowed_but_current_machine_claim_is_rejected() -> None:
    assert validate_training_log(_valid_training_log()) == []
    invalid = _valid_training_log().replace(
        "当前状态由 docs/status/CURRENT_STATUS.md 展示。",
        "当前机器可读状态为 verified_candidate。docs/status/CURRENT_STATUS.md",
    )
    assert any("越级或混用声明" in error for error in validate_training_log(invalid))


def test_empty_qualification_cases_derive_ineligible() -> None:
    model = build_status_model()
    assert model["capability_policy"]["derived_maturity"] == "foundation"
    assert model["capability_policy"]["qualification_eligible"] is False
    assert model["evidence"]["qualification_case_count"] == 0


def test_manual_maturity_or_status_in_evidence_is_rejected(tmp_path: Path) -> None:
    for field in ("maturity", "status", "qualification_eligible"):
        evidence = _evidence()
        evidence[field] = False if field == "qualification_eligible" else "foundation"
        errors = check_state_consistency(evidence_path=_write_evidence(tmp_path / field, evidence))
        assert any("不符合 Schema" in error for error in errors)


def test_render_is_byte_deterministic() -> None:
    assert render_current_status().encode("utf-8") == render_current_status().encode("utf-8")


def test_runtime_and_capability_namespaces_are_separate() -> None:
    model = build_status_model()
    assert model["runtime_profile"]["lifecycle_state"] == "assembled"
    assert model["capability_policy"]["derived_maturity"] == "foundation"

    invalid_comparisons = (
        "assembled 高于 foundation",
        "foundation 覆盖 assembled",
        "因为 runtime assembled，所以 capability qualified",
    )
    for claim in invalid_comparisons:
        invalid = _valid_training_log() + claim
        assert any("越级或混用声明" in error for error in validate_training_log(invalid))


def test_stale_status_after_evidence_change_is_rejected(tmp_path: Path) -> None:
    stale_status = tmp_path / "CURRENT_STATUS.md"
    stale_status.write_text(render_current_status(), encoding="utf-8")
    changed = copy.deepcopy(_evidence())
    foundation_documents = changed["foundation_documents"]
    assert isinstance(foundation_documents, list)
    foundation_documents.remove("roadmap")
    changed_path = _write_evidence(tmp_path, changed)

    errors = check_state_consistency(evidence_path=changed_path, status_path=stale_status)
    assert any("现场重新渲染结果不一致" in error for error in errors)
