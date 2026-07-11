import pytest
import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_repository import RepositoryValidator
from finalize_run_evidence import finalize_run_evidence
from run_workflow import GATE_5_CHECKLIST_KEYS, mark_run_completed, record_transition
from promotion_engine import evaluate_status_eligibility

FIXTURE_DIR = ROOT / "tests/fixtures/valid_promotion_evidence"

@pytest.fixture
def valid_matrix():
    return json.loads((FIXTURE_DIR / "matrix.json").read_text("utf-8"))

@pytest.fixture
def valid_patch_index():
    return json.loads((FIXTURE_DIR / "patch_index.json").read_text("utf-8"))

@pytest.fixture
def validator():
    return RepositoryValidator()

# A helper to mock load_json
def mock_load_json(valid_matrix, valid_patch_index):
    def _load_json(x):
        if 'matrix.json' in str(x): return valid_matrix
        if 'patch_index.json' in str(x): return valid_patch_index
        return RepositoryValidator().load_json(x)
    return _load_json

def modify_json(path: Path, updates: dict):
    data = json.loads(path.read_text("utf-8"))
    data.update(updates)
    path.write_text(json.dumps(data), "utf-8")


def _complete_and_seal_fixture_run(run_dir: Path) -> None:
    """用真实 Gate API 构造可用于晋级验证的完整运行证据。"""
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest.update({"run_status": "initialized", "integrity_status": "unsealed"})
    manifest_path.write_text(json.dumps(manifest), "utf-8")
    runtime_manifest = json.loads(
        (run_dir / "runtime_pack.manifest.json").read_text("utf-8")
    )
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
                "run_id": manifest["run_id"],
                "problem_id": manifest["problem_id"],
                "profile": manifest["profile"],
                "runtime_version": manifest["runtime_version"],
                "runtime_pack_sha256": runtime_manifest["runtime_pack_sha256"],
                "target_gate": 5,
                "reviewer": "fixture",
                "reviewed_at": "2026-07-11T00:00:00Z",
                "decision": "approved",
                "final_acceptance": True,
                "reason": "Fixture Gate 5 review is approved.",
                "checklist": {key: True for key in GATE_5_CHECKLIST_KEYS},
            }
        ),
        "utf-8",
    )
    mark_run_completed(run_dir, "fixture")
    finalize_run_evidence(run_dir)

def test_valid_evidence_passes(validator, valid_matrix, valid_patch_index, tmp_path):
    fix_dir = _copy_fixture(tmp_path)
    _setup_fixture_paths(fix_dir, valid_matrix)
    _complete_and_seal_fixture_run(fix_dir / "baseline")
    _complete_and_seal_fixture_run(fix_dir / "treatment")
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert not validator.failures
            assert (
                "patch 晋级规则（promotion_policy.json 统一评估 + 负控证据验证）"
                in validator.passes
            )


def test_incomplete_gate_log_cannot_be_promotion_evidence(validator, valid_matrix, valid_patch_index, tmp_path):
    """仅有 ready 文本的 transitions 不能伪装成完成的 Gate 0-5 运行。"""
    fix_dir = _copy_fixture(tmp_path)
    _setup_fixture_paths(fix_dir, valid_matrix)
    _complete_and_seal_fixture_run(fix_dir / "baseline")
    _complete_and_seal_fixture_run(fix_dir / "treatment")
    (fix_dir / "baseline" / "transitions.jsonl").write_text('{"state": "ready"}\n', "utf-8")

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any("Gate 状态机记录无效" in failure for failure in validator.failures)

def test_negative_case_mismatch_fails(validator, valid_matrix, valid_patch_index):
    valid_matrix["patches"][0]["negative"]["case"] = "WRONG-CASE"

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        validator.validate_patch_promotion()
        assert any("negative.case 与运行题号不一致" in failure for failure in validator.failures)


def test_simulated_precheck_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "baseline" / "run_manifest.json", {"evidence_validity": "simulated_precheck"})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("evidence_validity 不是 real_ai_run" in f for f in validator.failures)

def test_eligible_for_promotion_false_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "baseline" / "run_manifest.json", {"eligible_for_promotion": False})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("eligible_for_promotion 为 false" in f for f in validator.failures)

def test_request_prompt_empty_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "treatment" / "request.json", {"prompt": ""})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("request.prompt 为空" in f for f in validator.failures)

def test_same_response_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    # To truly test "same response", we make baseline and treatment responses exactly the same and both valid
    import hashlib
    valid_resp = (FIXTURE_DIR / "treatment" / "response.json").read_text('utf-8')
    (tmp_path / "fixtures" / "baseline" / "response.json").write_text(valid_resp, 'utf-8')
    # Update hash in automatic_evaluation so schema passes, and re-evaluation isn't blocked by mismatch hashes
    modify_json(tmp_path / "fixtures" / "baseline" / "automatic_evaluation.json", {"response_sha256": hashlib.sha256(valid_resp.encode('utf-8')).hexdigest()})
    
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("完全相同" in f for f in validator.failures)

def test_path_traversal_fails(validator, valid_matrix, valid_patch_index):
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = "../escape"
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        validator.validate_patch_promotion()
        assert any("位于仓库外" in f for f in validator.failures)

def test_wrong_target_patch_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "treatment" / "run_manifest.json", {"target_patch": "WRONG"})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("treatment target_patch 错误" in f for f in validator.failures)

def test_experiment_group_mismatch(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "baseline" / "run_manifest.json", {"experiment_group_id": "GRP-02"})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("experiment_group_id 不同" in f for f in validator.failures)

def test_missing_evidence(validator, valid_matrix, valid_patch_index):
    valid_matrix["patches"][0]["negative"]["evidence"] = {}
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        validator.validate_patch_promotion()
        assert any("缺少结构化 evidence 或必填字段" in f for f in validator.failures)

def test_auto_eval_hash_mismatch(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "treatment" / "automatic_evaluation.json", {"response_sha256": "wronghash"})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("response_sha256 不匹配" in f for f in validator.failures)

def test_comparison_review_risk_flag(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    data = json.loads((tmp_path / "fixtures" / "comparison_review.json").read_text("utf-8"))
    data["risk_flags"]["changed_primary_type"] = True
    (tmp_path / "fixtures" / "comparison_review.json").write_text(json.dumps(data), "utf-8")
    
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            # v2 comparison review: risk flags are plain boolean, not const false.
            # The failure should come from the risk flag check (not Schema).
            assert any("risk_flags" in f and "true" in f for f in validator.failures)

def test_comparison_review_group_id_mismatch(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "comparison_review.json", {"experiment_group_id": "WRONG_ID"})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("与运行组不一致" in f for f in validator.failures)

def test_enabled_mismatch(validator, valid_matrix, valid_patch_index, tmp_path):
    def mock_resolve(self, raw): return Path(raw).resolve()
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    # modify treatment response so enabled is wrong
    data = json.loads((tmp_path / "fixtures" / "treatment" / "response.json").read_text("utf-8"))
    data["patch_decisions"]["A001"]["enabled"] = True # treatment's manifest has A001, so wait, it expects it to be True?
    # the valid response sets enabled: False for A001 while manifest has A001
    # Oh wait! In my valid fixture, A001 is loaded, but enabled is False!
    # Wait, the rule is expected_enabled = patch in manifest.
    # actual_enabled = decision.enabled
    # In treatment, A001 is in manifest, so it expects True! But in negative control, applicable is False.
    # Ah! If applicable is False, does `evaluate_prompt_response` still require `enabled=True` because it's loaded?
    # Yes! A patch can be enabled (meaning the decision framework allows it to be evaluated) even if applicable is False?
    # Let's check my `test_same_response_fails`.
    data["patch_decisions"]["A001"]["enabled"] = False # making it mismatch
    import hashlib
    (tmp_path / "fixtures" / "treatment" / "response.json").write_text(json.dumps(data), "utf-8")
    modify_json(tmp_path / "fixtures" / "treatment" / "automatic_evaluation.json", {"response_sha256": hashlib.sha256(json.dumps(data).encode('utf-8')).hexdigest()})
    
    # We expect `evaluate_manifest_alignment` to fail.
    # But wait, in the valid fixture, enabled is already false! Let's ensure the valid fixture has enabled=True so it passes naturally.
    valid_data = json.loads((FIXTURE_DIR / "treatment" / "response.json").read_text("utf-8"))
    valid_data["patch_decisions"]["A001"]["enabled"] = False
    
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("与运行包包含情况不符" in f for f in validator.failures)


# ====== AI 运行元数据校验测试 ======


def _copy_fixture(tmp_path: Path) -> Path:
    """Helper: copy the valid fixture and return the temp path to it."""
    dst = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_DIR, dst)
    return dst


def _setup_fixture_paths(fix_dir: Path, valid_matrix, b_extra: str = "", t_extra: str = ""):
    """Set up baseline/treatment paths in the matrix and sync comparison_review paths."""
    b_path = str(fix_dir / "baseline") + b_extra
    t_path = str(fix_dir / "treatment") + t_extra
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = b_path
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = t_path
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(
        fix_dir / "comparison_review.json"
    )
    # Sync comparison_review.json with the temp paths
    cr = json.loads((fix_dir / "comparison_review.json").read_text("utf-8"))
    cr["baseline_run"] = b_path
    cr["treatment_run"] = t_path
    (fix_dir / "comparison_review.json").write_text(json.dumps(cr), "utf-8")


def _fixture_legacy_policy(fix_dir: Path) -> dict:
    """为临时夹具登记唯一可放行的历史证据路径。"""
    policy = json.loads((ROOT / "policies" / "promotion_policy.json").read_text("utf-8"))
    requirements = policy["diagnosis_schema_requirements"]
    requirements["legacy_evidence_allowlist"] = ["GRP-01"]
    requirements["legacy_evidence_paths"] = {
        "GRP-01": {
            "baseline_run": str(fix_dir / "baseline"),
            "treatment_run": str(fix_dir / "treatment"),
            "comparison_review": str(fix_dir / "comparison_review.json"),
        }
    }
    return policy


def test_ai_metadata_valid_passes(validator, valid_matrix, valid_patch_index, tmp_path):
    """Valid ai_run_metadata on both baseline and treatment passes."""
    fix_dir = _copy_fixture(tmp_path)
    _setup_fixture_paths(fix_dir, valid_matrix)
    _complete_and_seal_fixture_run(fix_dir / "baseline")
    _complete_and_seal_fixture_run(fix_dir / "treatment")

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    def mock_load(valid_matrix, valid_patch_index):
        def fn(x):
            if "matrix.json" in str(x):
                return valid_matrix
            if "patch_index.json" in str(x):
                return valid_patch_index
            return RepositoryValidator().load_json(x)
        return fn

    with patch.object(validator, "load_json", side_effect=mock_load(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert not validator.failures


def test_ai_metadata_missing_file_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """Missing ai_run_metadata.json on non-legacy evidence fails."""
    fix_dir = _copy_fixture(tmp_path)
    (fix_dir / "baseline" / "ai_run_metadata.json").unlink()
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("缺少 ai_run_metadata.json" in f for f in validator.failures)


def test_ai_metadata_empty_provider_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """Empty provider in ai_run_metadata fails."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "baseline" / "ai_run_metadata.json", {"provider": ""})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("ai_run_metadata.provider 为空" in f for f in validator.failures)


def test_ai_metadata_empty_model_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """Empty model in ai_run_metadata fails."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "baseline" / "ai_run_metadata.json", {"model": ""})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("ai_run_metadata.model 为空" in f for f in validator.failures)


def test_ai_metadata_completed_before_started_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """completed_at earlier than started_at fails."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(
        fix_dir / "baseline" / "ai_run_metadata.json",
        {"started_at": "2026-07-10T12:05:00Z", "completed_at": "2026-07-10T12:00:00Z"},
    )
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("早于 started_at" in f for f in validator.failures)


def test_ai_metadata_prompt_sha256_mismatch_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """prompt_sha256 doesn't match actual normalized prompt hash."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "treatment" / "ai_run_metadata.json", {"prompt_sha256": "a" * 64})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("ai_run_metadata.prompt_sha256 不匹配" in f for f in validator.failures)


def test_ai_metadata_runtime_pack_sha256_mismatch_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """runtime_pack_sha256 与 runtime_pack.md 内容不一致时失败。"""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "treatment" / "ai_run_metadata.json", {"runtime_pack_sha256": "b" * 64})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("ai_run_metadata.runtime_pack_sha256 不匹配" in f for f in validator.failures)


def test_ai_metadata_runtime_pack_content_tamper_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """篡改 runtime_pack.md 而不同步 manifest/metadata 时必须被发现。"""
    fix_dir = _copy_fixture(tmp_path)
    with (fix_dir / "treatment" / "runtime_pack.md").open("a", encoding="utf-8") as fh:
        fh.write("\nTampered rule.\n")
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any("runtime_pack_sha256 不匹配" in f for f in validator.failures)


def test_ai_metadata_problem_material_digest_mismatch_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """problem_material_digest doesn't match content_digest in problem_manifest."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "treatment" / "ai_run_metadata.json", {"problem_material_digest": "c" * 64})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("ai_run_metadata.problem_material_digest 不匹配" in f for f in validator.failures)


def test_ai_metadata_problem_material_digest_missing_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """problem_manifest 缺少材料摘要不能被视为通过。"""
    fix_dir = _copy_fixture(tmp_path)
    manifest_path = fix_dir / "treatment" / "problem_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest.pop("content_digest")
    manifest_path.write_text(json.dumps(manifest), "utf-8")
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any("problem_manifest.content_digest 缺失" in f for f in validator.failures)


def test_ai_metadata_model_mismatch_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """Baseline and treatment must use the same model."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "treatment" / "ai_run_metadata.json", {"model": "DifferentModel"})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("ai_run_metadata.model 不一致" in f for f in validator.failures)


def test_ai_metadata_reasoning_effort_mismatch_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    """Baseline and treatment must use the same reasoning_effort."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "treatment" / "ai_run_metadata.json", {"reasoning_effort": "low"})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("ai_run_metadata.reasoning_effort 不一致" in f for f in validator.failures)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("client_version", "2.0.0"),
        ("temperature", 1.0),
        ("seed", 7),
        ("tool_permissions", ["terminal"]),
        ("working_directory_mode", "shared"),
    ],
)
def test_ai_metadata_additional_pair_configuration_mismatch_fails(
    validator, valid_matrix, valid_patch_index, tmp_path, field, value
):
    """对照组的客户端、采样和权限配置也必须保持一致。"""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "treatment" / "ai_run_metadata.json", {field: value})
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any(f"ai_run_metadata.{field} 不一致" in f for f in validator.failures)


@pytest.mark.parametrize(
    ("metadata_version", "should_pass"),
    [("0.9.0", False), ("1.0.0", True), ("1.1.0", True)],
)
def test_ai_metadata_minimum_version_is_enforced(
    validator, valid_matrix, valid_patch_index, tmp_path, metadata_version, should_pass
):
    """政策的 metadata_version_minimum 必须执行 SemVer 比较。"""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "baseline" / "ai_run_metadata.json", {"metadata_version": metadata_version})
    modify_json(fix_dir / "treatment" / "ai_run_metadata.json", {"metadata_version": metadata_version})
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            version_failures = [f for f in validator.failures if "metadata_version" in f]
            assert bool(version_failures) is (not should_pass)


def test_ai_metadata_time_comparison_uses_timezones(validator, valid_matrix, valid_patch_index, tmp_path):
    """不同时区的等价/递进时间不能按字符串误判。"""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(
        fix_dir / "baseline" / "ai_run_metadata.json",
        {"started_at": "2026-07-10T12:00:00+09:00", "completed_at": "2026-07-10T11:30:00+08:00"},
    )
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert not any("早于 started_at" in f for f in validator.failures)


def test_pending_ai_metadata_cannot_be_promotion_evidence(validator, valid_matrix, valid_patch_index, tmp_path):
    """pending 文件可通过脚手架 Schema，但不能通过晋级校验。"""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "baseline" / "ai_run_metadata.json", {"status": "pending"})
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any("status 必须为 completed" in f for f in validator.failures)


def test_ai_metadata_absolute_path_in_note_rejected(validator, valid_matrix, valid_patch_index, tmp_path):
    """Absolute local paths in note field are rejected."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "baseline" / "ai_run_metadata.json", {"note": "run from E:\\AI\\数模"})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("绝对路径" in f for f in validator.failures)


def test_ai_metadata_legacy_grandfathered_passes_without_file(validator, valid_matrix, valid_patch_index, tmp_path):
    """Legacy grandfathered evidence still passes even without ai_run_metadata.json."""
    fix_dir = _copy_fixture(tmp_path)
    (fix_dir / "baseline" / "ai_run_metadata.json").unlink()
    (fix_dir / "treatment" / "ai_run_metadata.json").unlink()
    # Mark as legacy grandfathered and register the fixture as the only allowed historical group.
    valid_matrix["patches"][0]["negative"]["evidence"]["schema_generation"] = "legacy_v1_grandfathered"
    _setup_fixture_paths(fix_dir, valid_matrix)
    modify_json(fix_dir / "baseline" / "run_manifest.json", {"created_at": "2026-07-10T17:00:00+08:00"})
    modify_json(fix_dir / "treatment" / "run_manifest.json", {"created_at": "2026-07-10T17:00:00+08:00"})

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            with patch("validate_repository.pe_load_json", return_value=_fixture_legacy_policy(fix_dir)):
                validator.validate_patch_promotion()
                assert not validator.failures


@pytest.mark.parametrize("path_key", ["baseline_run", "treatment_run"])
def test_legacy_evidence_path_must_match_its_fixed_role(
    validator, valid_matrix, valid_patch_index, tmp_path, path_key
):
    """历史 baseline/treatment 路径都必须逐一匹配政策登记值。"""
    fix_dir = _copy_fixture(tmp_path)
    (fix_dir / "baseline" / "ai_run_metadata.json").unlink()
    (fix_dir / "treatment" / "ai_run_metadata.json").unlink()
    valid_matrix["patches"][0]["negative"]["evidence"]["schema_generation"] = "legacy_v1_grandfathered"
    _setup_fixture_paths(fix_dir, valid_matrix)
    modify_json(fix_dir / "baseline" / "run_manifest.json", {"created_at": "2026-07-10T17:00:00+08:00"})
    modify_json(fix_dir / "treatment" / "run_manifest.json", {"created_at": "2026-07-10T17:00:00+08:00"})
    legacy_policy = _fixture_legacy_policy(fix_dir)
    legacy_policy["diagnosis_schema_requirements"]["legacy_evidence_paths"]["GRP-01"][path_key] = str(
        fix_dir / "not_registered"
    )

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            with patch("validate_repository.pe_load_json", return_value=legacy_policy):
                validator.validate_patch_promotion()
                assert any(f"legacy {path_key}" in failure for failure in validator.failures)


def test_forged_legacy_marker_cannot_bypass_metadata_gate(validator, valid_matrix, valid_patch_index, tmp_path):
    """仅追加 legacy 标记、未进入 allowlist 的新证据必须仍被拒绝。"""
    fix_dir = _copy_fixture(tmp_path)
    (fix_dir / "baseline" / "ai_run_metadata.json").unlink()
    valid_matrix["patches"][0]["negative"]["evidence"]["schema_generation"] = "legacy_v1_grandfathered"
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any("legacy 证据组不在 allowlist" in f for f in validator.failures)
            assert any("缺少 ai_run_metadata.json" in f for f in validator.failures)


def test_evidence_manifest_path_hash_and_role_are_verified(validator, valid_matrix, valid_patch_index, tmp_path):
    """证据清单必须拒绝目录穿越、错误哈希和缺失角色。"""
    fix_dir = _copy_fixture(tmp_path)
    evidence_path = fix_dir / "baseline" / "run_evidence_manifest.json"
    evidence = json.loads(evidence_path.read_text("utf-8"))
    evidence["artifacts"][0]["path"] = "../outside.json"
    evidence["artifacts"][1]["sha256"] = "0" * 64
    evidence["artifacts"] = [item for item in evidence["artifacts"] if item["role"] != "human_review"]
    evidence_path.write_text(json.dumps(evidence), "utf-8")
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any("run_evidence_manifest" in f and ("路径" in f or "sha256" in f or "角色" in f) for f in validator.failures)


def test_evidence_manifest_role_must_reference_its_fixed_file(validator, valid_matrix, valid_patch_index, tmp_path):
    """每个证据角色只能引用政策登记的固定文件。"""
    fix_dir = _copy_fixture(tmp_path)
    evidence_path = fix_dir / "baseline" / "run_evidence_manifest.json"
    evidence = json.loads(evidence_path.read_text("utf-8"))
    response = next(item for item in evidence["artifacts"] if item["role"] == "model_response")
    human_review = fix_dir / "baseline" / "human_review.md"
    response["path"] = "human_review.md"
    response["size_bytes"] = human_review.stat().st_size
    response["sha256"] = hashlib.sha256(human_review.read_bytes()).hexdigest()
    evidence_path.write_text(json.dumps(evidence), "utf-8")
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any("角色 model_response 必须对应固定文件" in failure for failure in validator.failures)


def test_request_model_and_runtime_version_must_match_run_metadata_and_manifest(
    validator, valid_matrix, valid_patch_index, tmp_path
):
    """同一运行的请求模型与 runtime 版本不能同内部事实冲突。"""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "baseline" / "request.json", {"model": "WrongModel", "runtime_version": "9.9.9"})
    _setup_fixture_paths(fix_dir, valid_matrix)

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=lambda self, raw: Path(raw).resolve()):
            validator.validate_patch_promotion()
            assert any("request.model 与 ai_run_metadata.model 不一致" in failure for failure in validator.failures)
            assert any("request.runtime_version 与 run_manifest.runtime_version 不一致" in failure for failure in validator.failures)

def test_evaluate_status_eligibility_stable_fail_closed():
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT / 'scripts') not in sys.path:
        sys.path.insert(0, str(ROOT / 'scripts'))
    from promotion_engine import evaluate_status_eligibility
    
    # 1. Missing stable_evidence config in policy
    policy_missing = {"status_rules": {"competition_evidenced": {}}}
    report = evaluate_status_eligibility({"patch_id": "A"}, {}, policy_missing, "competition_evidenced")
    assert not report.eligible
    assert any("缺少 stable_evidence 配置" in gap for gap in report.gaps)
    
    # 2. stable_evidence config required is False
    policy_not_required = {"status_rules": {"competition_evidenced": {"stable_evidence": {"required": False}}}}
    report = evaluate_status_eligibility({"patch_id": "A"}, {}, policy_not_required, "competition_evidenced")
    assert not report.eligible
    assert any("未启用 stable_evidence.required" in gap for gap in report.gaps)
    
    # 3. Patch missing stable_evidence
    policy_valid = {"status_rules": {"competition_evidenced": {"stable_evidence": {"required": True}}}}
    report = evaluate_status_eligibility({"patch_id": "A"}, {}, policy_valid, "competition_evidenced")
    assert not report.eligible
    assert any("必须提供 stable_evidence 对象" in gap for gap in report.gaps)


def test_deprecated_patch_is_a_valid_terminal_state():
    policy = json.loads((ROOT / "policies/promotion_policy.json").read_text("utf-8"))
    report = evaluate_status_eligibility(
        {"patch_id": "A092", "status": "deprecated"},
        {},
        policy,
        "deprecated",
    )

    assert report.eligible


@pytest.mark.parametrize("risk", ["M1", "M2", "M3", "M5"])
def test_forbidden_material_risk_blocks_promotion(tmp_path, risk):
    """failure_labels.json 中的禁止材料风险必须阻断晋级。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record_path = run_dir / "validation.md"
    record_path.write_text("validation record", encoding="utf-8")
    (run_dir / "failure_labels.json").write_text(
        json.dumps({"labels": [], "material_risks": [risk]}),
        encoding="utf-8",
    )
    report = evaluate_status_eligibility(
        {"patch_id": "A001", "status": "review_ready", "validation_records": [str(record_path)]},
        {},
        {"status_rules": {"review_ready": {"forbidden_material_risks": [risk]}}},
        "review_ready",
    )
    assert any(f"禁止材料风险：{risk}" in gap for gap in report.gaps)
