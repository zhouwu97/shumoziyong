from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evidence_validation as evidence_module  # noqa: E402
import promotion_engine  # noqa: E402
import promote_patch as promote_patch_module  # noqa: E402
from evaluation_case_registry import (  # noqa: E402
    build_expected_registry,
    validate_registry,
)
from evidence_validation import (  # noqa: E402
    ControlOutcome,
    EvidenceOutcome,
    derive_validated_formal_patch_ids,
    failure_fix_evidence_digest,
    validate_control_evidence,
    validate_formal_patch,
    validate_full_run,
    validate_profile_record,
)
from promotion_engine import EligibilityReport  # noqa: E402


def _write(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_formal_patch_status_must_equal_highest_derived_state(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """真实证据已支持更高状态时，较低手填状态也不得进入正式包。"""
    patch_file = tmp_path / "patch.md"
    patch_file.write_text("verified patch", encoding="utf-8")
    patch_sha = hashlib.sha256(patch_file.read_bytes()).hexdigest()
    _write(
        tmp_path / "card.json",
        {"source": {"verification_status": "verified", "claims": [{"claim_id": "C001"}]}},
    )

    negative_runs = []
    for index in range(2):
        baseline = tmp_path / f"baseline-{index}"
        treatment = tmp_path / f"treatment-{index}"
        _write(baseline / "run_evidence_manifest.json", {"run_id": f"b-{index}"})
        _write(treatment / "run_evidence_manifest.json", {"run_id": f"t-{index}"})
        review = tmp_path / f"review-{index}.json"
        _write(review, {"final_conclusion": "pass"})
        negative_runs.append(
            {
                "experiment_group_id": f"group-{index}",
                "case": f"negative-{index}",
                "baseline_run": baseline.relative_to(tmp_path).as_posix(),
                "treatment_run": treatment.relative_to(tmp_path).as_posix(),
                "comparison_review": review.relative_to(tmp_path).as_posix(),
            }
        )

    failure_id = "F-A999-001"
    failure_sha = _write(
        tmp_path / "failure.json",
        {
            "failure_id": failure_id,
            "target_patch": "A999",
            "retest_run_id": "retest",
            "failure_label": "logic",
        },
    )
    fix_sha = _write(
        tmp_path / "fix.json",
        {
            "failure_id": failure_id,
            "target_patch": "A999",
            "retest_run_id": "retest",
            "fix_description": "fixed",
        },
    )
    retest = tmp_path / "retest"
    retest_manifest_sha = _write(
        retest / "run_evidence_manifest.json", {"run_id": "retest"}
    )
    _write(
        tmp_path / "review-fix.json",
        {
            "failure_id": failure_id,
            "target_patch": "A999",
            "retest_run_id": "retest",
            "fix_record_sha256": fix_sha,
            "evidence_digest": failure_fix_evidence_digest(
                failure_id=failure_id,
                target_patch="A999",
                retest_run_id="retest",
                failure_record_sha256=failure_sha,
                fix_record_sha256=fix_sha,
                retest_evidence_manifest_sha256=retest_manifest_sha,
            ),
            "decision": "approved",
            "reviewer": "human",
        },
    )

    competition_manifest = tmp_path / "competition.manifest.json"
    competition_sha = _write(
        competition_manifest,
        {
            "patches": [
                {
                    "patch_id": "A999",
                    "path": "patch.md",
                    "sha256": patch_sha,
                    "status": "regression_verified",
                }
            ],
            "validation_target_status": "competition_evidenced",
        },
    )
    _write(
        tmp_path / "competition.result.json",
            {
                "result": "pass",
                "target_patch": "A999",
                "runtime_pack_manifest": "competition.manifest.json",
            "runtime_pack_manifest_sha256": competition_sha,
        },
    )

    patch = {
        "patch_id": "A999",
        "status": "regression_verified",
        "file": "patch.md",
        "source": {"knowledge_card": "card.json", "claim_ids": ["C001"]},
        "validation_records": ["validation.json"],
        "stable_evidence": {
            "negative_control_runs": negative_runs,
            "failure_fix_retests": [
                {
                    "failure_id": failure_id,
                    "failure_record": "failure.json",
                    "fix_record": "fix.json",
                    "review_record": "review-fix.json",
                    "retest_run": "retest",
                }
            ],
            "competition_validation_records": [
                {
                    "runtime_pack_manifest": "competition.manifest.json",
                    "runtime_pack_manifest_sha256": competition_sha,
                    "result_record": "competition.result.json",
                }
            ],
            "human_approval_record": {},
        },
    }
    matrix_entry = {
        name: {"case": name, "evidence": {"fixture": True}}
        for name in ("positive", "boundary", "negative")
    }

    monkeypatch.setattr(
        evidence_module,
        "validate_control_evidence",
        lambda *_args, **_kwargs: ControlOutcome(True, result="pass"),
    )
    monkeypatch.setattr(
        evidence_module,
        "validate_full_run",
        lambda *_args, **_kwargs: EvidenceOutcome(
            True, identity={"run_id": "retest"}
        ),
    )
    monkeypatch.setattr(evidence_module, "_schema_errors", lambda *_args: [])

    def eligible(
        candidate: dict[str, Any],
        _entry: dict[str, Any],
        _policy: dict[str, Any],
        target: str,
    ) -> EligibilityReport:
        return EligibilityReport(
            patch_id=str(candidate["patch_id"]),
            current_status=str(candidate["status"]),
            target_status=target,
            eligible=True,
        )

    monkeypatch.setattr(promotion_engine, "evaluate_status_eligibility", eligible)
    outcome = validate_formal_patch(patch, matrix_entry, {}, root=tmp_path)

    assert not outcome.valid
    assert outcome.identity["derived_status"] == "competition_evidenced"
    assert any("记录状态 regression_verified" in error for error in outcome.errors)

    patch["source"]["claim_ids"] = ["C999"]
    missing_claim_outcome = validate_formal_patch(patch, matrix_entry, {}, root=tmp_path)
    assert not missing_claim_outcome.valid
    assert any("Claim ID 不存在" in error for error in missing_claim_outcome.errors)
    patch["source"]["claim_ids"] = ["C001"]

    review_path = tmp_path / "review-fix.json"
    original_review = review_path.read_text(encoding="utf-8")
    mismatched_review = json.loads(original_review)
    mismatched_review["failure_id"] = "F-OTHER-001"
    review_path.write_text(json.dumps(mismatched_review), encoding="utf-8")
    patch["status"] = "competition_evidenced"
    identity_outcome = validate_formal_patch(patch, matrix_entry, {}, root=tmp_path)
    assert not identity_outcome.valid
    assert any("failure_id 不一致" in error for error in identity_outcome.errors)
    review_path.write_text(original_review, encoding="utf-8")

    for field_name, invalid_value, expected_error in (
        ("retest_run_id", "other-run", "retest_run_id"),
        ("fix_record_sha256", "0" * 64, "fix_record_sha256"),
        ("evidence_digest", "0" * 64, "evidence_digest"),
    ):
        invalid_review = json.loads(original_review)
        invalid_review[field_name] = invalid_value
        review_path.write_text(json.dumps(invalid_review), encoding="utf-8")
        binding_outcome = validate_formal_patch(patch, matrix_entry, {}, root=tmp_path)
        assert not binding_outcome.valid
        assert any(expected_error in error for error in binding_outcome.errors)
        review_path.write_text(original_review, encoding="utf-8")

    _write(
        tmp_path / "failure.json",
        {
            "failure_id": failure_id,
            "target_patch": "A999",
            "retest_run_id": "retest",
        },
    )
    semantic_outcome = validate_formal_patch(patch, matrix_entry, {}, root=tmp_path)
    assert not semantic_outcome.valid
    assert any("failure_record" in error for error in semantic_outcome.errors)


def test_full_run_recomputes_automatic_evaluation(
    tmp_path: Path, monkeypatch: Any
) -> None:
    fixture = ROOT / "tests" / "fixtures" / "valid_promotion_evidence" / "baseline"
    run_dir = tmp_path / "run"
    shutil.copytree(fixture, run_dir)
    response_path = run_dir / "response.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["patch_decisions"] = {
        "A999": {"enabled": True, "reason": "forged active patch"}
    }
    response_text = json.dumps(response)
    response_path.write_text(response_text, encoding="utf-8")
    automatic_path = run_dir / "automatic_evaluation.json"
    automatic = json.loads(automatic_path.read_text(encoding="utf-8"))
    automatic.update(
        {
            "result": "pass",
            "errors": [],
            "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
        }
    )
    automatic_path.write_text(json.dumps(automatic), encoding="utf-8")

    import finalize_run_evidence
    import run_workflow

    monkeypatch.setattr(run_workflow, "verify_run_seal", lambda *_args: {})
    monkeypatch.setattr(run_workflow, "verify_gate_artifacts", lambda *_args: {})
    monkeypatch.setattr(
        run_workflow,
        "replay_transition_log",
        lambda *_args: {"completed": True, "max_gate": 5, "transition_version": "2.0.0"},
    )
    monkeypatch.setattr(
        finalize_run_evidence, "validate_evidence_manifest", lambda *_args: []
    )

    outcome = validate_full_run(run_dir, {})

    assert not outcome.valid
    assert any("response.json diagnosis.schema.json" in error for error in outcome.errors)
    assert any("现场重算" in error for error in outcome.errors), outcome.errors


def _bypass_full_run_integrity(monkeypatch: Any) -> None:
    """隔离自动评估绑定测试，避免无关 Seal 细节干扰断言。"""
    import finalize_run_evidence
    import run_workflow

    monkeypatch.setattr(run_workflow, "verify_run_seal", lambda *_args: {})
    monkeypatch.setattr(run_workflow, "verify_gate_artifacts", lambda *_args: {})
    monkeypatch.setattr(
        run_workflow,
        "replay_transition_log",
        lambda *_args: {"completed": True, "max_gate": 5, "transition_version": "2.0.0"},
    )
    monkeypatch.setattr(
        finalize_run_evidence, "validate_evidence_manifest", lambda *_args: []
    )


def test_full_run_rejects_diagnosis_below_policy_minimum(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """普通 v2 晋级路径不能接受低于 Policy 下限的 Diagnosis v1。"""
    fixture = ROOT / "tests" / "fixtures" / "valid_promotion_evidence" / "baseline"
    run_dir = tmp_path / "run"
    shutil.copytree(fixture, run_dir)
    response_path = run_dir / "response.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["schema_version"] = "1.0.0"
    response_text = json.dumps(response)
    response_path.write_text(response_text, encoding="utf-8")
    automatic_path = run_dir / "automatic_evaluation.json"
    automatic = json.loads(automatic_path.read_text(encoding="utf-8"))
    automatic["response_sha256"] = hashlib.sha256(
        response_text.encode("utf-8")
    ).hexdigest()
    automatic_path.write_text(json.dumps(automatic), encoding="utf-8")
    _bypass_full_run_integrity(monkeypatch)

    outcome = validate_full_run(
        run_dir,
        {"diagnosis_schema_requirements": {"minimum_schema_version": "2.0.0"}},
    )

    assert not outcome.valid
    assert any("低于晋级证据最低版本" in error for error in outcome.errors)


def test_authorized_case_role_and_target_must_match_run_context(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """授权 YAML 不能跨 baseline/treatment 或跨目标 Patch 复用。"""
    baseline_fixture = ROOT / "tests" / "fixtures" / "valid_promotion_evidence" / "baseline"
    treatment_fixture = ROOT / "tests" / "fixtures" / "valid_promotion_evidence" / "treatment"
    baseline_dir = tmp_path / "baseline"
    treatment_dir = tmp_path / "treatment"
    shutil.copytree(baseline_fixture, baseline_dir)
    shutil.copytree(treatment_fixture, treatment_dir)
    # 把 treatment 授权用例记录放到 baseline 运行，记录内部仍然自洽。
    shutil.copy2(
        treatment_fixture / "automatic_evaluation.json",
        baseline_dir / "automatic_evaluation.json",
    )
    treatment_manifest_path = treatment_dir / "run_manifest.json"
    treatment_manifest = json.loads(treatment_manifest_path.read_text(encoding="utf-8"))
    treatment_manifest["target_patch"] = "A999"
    treatment_manifest_path.write_text(json.dumps(treatment_manifest), encoding="utf-8")
    _bypass_full_run_integrity(monkeypatch)

    baseline_outcome = validate_full_run(
        baseline_dir, {}, expected_role="baseline"
    )
    treatment_outcome = validate_full_run(
        treatment_dir,
        {},
        expected_role="patch_only",
        expected_target_patch="A999",
    )

    assert not baseline_outcome.valid
    assert any("control_type 与运行角色" in error for error in baseline_outcome.errors)
    assert not treatment_outcome.valid
    assert any("target_patch 与运行目标 Patch" in error for error in treatment_outcome.errors)


def test_registry_generator_rejects_crlf_and_only_derives_hash(
    tmp_path: Path,
) -> None:
    """更新器不能把 CRLF 工作区字节重新写成可信哈希。"""
    case_path = tmp_path / "case.yaml"
    case_path.write_bytes(
        b"cases:\r\n  - case_id: C001\r\n    expected:\r\n      values:\r\n        primary_type: optimization\r\n"
    )
    registry = {
        "registry_version": "1.0.0",
        "evaluator_version": "1.2.0",
        "cases": [
            {
                "case_id": "C001",
                "case_file": "case.yaml",
                "case_sha256": "0" * 64,
                "control_type": "full_run",
                "target_patch": None,
                "minimum_assertion_count": 1,
            }
        ],
    }

    assert any("不是 LF 文件" in issue for issue in validate_registry(registry, root=tmp_path))
    with pytest.raises(ValueError, match="不是 LF 文件"):
        build_expected_registry(registry, root=tmp_path)

    case_path.write_bytes(case_path.read_bytes().replace(b"\r\n", b"\n"))
    expected = build_expected_registry(registry, root=tmp_path)
    assert expected["cases"][0]["case_sha256"] != registry["cases"][0]["case_sha256"]
    assert expected["cases"][0]["control_type"] == "full_run"
    assert expected["cases"][0]["minimum_assertion_count"] == 1


def test_full_run_rejects_unregistered_or_empty_evaluation_case(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """晋级评估不得把任意 YAML 或空断言用例伪装成可信用例。"""
    fixture = ROOT / "tests" / "fixtures" / "valid_promotion_evidence" / "baseline"
    run_dir = tmp_path / "run"
    shutil.copytree(fixture, run_dir)
    empty_case = tmp_path / "empty.yaml"
    empty_case.write_text(
        "cases:\n  - case_id: empty_case\n    expected:\n      patch_not_applicable: {}\n",
        encoding="utf-8",
    )
    automatic_path = run_dir / "automatic_evaluation.json"
    automatic = json.loads(automatic_path.read_text(encoding="utf-8"))
    automatic.update(
        {
            "case_id": "empty_case",
            "case_file": empty_case.relative_to(ROOT).as_posix()
            if empty_case.is_relative_to(ROOT)
            else str(empty_case),
            "case_sha256": hashlib.sha256(empty_case.read_bytes()).hexdigest(),
            "assertion_count": 0,
        }
    )
    # 绝对路径本身也应被 _resolve 拒绝；这里同时证明不会退回到“空用例通过”。
    automatic_path.write_text(json.dumps(automatic), encoding="utf-8")

    import finalize_run_evidence
    import run_workflow

    monkeypatch.setattr(run_workflow, "verify_run_seal", lambda *_args: {})
    monkeypatch.setattr(run_workflow, "verify_gate_artifacts", lambda *_args: {})
    monkeypatch.setattr(
        run_workflow,
        "replay_transition_log",
        lambda *_args: {"completed": True, "max_gate": 5, "transition_version": "2.0.0"},
    )
    monkeypatch.setattr(
        finalize_run_evidence, "validate_evidence_manifest", lambda *_args: []
    )

    outcome = validate_full_run(run_dir, {})

    assert not outcome.valid
    assert any("case_file" in error or "授权" in error for error in outcome.errors)


def test_control_requires_same_prompt_and_distinct_responses(
    tmp_path: Path, monkeypatch: Any
) -> None:
    baseline = tmp_path / "baseline"
    treatment = tmp_path / "treatment"
    baseline.mkdir()
    treatment.mkdir()
    baseline_evidence_sha = _write(
        baseline / "run_evidence_manifest.json", {"run_id": "baseline"}
    )
    treatment_evidence_sha = _write(
        treatment / "run_evidence_manifest.json", {"run_id": "treatment"}
    )
    _write(baseline / "ai_run_metadata.json", {"model": "same"})
    _write(treatment / "ai_run_metadata.json", {"model": "same"})
    _write(baseline / "problem_manifest.json", {"content_digest": "same"})
    _write(treatment / "problem_manifest.json", {"content_digest": "same"})
    _write(baseline / "runtime_pack.manifest.json", {"patches": []})
    _write(
        treatment / "runtime_pack.manifest.json",
        {"patches": [{"patch_id": "A999"}]},
    )
    review_path = tmp_path / "review.json"
    review = {
        "control_type": "positive",
        "target_patch": "A999",
        "baseline_run": "baseline",
        "treatment_run": "treatment",
        "baseline_evidence_manifest_sha256": baseline_evidence_sha,
        "treatment_evidence_manifest_sha256": treatment_evidence_sha,
        "experiment_group_id": "group",
        "final_conclusion": "pass",
        "consistency_checks": {"same_prompt": True},
        "risk_items": [{"observed": False}],
    }
    _write(review_path, review)

    def full_run(
        _run_dir: Path, _policy: dict[str, Any], **kwargs: Any
    ) -> EvidenceOutcome:
        role = kwargs["expected_role"]
        return EvidenceOutcome(
            True,
            identity={
                "run_id": role,
                "problem_id": "problem",
                "profile": "profile",
                "runtime_version": "1.0.0",
                "experiment_group_id": "group",
                "prompt_sha256": "baseline-prompt" if role == "baseline" else "other-prompt",
                "response_sha256": "same-response",
            },
        )

    monkeypatch.setattr(evidence_module, "validate_full_run", full_run)
    monkeypatch.setattr(evidence_module, "_schema_errors", lambda *_args: [])
    outcome = validate_control_evidence(
        "A999",
        "positive",
        {
            "case": "problem",
            "evidence": {
                "baseline_run": "baseline",
                "treatment_run": "treatment",
                "comparison_review": "review.json",
                "baseline_evidence_manifest_sha256": baseline_evidence_sha,
                "treatment_evidence_manifest_sha256": treatment_evidence_sha,
            },
        },
        {},
        root=tmp_path,
    )

    assert not outcome.valid
    assert any("prompt" in error.lower() for error in outcome.errors)
    assert any("response" in error.lower() for error in outcome.errors)


def test_profile_competition_rejects_experiment_and_patch_set_mismatch(
    tmp_path: Path, monkeypatch: Any
) -> None:
    patch_file = tmp_path / "patch.md"
    patch_file.write_text("patch", encoding="utf-8")
    runtime_path = tmp_path / "runtime.json"
    runtime_sha = _write(
        runtime_path,
        {
            "profile": "engineering_optimization",
            "runtime_version": "1.0.0",
            "runtime_pack_sha256": "a" * 64,
            "candidate_experiment": {"enabled": True, "patch_ids": ["A999"]},
            "exclusion_experiment": {"enabled": False, "patch_ids": []},
            "export_flags": {"candidate_patches": ["A999"], "excluded_patches": []},
            "patches": [
                {
                    "patch_id": "A999",
                    "path": "patch.md",
                    "status": "regression_verified",
                    "sha256": hashlib.sha256(patch_file.read_bytes()).hexdigest(),
                }
            ],
        },
    )
    result_path = tmp_path / "result.json"
    result_sha = _write(result_path, {"run_id": "run", "result": "pass"})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    evidence_path = tmp_path / "competition.json"
    _write(
        evidence_path,
        {
            "profile": "engineering_optimization",
            "runtime_version": "1.0.0",
            "run_id": "run",
            "run_dir": "run",
            "runtime_pack_manifest": "runtime.json",
            "runtime_pack_manifest_sha256": runtime_sha,
            "result_record": "result.json",
            "result_record_sha256": result_sha,
        },
    )
    monkeypatch.setattr(evidence_module, "_schema_errors", lambda *_args: [])
    monkeypatch.setattr(
        evidence_module,
        "validate_full_run",
        lambda *_args, **_kwargs: EvidenceOutcome(
            True,
            identity={
                "run_id": "run",
                "runtime_pack_sha256": "a" * 64,
            },
        ),
    )
    record = {
        "record_id": "competition",
        "kind": "competition",
        "path": "competition.json",
        "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    patches = [
        {
            "patch_id": "A999",
            "status": "regression_verified",
            "file": "patch.md",
            "runtime_profiles": ["engineering_optimization"],
        }
    ]
    policy = {
        "runtime_profile_stable_requirements": {
            "forbid_candidate_experiment": True,
            "forbid_exclusion_experiment": True,
            "require_exact_patch_set": True,
            "require_non_empty_verified_patches": True,
        }
    }

    outcome = validate_profile_record(
        record,
        "engineering_optimization",
        patches,
        policy,
        root=tmp_path,
        validated_formal_patch_ids=set(),
    )

    assert not outcome.valid
    assert any("candidate" in error for error in outcome.errors)
    assert any("Patch 集合" in error for error in outcome.errors)


def test_profile_competition_binds_result_record_to_runtime_identity(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """只有 result=pass 的记录不能与任意运行包拼接成比赛证据。"""
    patch_file = tmp_path / "patch.md"
    patch_file.write_text("patch", encoding="utf-8")
    runtime_path = tmp_path / "runtime.json"
    runtime_sha = _write(
        runtime_path,
        {
            "profile": "engineering_optimization",
            "runtime_version": "1.0.0",
            "runtime_pack_sha256": "a" * 64,
            "validation_target_status": "competition_evidenced",
            "candidate_experiment": {"enabled": False, "patch_ids": [], "warning": None},
            "exclusion_experiment": {"enabled": False, "patch_ids": []},
            "export_flags": {"candidate_patches": [], "excluded_patches": []},
            "patches": [
                {
                    "patch_id": "A999",
                    "path": "patch.md",
                    "status": "regression_verified",
                    "sha256": hashlib.sha256(patch_file.read_bytes()).hexdigest(),
                }
            ],
        },
    )
    result_path = tmp_path / "result.json"
    result_sha = _write(result_path, {"run_id": "run", "result": "pass"})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    evidence_path = tmp_path / "competition.json"
    _write(
        evidence_path,
        {
            "profile": "engineering_optimization",
            "runtime_version": "1.0.0",
            "run_id": "run",
            "run_dir": "run",
            "runtime_pack_manifest": "runtime.json",
            "runtime_pack_manifest_sha256": runtime_sha,
            "result_record": "result.json",
            "result_record_sha256": result_sha,
        },
    )
    monkeypatch.setattr(evidence_module, "_schema_errors", lambda *_args: [])
    monkeypatch.setattr(
        evidence_module,
        "validate_full_run",
        lambda *_args, **_kwargs: EvidenceOutcome(
            True,
            identity={
                "run_id": "run",
                "problem_id": "2024-C",
                "runtime_pack_sha256": "a" * 64,
            },
        ),
    )
    record = {
        "record_id": "competition",
        "kind": "competition",
        "path": "competition.json",
        "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    patches = [
        {
            "patch_id": "A999",
            "status": "competition_evidenced",
            "file": "patch.md",
            "runtime_profiles": ["engineering_optimization"],
        }
    ]
    outcome = validate_profile_record(
        record,
        "engineering_optimization",
        patches,
        {"runtime_profile_stable_requirements": {}},
        root=tmp_path,
        validated_formal_patch_ids={"A999"},
    )

    assert not outcome.valid
    assert any("result_record.profile" in error for error in outcome.errors)


def test_recorded_formal_status_does_not_create_validated_patch_id(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _write(
        tmp_path / "tests/prompt_regression/patch_negative_control_matrix.json",
        {"matrix_version": "2.0.0", "patches": [{"patch_id": "A999"}]},
    )
    patches = [{"patch_id": "A999", "status": "regression_verified"}]
    monkeypatch.setattr(
        evidence_module,
        "validate_formal_patch",
        lambda *_args, **_kwargs: EvidenceOutcome(False, ["deep evidence invalid"]),
    )

    validated, errors = derive_validated_formal_patch_ids(
        patches, {}, root=tmp_path
    )

    assert validated == set()
    assert any("deep evidence invalid" in error for error in errors)


def test_explicit_promotion_command_is_the_only_state_mutation_path(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """晋级命令在证据验证后原子改状态，不要求预先把状态伪造成终态。"""
    index_path = tmp_path / "patch_index.json"
    _write(
        index_path,
        [
            {
                "patch_id": "A999",
                "status": "regression_verified",
                "stable_evidence": {
                    "human_approval_record": {"reviewer": "reviewer"}
                },
            }
        ],
    )
    matrix_path = tmp_path / "matrix.json"
    _write(matrix_path, {"patches": [{"patch_id": "A999"}]})
    policy_path = tmp_path / "policy.json"
    _write(policy_path, {})
    monkeypatch.setattr(
        promote_patch_module,
        "derive_v2_matrix_results",
        lambda matrix, _policy, **_kwargs: (matrix, []),
    )
    monkeypatch.setattr(
        promote_patch_module,
        "validate_formal_patch",
        lambda *_args, **_kwargs: EvidenceOutcome(
            True, identity={"derived_status": "competition_evidenced"}
        ),
    )

    result = promote_patch_module.promote_patch(
        "A999",
        "competition_evidenced",
        "reviewer",
        root=tmp_path,
        index_path=index_path,
        matrix_path=matrix_path,
        policy_path=policy_path,
    )

    rewritten = json.loads(index_path.read_text(encoding="utf-8"))
    assert rewritten[0]["status"] == "competition_evidenced"
    assert result["previous_status"] == "regression_verified"
