from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from formal_result.canonicalization import canonical_bytes  # noqa: E402
from formal_result.hashing import file_sha256  # noqa: E402
from validate_competition_qualification import (  # noqa: E402
    QualificationError,
    _commitment_root,
    _mapping_digest,
    qualification_campaign_digest,
    qualification_evidence_digest,
    validate_qualification,
)
from qualification_signature_payload import attach_signature, signing_payload  # noqa: E402
import validate_repository as repository_module  # noqa: E402


DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _is_probable_prime(candidate: int) -> bool:
    if candidate < 2 or candidate % 2 == 0:
        return candidate == 2
    divisor = candidate - 1
    power = 0
    while divisor % 2 == 0:
        divisor //= 2
        power += 1
    for base in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if base >= candidate:
            continue
        value = pow(base, divisor, candidate)
        if value in (1, candidate - 1):
            continue
        for _ in range(power - 1):
            value = pow(value, 2, candidate)
            if value == candidate - 1:
                break
        else:
            return False
    return True


def _prime(rng: random.Random, bits: int) -> int:
    while True:
        candidate = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


def _test_key(seed: int, key_id: str, role: str) -> tuple[dict[str, Any], tuple[int, int]]:
    rng = random.Random(seed)
    exponent = 65537
    while True:
        first = _prime(rng, 384)
        second = _prime(rng, 384)
        phi = (first - 1) * (second - 1)
        if first != second and math.gcd(exponent, phi) == 1:
            break
    modulus = first * second
    private_exponent = pow(exponent, -1, phi)
    entry = {
        "key_id": key_id,
        "pseudonym": key_id,
        "role": role,
        "human_identity_verified": True,
        "status": "active",
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
        "rsa_modulus_hex": format(modulus, "x"),
        "rsa_exponent": exponent,
        "not_before": "2026-01-01T00:00:00Z",
        "not_after": "2030-01-01T00:00:00Z",
    }
    return entry, (modulus, private_exponent)


def _sign(payload: Mapping[str, Any], private_key: tuple[int, int]) -> str:
    modulus, private_exponent = private_key
    width = (modulus.bit_length() + 7) // 8
    digest_info = DIGEST_INFO_PREFIX + hashlib.sha256(canonical_bytes(payload)).digest()
    padding_size = width - len(digest_info) - 3
    encoded = b"\x00\x01" + b"\xff" * padding_size + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), private_exponent, modulus).to_bytes(
        width, "big"
    )
    return base64.b64encode(signature).decode("ascii")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resign_coordinator(
    evidence: dict[str, Any], private_keys: Mapping[str, tuple[int, int]]
) -> None:
    attestation = evidence["coordinator_attestation"]
    attestation["case_commitment_root"] = _commitment_root(evidence["cases"])
    attestation["mapping_sha256"] = _mapping_digest(evidence["cases"])
    attestation["campaign_evidence_digest"] = qualification_campaign_digest(evidence)
    coordinator_key_id = str(attestation["coordinator_key_id"])
    attestation["signature"] = _sign(
        {key: value for key, value in attestation.items() if key != "signature"},
        private_keys[coordinator_key_id],
    )


def _fixture(tmp_path: Path) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, tuple[int, int]]
]:
    protocol = json.loads(
        (ROOT / "runtime_contracts/competition_qualification_protocol_v1.json").read_text(
            encoding="utf-8"
        )
    )
    capability = json.loads(
        (ROOT / "runtime_contracts/competition_production_capability_v1.json").read_text(
            encoding="utf-8"
        )
    )
    # 资格校验器单元测试使用已完成完整回放的隔离源能力；仓库当前能力仍保持降级状态。
    capability["lifecycle"] = "full_replay_passed"
    protocol_path = tmp_path / "runtime_contracts/competition_qualification_protocol_v1.json"
    capability_path = tmp_path / "runtime_contracts/competition_production_capability_v1.json"
    _write_json(protocol_path, protocol)
    _write_json(capability_path, capability)

    key_specs = [
        (101, "human-reviewer-a", "human_reviewer"),
        (202, "human-reviewer-b", "human_reviewer"),
        (303, "qualification-coordinator", "qualification_coordinator"),
    ]
    keys: list[dict[str, Any]] = []
    private_keys: dict[str, tuple[int, int]] = {}
    for seed, key_id, role in key_specs:
        entry, private_key = _test_key(seed, key_id, role)
        keys.append(entry)
        private_keys[key_id] = private_key
    registry = {
        "schema_version": "1.0.0",
        "registry_id": "competition_qualification_authorities_v1",
        "status": "active",
        "identity_verification": "out_of_band_human_verification_required",
        "keys": keys,
    }
    registry_path = tmp_path / "policies/competition_qualification_authorities_v1.json"
    _write_json(registry_path, registry)

    cases: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for index, slot in enumerate(protocol["case_slots"], start=1):
        baseline_package = "X" if index % 2 else "Y"
        treatment_package = "Y" if index % 2 else "X"
        packages = [
            {
                "package_id": f"{slot}-{label}",
                "label": label,
                "artifact_sha256": hashlib.sha256(f"{slot}-{label}".encode()).hexdigest(),
                "created_at": "2026-08-01T00:06:00Z",
                "author_identity_removed": True,
                "arm_identity_removed": True,
            }
            for label in ("X", "Y")
        ]
        case = {
            "case_slot": slot,
            "material_commitment_sha256": hashlib.sha256(slot.encode()).hexdigest(),
            "selection_locked_at": "2026-07-31T23:59:00Z",
            "first_revealed_to_runner_at": "2026-08-01T00:01:00Z",
            "answer_leakage_detected": False,
            "time_leakage_detected": False,
            "baseline": {
                "run_id": f"{slot}-baseline",
                "runtime_pack_sha256": "a" * 64,
                "execution_controls_sha256": hashlib.sha256(f"{slot}-controls".encode()).hexdigest(),
                "started_at": "2026-08-01T00:02:00Z",
                "completed_at": "2026-08-01T00:03:00Z",
                "formal_validation_passed": True,
                "fatal_error": False,
                "executable_solution": index <= 4,
                "manual_revision_minutes": 20,
                "supported_claim_count": 20,
                "overclaim_count": 2,
            },
            "treatment": {
                "run_id": f"{slot}-treatment",
                "runtime_pack_sha256": "b" * 64,
                "execution_controls_sha256": hashlib.sha256(f"{slot}-controls".encode()).hexdigest(),
                "started_at": "2026-08-01T00:04:00Z",
                "completed_at": "2026-08-01T00:05:00Z",
                "formal_validation_passed": True,
                "fatal_error": False,
                "executable_solution": True,
                "manual_revision_minutes": 15,
                "supported_claim_count": 25,
                "overclaim_count": 1,
            },
            "review_packages": packages,
            "package_arm_mapping": {
                baseline_package: "baseline",
                treatment_package: "treatment",
            },
            "mapping_revealed_at": "2026-08-01T00:09:00Z",
        }
        cases.append(case)
        for package in packages:
            arm = case["package_arm_mapping"][package["label"]]
            for reviewer_index, reviewer_key_id in enumerate(
                ("human-reviewer-a", "human-reviewer-b"), start=1
            ):
                review = {
                    "review_id": f"{package['package_id']}-R{reviewer_index}",
                    "case_slot": slot,
                    "package_id": package["package_id"],
                    "reviewer_key_id": reviewer_key_id,
                    "reviewer_kind": "human",
                    "model_quality_score": 75 if arm == "baseline" else 85,
                    "paper_quality_score": 76 if arm == "baseline" else 86,
                    "fatal_error": False,
                    "signed_at": f"2026-08-01T00:0{6 + reviewer_index}:00Z",
                    "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
                }
                review["signature"] = _sign(review, private_keys[reviewer_key_id])
                reviews.append(review)

    selection_attestation = {
        "coordinator_key_id": "qualification-coordinator",
        "case_commitment_root": _commitment_root(cases),
        "locked_at": "2026-08-01T00:00:00Z",
        "case_identity_hidden_before_lock": True,
        "answers_withheld": True,
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
    }
    selection_attestation["signature"] = _sign(
        selection_attestation, private_keys["qualification-coordinator"]
    )
    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "campaign_id": "qualification-fixture-v1",
        "protocol_ref": {
            "path": "runtime_contracts/competition_qualification_protocol_v1.json",
            "sha256": file_sha256(protocol_path),
        },
        "authority_registry_ref": {
            "path": "policies/competition_qualification_authorities_v1.json",
            "sha256": file_sha256(registry_path),
        },
        "source_capability_ref": {
            "path": "runtime_contracts/competition_production_capability_v1.json",
            "sha256": file_sha256(capability_path),
            "lifecycle": "full_replay_passed",
        },
        "locked_at": "2026-08-01T00:00:00Z",
        "cases": cases,
        "selection_attestation": selection_attestation,
        "blind_reviews": reviews,
    }
    attestation = {
        "coordinator_key_id": "qualification-coordinator",
        "case_commitment_root": _commitment_root(cases),
        "mapping_sha256": _mapping_digest(cases),
        "campaign_evidence_digest": qualification_campaign_digest(evidence),
        "case_selection_locked_before_runs": True,
        "arm_mapping_hidden_until_reviews_complete": True,
        "reviewer_assignments_hidden_from_producers": True,
        "signed_at": "2026-08-01T00:10:00Z",
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
    }
    attestation["signature"] = _sign(attestation, private_keys["qualification-coordinator"])
    evidence["coordinator_attestation"] = attestation
    return evidence, protocol, registry, private_keys


def _human_assisted_fixture(tmp_path: Path) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, tuple[int, int]]
]:
    legacy_evidence, _legacy_protocol, _legacy_registry, _legacy_keys = _fixture(tmp_path)
    protocol = json.loads(
        (ROOT / "runtime_contracts/competition_qualification_protocol_v2.json").read_text(
            encoding="utf-8"
        )
    )
    protocol_path = tmp_path / "runtime_contracts/competition_qualification_protocol_v2.json"
    _write_json(protocol_path, protocol)

    owner, owner_private_key = _test_key(
        404, "human-qualification-owner", "human_qualification_owner"
    )
    private_keys = {"human-qualification-owner": owner_private_key}
    registry = {
        "schema_version": "2.0.0",
        "registry_id": "competition_qualification_authorities_v2",
        "status": "active",
        "identity_verification": "out_of_band_human_verification_required",
        "keys": [owner],
    }
    registry_path = tmp_path / "policies/competition_qualification_authorities_v2.json"
    _write_json(registry_path, registry)

    cases = copy.deepcopy(legacy_evidence["cases"])
    reviews: list[dict[str, Any]] = []
    for case in cases:
        for package in case["review_packages"]:
            package_id = str(package["package_id"])
            arm = case["package_arm_mapping"][package["label"]]
            review = {
                "review_id": f"{package_id}-H1",
                "case_slot": case["case_slot"],
                "package_id": package_id,
                "reviewer_key_id": "human-qualification-owner",
                "reviewer_kind": "human",
                "assessment_mode": "human_decision_ai_recorded",
                "human_decision_confirmed": True,
                "ai_decision_authority": False,
                "ai_recorder": {
                    "record_id": f"{package_id}-record",
                    "provider": "fixture-provider",
                    "model": "fixture-recorder",
                    "model_version": "2026-08-01",
                    "session_id": f"fixture-{case['case_slot']}",
                    "system_prompt_sha256": hashlib.sha256(b"record-only").hexdigest(),
                    "transcript_sha256": hashlib.sha256(
                        f"{package_id}-transcript".encode()
                    ).hexdigest(),
                    "record_sha256": hashlib.sha256(f"{package_id}-record".encode()).hexdigest(),
                    "started_at": "2026-08-01T00:06:10Z",
                    "completed_at": "2026-08-01T00:06:30Z",
                    "decision_authority": False,
                },
                "model_quality_score": 75 if arm == "baseline" else 85,
                "paper_quality_score": 76 if arm == "baseline" else 86,
                "fatal_error": False,
                "signed_at": "2026-08-01T00:07:00Z",
                "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
            }
            review["signature"] = _sign(review, owner_private_key)
            reviews.append(review)

    selection_attestation = {
        "coordinator_key_id": "human-qualification-owner",
        "case_commitment_root": _commitment_root(cases),
        "locked_at": "2026-08-01T00:00:00Z",
        "case_identity_hidden_before_lock": True,
        "answers_withheld": True,
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
    }
    selection_attestation["signature"] = _sign(selection_attestation, owner_private_key)
    evidence: dict[str, Any] = {
        "schema_version": "2.0.0",
        "campaign_id": "human-assisted-qualification-fixture-v2",
        "protocol_ref": {
            "path": "runtime_contracts/competition_qualification_protocol_v2.json",
            "sha256": file_sha256(protocol_path),
        },
        "authority_registry_ref": {
            "path": "policies/competition_qualification_authorities_v2.json",
            "sha256": file_sha256(registry_path),
        },
        "source_capability_ref": copy.deepcopy(legacy_evidence["source_capability_ref"]),
        "locked_at": "2026-08-01T00:00:00Z",
        "cases": cases,
        "selection_attestation": selection_attestation,
        "human_assisted_reviews": reviews,
    }
    attestation = {
        "coordinator_key_id": "human-qualification-owner",
        "case_commitment_root": _commitment_root(cases),
        "mapping_sha256": _mapping_digest(cases),
        "campaign_evidence_digest": qualification_campaign_digest(evidence),
        "case_selection_locked_before_runs": True,
        "arm_mapping_hidden_until_reviews_complete": True,
        "human_decisions_confirmed": True,
        "ai_records_bound_to_human_decisions": True,
        "signed_at": "2026-08-01T00:10:00Z",
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
    }
    attestation["signature"] = _sign(attestation, owner_private_key)
    evidence["coordinator_attestation"] = attestation
    return evidence, protocol, registry, private_keys


def _trusted_fixture(tmp_path: Path) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, tuple[int, int]]
]:
    evidence, _legacy_protocol, legacy_registry, private_keys = _fixture(tmp_path)
    protocol = json.loads(
        (ROOT / "runtime_contracts/competition_qualification_protocol_v3.json").read_text(
            encoding="utf-8"
        )
    )
    protocol_path = tmp_path / "runtime_contracts/competition_qualification_protocol_v3.json"
    _write_json(protocol_path, protocol)

    role_by_key = {
        "human-reviewer-a": "external_human_reviewer",
        "human-reviewer-b": "external_human_reviewer",
        "qualification-coordinator": "independent_coordinator",
    }
    keys = copy.deepcopy(legacy_registry["keys"])
    for key in keys:
        key["role"] = role_by_key[key["key_id"]]
        key["project_external"] = True
    registry = {
        "schema_version": "3.0.0",
        "registry_id": "competition_qualification_authorities_v3",
        "status": "active",
        "identity_verification": "out_of_band_human_verification_required",
        "keys": keys,
    }
    registry_path = tmp_path / "policies/competition_qualification_authorities_v3.json"
    _write_json(registry_path, registry)

    for case in evidence["cases"]:
        case.update(
            {
                "complete_official_problem": True,
                "all_official_attachments_included": True,
                "not_used_during_development": True,
                "runner_answer_isolation": True,
            }
        )
        for arm_name in ("baseline", "treatment"):
            case[arm_name].update(
                {
                    "problem_validator_passed": True,
                    "complete_paper_generated": True,
                    "excel_validated": True,
                    "appendix_validated": True,
                    "submission_manifest_sha256": hashlib.sha256(
                        f"{case['case_slot']}-{arm_name}-submission".encode()
                    ).hexdigest(),
                }
            )

    reviews = evidence.pop("blind_reviews")
    for review in reviews:
        review.update(
            {
                "reviewer_kind": "external_human",
                "assessment_mode": "human_decision_ai_recorded",
                "human_decision_confirmed": True,
                "ai_decision_authority": False,
                "excel_and_appendix_verified": True,
                "ai_recorder": {
                    "record_id": f"{review['review_id']}-record",
                    "provider": "fixture-provider",
                    "model": "fixture-recorder",
                    "model_version": "2026-08-01",
                    "session_id": f"fixture-{review['review_id']}",
                    "system_prompt_sha256": hashlib.sha256(b"record-only").hexdigest(),
                    "transcript_sha256": hashlib.sha256(
                        f"{review['review_id']}-transcript".encode()
                    ).hexdigest(),
                    "record_sha256": hashlib.sha256(
                        f"{review['review_id']}-record".encode()
                    ).hexdigest(),
                    "started_at": "2026-08-01T00:06:10Z",
                    "completed_at": "2026-08-01T00:06:30Z",
                    "decision_authority": False,
                },
            }
        )
        review["signature"] = _sign(
            {key: value for key, value in review.items() if key != "signature"},
            private_keys[review["reviewer_key_id"]],
        )
    evidence["human_assisted_reviews"] = reviews
    evidence["schema_version"] = "3.0.0"
    evidence["campaign_id"] = "trusted-qualification-fixture-v3"
    evidence["protocol_ref"] = {
        "path": "runtime_contracts/competition_qualification_protocol_v3.json",
        "sha256": file_sha256(protocol_path),
    }
    evidence["authority_registry_ref"] = {
        "path": "policies/competition_qualification_authorities_v3.json",
        "sha256": file_sha256(registry_path),
    }
    selection = evidence["selection_attestation"]
    selection["development_use_excluded"] = True
    selection["signature"] = _sign(
        {key: value for key, value in selection.items() if key != "signature"},
        private_keys["qualification-coordinator"],
    )
    attestation = evidence["coordinator_attestation"]
    attestation.update(
        {
            "human_decisions_confirmed": True,
            "ai_records_bound_to_human_decisions": True,
            "two_external_reviewers_confirmed": True,
            "coordinator_independence_confirmed": True,
            "final_excel_and_appendices_verified": True,
        }
    )
    attestation["campaign_evidence_digest"] = qualification_campaign_digest(evidence)
    attestation["signature"] = _sign(
        {key: value for key, value in attestation.items() if key != "signature"},
        private_keys["qualification-coordinator"],
    )
    return evidence, protocol, registry, private_keys


def test_qualification_contracts_and_current_registry_are_valid() -> None:
    pairs = [
        (
            "competition_qualification_protocol.schema.json",
            "runtime_contracts/competition_qualification_protocol_v1.json",
        ),
        (
            "competition_qualification_authority_registry.schema.json",
            "policies/competition_qualification_authorities_v1.json",
        ),
        (
            "competition_qualification_protocol_v2.schema.json",
            "runtime_contracts/competition_qualification_protocol_v2.json",
        ),
        (
            "competition_qualification_authority_registry_v2.schema.json",
            "policies/competition_qualification_authorities_v2.json",
        ),
        (
            "competition_qualification_protocol_v3.schema.json",
            "runtime_contracts/competition_qualification_protocol_v3.json",
        ),
        (
            "competition_qualification_authority_registry_v3.schema.json",
            "policies/competition_qualification_authorities_v3.json",
        ),
    ]
    for schema_name, instance_name in pairs:
        schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
        instance = json.loads((ROOT / instance_name).read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(instance)


def test_complete_signed_double_blind_evidence_passes_without_defaulting(
    tmp_path: Path,
) -> None:
    evidence, protocol, registry, _private_keys = _fixture(tmp_path)
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "blind_review_passed"
    assert report["derived_lifecycle"] == "blind_review_passed"
    assert report["new_problem_default_enabled"] is False
    assert report["review_summary"] == {
        "review_count": 24,
        "distinct_human_reviewers": 2,
        "all_signatures_valid": True,
        "double_blind_attested": True,
    }
    assert report["metrics"]["treatment_executable_rate"] == 1.0
    assert "不自动启用默认能力" in report["gaps"][0]


def test_human_assisted_ai_recorded_evidence_passes_without_defaulting(
    tmp_path: Path,
) -> None:
    evidence, protocol, registry, _private_keys = _human_assisted_fixture(tmp_path)
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "human_assisted_review_passed"
    assert report["derived_lifecycle"] == "human_assisted_review_passed"
    assert report["new_problem_default_enabled"] is False
    assert report["review_summary"] == {
        "review_count": 12,
        "distinct_human_reviewers": 1,
        "ai_record_count": 12,
        "all_signatures_valid": True,
        "human_decision_attested": True,
        "ai_record_only_attested": True,
        "arm_blind_attested": True,
    }


def test_trusted_double_external_human_review_passes_without_defaulting(
    tmp_path: Path,
) -> None:
    evidence, protocol, registry, _private_keys = _trusted_fixture(tmp_path)
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "blind_review_passed"
    assert report["derived_lifecycle"] == "blind_review_passed"
    assert report["new_problem_default_enabled"] is False
    assert report["review_summary"]["review_count"] == 24
    assert report["review_summary"]["distinct_human_reviewers"] == 2
    assert report["review_summary"]["ai_record_count"] == 24
    assert "72 小时模拟赛" in report["gaps"][-1]


def test_human_assisted_ai_cannot_claim_decision_authority(tmp_path: Path) -> None:
    evidence, protocol, registry, _private_keys = _human_assisted_fixture(tmp_path)
    evidence["human_assisted_reviews"][0]["ai_decision_authority"] = True
    with pytest.raises(QualificationError, match="资格证据不符合 Schema"):
        validate_qualification(evidence, protocol, registry, root=tmp_path)


def test_human_assisted_ai_record_must_precede_human_signature(tmp_path: Path) -> None:
    evidence, protocol, registry, private_keys = _human_assisted_fixture(tmp_path)
    review = evidence["human_assisted_reviews"][0]
    review["ai_recorder"]["completed_at"] = "2026-08-01T00:08:00Z"
    review["signature"] = _sign(
        {key: value for key, value in review.items() if key != "signature"},
        private_keys["human-qualification-owner"],
    )
    _resign_coordinator(evidence, private_keys)
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "failed"
    assert report["derived_lifecycle"] == "full_replay_passed"
    assert "QF_AI_RECORD_TIME_ORDER" in report["fatal_codes"]


def test_human_assisted_score_tampering_breaks_human_signature(tmp_path: Path) -> None:
    evidence, protocol, registry, _private_keys = _human_assisted_fixture(tmp_path)
    evidence["human_assisted_reviews"][0]["paper_quality_score"] = 100
    with pytest.raises(QualificationError, match="签名验证失败"):
        validate_qualification(evidence, protocol, registry, root=tmp_path)


def test_single_human_assisted_review_cannot_reach_default_candidate(
    tmp_path: Path,
) -> None:
    evidence, protocol, registry, private_keys = _human_assisted_fixture(tmp_path)
    approval = {
        "coordinator_key_id": "human-qualification-owner",
        "evidence_digest": qualification_evidence_digest(evidence),
        "target_lifecycle": "default_candidate",
        "approved_at": "2026-08-01T00:11:00Z",
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
    }
    approval["signature"] = _sign(approval, private_keys["human-qualification-owner"])
    evidence["promotion_approval"] = approval
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "human_assisted_review_passed"
    assert report["derived_lifecycle"] == "human_assisted_review_passed"
    assert report["new_problem_default_enabled"] is False
    assert "不能产生 default_candidate" in report["gaps"][-1]


def test_unconfigured_human_owner_registry_cannot_qualify(tmp_path: Path) -> None:
    evidence, protocol, _registry, _private_keys = _human_assisted_fixture(tmp_path)
    registry = json.loads(
        (ROOT / "policies/competition_qualification_authorities_v2.json").read_text(
            encoding="utf-8"
        )
    )
    registry_path = tmp_path / "policies/competition_qualification_authorities_v2.json"
    _write_json(registry_path, registry)
    evidence["authority_registry_ref"]["sha256"] = file_sha256(registry_path)
    with pytest.raises(QualificationError, match="尚未激活"):
        validate_qualification(evidence, protocol, registry, root=tmp_path)


def test_metric_failure_stays_qualification_candidate(tmp_path: Path) -> None:
    evidence, protocol, registry, private_keys = _fixture(tmp_path)
    for review in evidence["blind_reviews"]:
        if review["model_quality_score"] == 85:
            review["model_quality_score"] = 76
            review["signature"] = _sign(
                {key: value for key, value in review.items() if key != "signature"},
                private_keys[review["reviewer_key_id"]],
            )
    _resign_coordinator(evidence, private_keys)
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "qualification_candidate"
    assert report["derived_lifecycle"] == "qualification_candidate"
    assert "Treatment 模型质量均分未达 80" in report["gaps"]


def test_arm_mapping_revealed_before_reviews_fails_closed(tmp_path: Path) -> None:
    evidence, protocol, registry, private_keys = _fixture(tmp_path)
    evidence["cases"][0]["mapping_revealed_at"] = "2026-08-01T00:07:30Z"
    _resign_coordinator(evidence, private_keys)
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "failed"
    assert report["derived_lifecycle"] == "full_replay_passed"
    assert "QF_ARM_IDENTITY_LEAKAGE" in report["fatal_codes"]


def test_review_signature_tampering_is_rejected(tmp_path: Path) -> None:
    evidence, protocol, registry, _private_keys = _fixture(tmp_path)
    evidence["blind_reviews"][0]["paper_quality_score"] = 100
    with pytest.raises(QualificationError, match="签名验证失败"):
        validate_qualification(evidence, protocol, registry, root=tmp_path)


def test_machine_metric_tampering_breaks_coordinator_digest(tmp_path: Path) -> None:
    evidence, protocol, registry, _private_keys = _fixture(tmp_path)
    evidence["cases"][0]["treatment"]["manual_revision_minutes"] = 0
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "failed"
    assert "QF_CAMPAIGN_EVIDENCE_DRIFT" in report["fatal_codes"]


def test_post_hoc_case_replacement_breaks_selection_commitment(tmp_path: Path) -> None:
    evidence, protocol, registry, _private_keys = _fixture(tmp_path)
    evidence["cases"][0]["material_commitment_sha256"] = "f" * 64
    with pytest.raises(QualificationError, match="选题承诺根"):
        validate_qualification(evidence, protocol, registry, root=tmp_path)


def test_signature_payload_helper_matches_validator_canonicalization(tmp_path: Path) -> None:
    evidence, _protocol, _registry, private_keys = _fixture(tmp_path)
    review = evidence["blind_reviews"][0]
    unsigned = {key: value for key, value in review.items() if key != "signature"}
    expected_signature = base64.b64decode(review["signature"], validate=True)
    assert signing_payload(review) == canonical_bytes(unsigned)
    assert attach_signature(unsigned, expected_signature)["signature"] == review["signature"]


def test_default_candidate_requires_digest_bound_coordinator_approval(tmp_path: Path) -> None:
    evidence, protocol, registry, private_keys = _fixture(tmp_path)
    approval = {
        "coordinator_key_id": "qualification-coordinator",
        "evidence_digest": qualification_evidence_digest(evidence),
        "target_lifecycle": "default_candidate",
        "approved_at": "2026-08-01T00:11:00Z",
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
    }
    approval["signature"] = _sign(approval, private_keys["qualification-coordinator"])
    evidence["promotion_approval"] = approval
    report = validate_qualification(evidence, protocol, registry, root=tmp_path)
    assert report["status"] == "default_candidate"
    assert report["derived_lifecycle"] == "default_candidate"
    assert report["new_problem_default_enabled"] is False


def test_unconfigured_human_authority_registry_cannot_qualify(tmp_path: Path) -> None:
    evidence, protocol, _registry, _private_keys = _fixture(tmp_path)
    registry = json.loads(
        (ROOT / "policies/competition_qualification_authorities_v1.json").read_text(
            encoding="utf-8"
        )
    )
    registry_path = tmp_path / "policies/competition_qualification_authorities_v1.json"
    _write_json(registry_path, registry)
    evidence["authority_registry_ref"]["sha256"] = file_sha256(registry_path)
    with pytest.raises(QualificationError, match="尚未激活"):
        validate_qualification(evidence, protocol, registry, root=tmp_path)


def test_source_capability_hash_drift_is_rejected(tmp_path: Path) -> None:
    evidence, protocol, registry, _private_keys = _fixture(tmp_path)
    evidence["source_capability_ref"]["sha256"] = "0" * 64
    with pytest.raises(QualificationError, match="SHA-256 漂移"):
        validate_qualification(evidence, protocol, registry, root=tmp_path)


def test_capability_schema_forbids_early_default_activation() -> None:
    schema = json.loads(
        (ROOT / "schemas/competition_production_capability.schema.json").read_text(
            encoding="utf-8"
        )
    )
    capability = json.loads(
        (ROOT / "runtime_contracts/competition_production_capability_v1.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(capability)
    capability["new_problem_default_enabled"] = True
    capability["activation_contexts"] = ["full_replay", "new_problem"]
    errors = list(Draft202012Validator(schema).iter_errors(capability))
    assert errors


def test_higher_lifecycle_requires_qualification_report_binding() -> None:
    schema = json.loads(
        (ROOT / "schemas/competition_production_capability.schema.json").read_text(
            encoding="utf-8"
        )
    )
    capability = json.loads(
        (ROOT / "runtime_contracts/competition_production_capability_v1.json").read_text(
            encoding="utf-8"
        )
    )
    capability["lifecycle"] = "blind_review_passed"
    errors = list(Draft202012Validator(schema).iter_errors(capability))
    assert errors
    capability["qualification_evidence"] = {
        "path": (
            "capability_evidence/competition_production/qualification/"
            "qualification_report_v1.json"
        ),
        "sha256": "c" * 64,
    }
    Draft202012Validator(schema).validate(capability)
    capability["lifecycle"] = "human_assisted_review_passed"
    capability["qualification_evidence"]["path"] = (
        "capability_evidence/competition_production/qualification/qualification_report_v2.json"
    )
    Draft202012Validator(schema).validate(capability)


def test_default_candidate_requires_v3_qualification_and_72h_simulation() -> None:
    schema = json.loads(
        (ROOT / "schemas/competition_production_capability.schema.json").read_text(
            encoding="utf-8"
        )
    )
    capability = json.loads(
        (ROOT / "runtime_contracts/competition_production_capability_v1.json").read_text(
            encoding="utf-8"
        )
    )
    capability["lifecycle"] = "default_candidate"
    capability["qualification_evidence"] = {
        "path": "capability_evidence/competition_production/qualification/qualification_report_v2.json",
        "sha256": "c" * 64,
    }
    assert list(Draft202012Validator(schema).iter_errors(capability))

    capability["qualification_evidence"]["path"] = (
        "capability_evidence/competition_production/qualification/qualification_report_v3.json"
    )
    capability["simulation_evidence"] = {
        "path": "capability_evidence/competition_production/simulation/simulation_report_v1.json",
        "sha256": "d" * 64,
    }
    Draft202012Validator(schema).validate(capability)


def test_repository_validator_accepts_default_candidate_only_as_composite_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_names = [
        "competition_production_capability.schema.json",
        "competition_qualification_report_v3.schema.json",
        "competition_72h_simulation_report.schema.json",
    ]
    for schema_name in schema_names:
        target = tmp_path / "schemas" / schema_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "schemas" / schema_name, target)

    metrics = {
        "baseline_model_quality": 75,
        "treatment_model_quality": 85,
        "model_quality_gain": 10,
        "baseline_paper_quality": 76,
        "treatment_paper_quality": 86,
        "paper_quality_gain": 10,
        "baseline_executable_rate": 0.5,
        "treatment_executable_rate": 1.0,
        "baseline_manual_revision_minutes": 600,
        "treatment_manual_revision_minutes": 480,
        "revision_time_reduction_ratio": 0.2,
        "baseline_overclaim_rate": 0.1,
        "treatment_overclaim_rate": 0.0,
        "cases_with_combined_quality_gain": 6,
    }
    qualification_report = {
        "schema_version": "3.0.0",
        "report_id": "trusted-qualification-report",
        "campaign_id": "trusted-qualification",
        "protocol_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "status": "blind_review_passed",
        "derived_lifecycle": "blind_review_passed",
        "new_problem_default_enabled": False,
        "metrics": metrics,
        "fatal_codes": [],
        "gaps": ["仍须通过独立 72 小时模拟赛"],
        "review_summary": {
            "review_count": 24,
            "distinct_human_reviewers": 2,
            "ai_record_count": 24,
            "all_signatures_valid": True,
            "human_decision_attested": True,
            "ai_record_only_attested": True,
            "arm_blind_attested": True,
        },
    }
    qualification_path = (
        tmp_path
        / "capability_evidence/competition_production/qualification/qualification_report_v3.json"
    )
    _write_json(qualification_path, qualification_report)
    simulation_report = {
        "schema_version": "1.0.0",
        "report_id": "trusted-simulation-report",
        "simulation_id": "trusted-simulation",
        "protocol_sha256": "c" * 64,
        "evidence_sha256": "d" * 64,
        "status": "competition_72h_simulation_passed",
        "default_candidate_eligible": True,
        "elapsed_hours": 68,
        "audit_overhead_ratio": 0.2,
        "stage_count": 8,
        "artifact_count": 5,
        "human_attested": True,
        "ai_record_only": True,
        "fatal_codes": [],
        "gaps": [],
    }
    simulation_path = (
        tmp_path
        / "capability_evidence/competition_production/simulation/simulation_report_v1.json"
    )
    _write_json(simulation_path, simulation_report)
    capability = json.loads(
        (ROOT / "runtime_contracts/competition_production_capability_v1.json").read_text(
            encoding="utf-8"
        )
    )
    capability.update(
        {
            "lifecycle": "default_candidate",
            "qualification_evidence": {
                "path": "capability_evidence/competition_production/qualification/qualification_report_v3.json",
                "sha256": hashlib.sha256(
                    qualification_path.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
            },
            "simulation_evidence": {
                "path": "capability_evidence/competition_production/simulation/simulation_report_v1.json",
                "sha256": hashlib.sha256(
                    simulation_path.read_text(encoding="utf-8").encode("utf-8")
                ).hexdigest(),
            },
        }
    )
    _write_json(
        tmp_path / "runtime_contracts/competition_production_capability_v1.json",
        capability,
    )

    monkeypatch.setattr(repository_module, "ROOT", tmp_path)
    monkeypatch.setattr(repository_module, "SCHEMA_DIR", tmp_path / "schemas")
    validator = repository_module.RepositoryValidator()
    validator.validate_competition_production_capability()
    assert validator.failures == []
    assert "Competition Production default_candidate 双证据闭包" in validator.passes
