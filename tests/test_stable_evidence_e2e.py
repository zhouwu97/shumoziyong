import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_runtime_pack import build_manifest, build_pack
from finalize_run_evidence import finalize_run_evidence
from promotion_engine import stable_evidence_digest
from run_workflow import mark_run_completed, record_transition
from validate_repository import RepositoryValidator


def mock_load_json(matrix, patch_index):
    def _load_json(path):
        if "matrix.json" in str(path):
            return matrix
        if "patch_index.json" in str(path):
            return patch_index
        return RepositoryValidator().load_json(path)

    return _load_json


def _complete_and_seal_run(run_dir: Path) -> None:
    """通过正式 Gate API 构造可复放、可封存的稳定证据运行。"""
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest.update({"run_status": "initialized", "integrity_status": "unsealed"})
    manifest_path.write_text(json.dumps(manifest), "utf-8")
    (run_dir / "score.json").write_text('{"total": 100, "passed": true}', "utf-8")
    (run_dir / "failure_labels.json").write_text('{"labels": [], "reviewed": true}', "utf-8")
    (run_dir / "transitions.jsonl").write_text(
        json.dumps({"from": None, "to": None, "state": "initialized", "material_ready": True, "max_gate": 5}) + "\n",
        "utf-8",
    )
    for gate in range(6):
        record_transition(run_dir, gate - 1 if gate else None, gate, "fixture", "approved")
    (run_dir / "gate_5_review.json").write_text(
        json.dumps(
            {
                "target_gate": 5,
                "reviewer": "fixture",
                "reviewed_at": "2026-07-11T00:00:00Z",
                "decision": "approved",
                "final_acceptance": True,
                "reason": "Fixture Gate 5 review is approved.",
            }
        ),
        "utf-8",
    )
    mark_run_completed(run_dir, "fixture")
    finalize_run_evidence(run_dir)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _retarget_fixture_patch(fix_dir: Path, patch_id: str) -> None:
    """将历史夹具的占位 Patch 改为真实 exporter 可导出的 Patch。"""
    for run_name in ("treatment", "treatment2", "retest"):
        run_dir = fix_dir / run_name
        manifest_path = run_dir / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8"))
        manifest["target_patch"] = patch_id
        manifest_path.write_text(json.dumps(manifest), "utf-8")

        runtime_manifest_path = run_dir / "runtime_pack.manifest.json"
        runtime_manifest = json.loads(runtime_manifest_path.read_text("utf-8"))
        for patch_entry in runtime_manifest.get("patches", []):
            patch_entry["patch_id"] = patch_id
        runtime_manifest_path.write_text(json.dumps(runtime_manifest), "utf-8")

        response_path = run_dir / "response.json"
        response = json.loads(response_path.read_text("utf-8"))
        decision = response.get("patch_decisions", {}).pop("A001")
        if decision is not None:
            response["patch_decisions"][patch_id] = decision
        response_path.write_text(json.dumps(response), "utf-8")

        evaluation_path = run_dir / "automatic_evaluation.json"
        evaluation = json.loads(evaluation_path.read_text("utf-8"))
        evaluation["response_sha256"] = _sha256(response_path)
        evaluation["manifest_sha256"] = _sha256(runtime_manifest_path)
        evaluation_path.write_text(json.dumps(evaluation), "utf-8")

    test_case_path = fix_dir / "test_t.yaml"
    test_case_path.write_text(test_case_path.read_text("utf-8").replace("A001", patch_id), "utf-8")
    for run_name in ("treatment", "treatment2", "retest"):
        evaluation_path = fix_dir / run_name / "automatic_evaluation.json"
        evaluation = json.loads(evaluation_path.read_text("utf-8"))
        evaluation["case_sha256"] = hashlib.sha256(
            test_case_path.read_text("utf-8").encode("utf-8")
        ).hexdigest()
        evaluation_path.write_text(json.dumps(evaluation), "utf-8")
    for record_name in ("failure_record.json", "fix_record.json"):
        record_path = fix_dir / record_name
        record = json.loads(record_path.read_text("utf-8"))
        record["patch_id"] = patch_id
        record_path.write_text(json.dumps(record), "utf-8")


def test_fully_valid_stable_patch_passes_repository_validator(tmp_path):
    """稳定证据夹具必须使用完整 Schema、真实 exporter 与完整 Gate 0-5。"""
    validator = RepositoryValidator()
    fix_dir = tmp_path / "fixtures"
    shutil.copytree(ROOT / "tests/fixtures/valid_stable_evidence", fix_dir)
    _retarget_fixture_patch(fix_dir, "A092")

    for run_name in ("baseline", "treatment", "baseline2", "treatment2", "retest"):
        manifest_path = fix_dir / run_name / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8"))
        manifest_path.write_text(json.dumps(manifest), "utf-8")
        _complete_and_seal_run(fix_dir / run_name)

    for review_name in ("comparison_review.json", "comparison_review_2.json"):
        review_path = fix_dir / review_name
        review = json.loads(review_path.read_text("utf-8"))
        review["target_patch"] = "A092"
        review_path.write_text(json.dumps(review), "utf-8")

    pack = build_pack("engineering_optimization")
    competition_manifest = build_manifest("engineering_optimization", pack)
    competition_manifest_path = fix_dir / "comp_manifest.json"
    competition_manifest_path.write_text(json.dumps(competition_manifest), "utf-8")
    competition_result_path = fix_dir / "comp_result.json"
    competition_result = json.loads(competition_result_path.read_text("utf-8"))
    competition_result.update(
        {
            "target_patch": "A092",
            "runtime_pack_manifest_sha256": _sha256(competition_manifest_path),
        }
    )
    competition_result_path.write_text(json.dumps(competition_result), "utf-8")

    source_index = json.loads((ROOT / "prompt_patches" / "patch_index.json").read_text("utf-8"))
    stable_patch = copy.deepcopy(next(item for item in source_index if item["patch_id"] == "A092"))
    stable_patch["status"] = "stable"
    original_evidence = json.loads((fix_dir / "patch_index.json").read_text("utf-8"))[0]["stable_evidence"]
    for negative_run in original_evidence["negative_control_runs"]:
        negative_run["case"] = "2016-C"
    original_evidence["competition_validation_records"][0]["runtime_pack_manifest_sha256"] = _sha256(competition_manifest_path)
    original_evidence["human_approval_record"]["patch_id"] = "A092"
    stable_patch["stable_evidence"] = original_evidence
    patch_index = [stable_patch]

    matrix = json.loads((fix_dir / "matrix.json").read_text("utf-8"))
    matrix["patches"][0]["patch_id"] = "A092"
    matrix["patches"][0]["negative"]["evidence"] = {
        "baseline_run": "tests/fixtures/valid_stable_evidence/baseline",
        "treatment_run": "tests/fixtures/valid_stable_evidence/treatment",
        "comparison_review": "tests/fixtures/valid_stable_evidence/comparison_review.json",
    }
    inner_hashes = {
        "negative_control_runs/0/baseline/run_evidence_manifest.json": _sha256(fix_dir / "baseline" / "run_evidence_manifest.json"),
        "negative_control_runs/0/treatment/run_evidence_manifest.json": _sha256(fix_dir / "treatment" / "run_evidence_manifest.json"),
        "negative_control_runs/0/comparison_review": _sha256(fix_dir / "comparison_review.json"),
        "negative_control_runs/1/baseline/run_evidence_manifest.json": _sha256(fix_dir / "baseline2" / "run_evidence_manifest.json"),
        "negative_control_runs/1/treatment/run_evidence_manifest.json": _sha256(fix_dir / "treatment2" / "run_evidence_manifest.json"),
        "negative_control_runs/1/comparison_review": _sha256(fix_dir / "comparison_review_2.json"),
        "failure_fix_retests/0/failure_record": _sha256(fix_dir / "failure_record.json"),
        "failure_fix_retests/0/fix_record": _sha256(fix_dir / "fix_record.json"),
        "failure_fix_retests/0/retest_evidence_manifest.json": _sha256(fix_dir / "retest" / "run_evidence_manifest.json"),
        "failure_fix_retests/0/review_record": _sha256(fix_dir / "fix_review.json"),
        "competition_validation_records/0/runtime_pack_manifest": _sha256(competition_manifest_path),
        "competition_validation_records/0/result_record": _sha256(competition_result_path),
    }
    stable_patch["stable_evidence"]["human_approval_record"]["evidence_digest"] = stable_evidence_digest(
        stable_patch,
        stable_patch["stable_evidence"],
        patch_sha256=_sha256(ROOT / stable_patch["file"]),
        inner_component_sha256s=inner_hashes,
    )

    def mock_resolve(self, raw):
        raw_text = str(raw)
        if raw_text.startswith("tests/fixtures/valid_stable_evidence"):
            return fix_dir / Path(raw_text).relative_to("tests/fixtures/valid_stable_evidence")
        if raw_text.startswith("tests/fixtures/valid_promotion_evidence/"):
            return fix_dir / Path(raw_text).name
        return (ROOT / raw_text).resolve()

    with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
        with patch.object(validator, "load_json", side_effect=mock_load_json(matrix, patch_index)):
            assert validator.validate_schema(patch_index, "patch_index.schema.json", "stable fixture patch_index")
            validator.validate_patch_promotion()
            assert not validator.failures

    (fix_dir / "fix_record.json").write_text('{"patch_id": "A092", "fix_description": "Tampered."}', "utf-8")
    tamper_validator = RepositoryValidator()
    with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
        with patch.object(tamper_validator, "load_json", side_effect=mock_load_json(matrix, patch_index)):
            tamper_validator.validate_patch_promotion()
            assert any("evidence_digest" in failure for failure in tamper_validator.failures)
