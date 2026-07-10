import pytest
import json
import shutil
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_repository import RepositoryValidator

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

def test_valid_evidence_passes(validator, valid_matrix, valid_patch_index):
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        validator.validate_patch_promotion()
        assert not validator.failures
        assert (
            "patch 晋级规则（promotion_policy.json 统一评估 + 负控证据验证）"
            in validator.passes
        )

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


def test_ai_metadata_valid_passes(validator, valid_matrix, valid_patch_index, tmp_path):
    """Valid ai_run_metadata on both baseline and treatment passes."""
    fix_dir = _copy_fixture(tmp_path)
    _setup_fixture_paths(fix_dir, valid_matrix)

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
    """runtime_pack_sha256 doesn't match actual manifest file hash."""
    fix_dir = _copy_fixture(tmp_path)
    modify_json(fix_dir / "treatment" / "ai_run_metadata.json", {"runtime_pack_sha256": "b" * 64})
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("ai_run_metadata.runtime_pack_sha256 不匹配" in f for f in validator.failures)


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
    # Mark as legacy grandfathered
    valid_matrix["patches"][0]["negative"]["evidence"]["schema_generation"] = "legacy_v1_grandfathered"
    _setup_fixture_paths(fix_dir, valid_matrix)

    def mock_resolve(self, raw):
        return Path(raw).resolve()

    with patch.object(validator, "load_json", side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, "resolve_repo_path", new=mock_resolve):
            validator.validate_patch_promotion()
            assert not validator.failures
