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

def test_simulated_precheck_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    # We will patch resolve_repo_path to allow tmp_path
    def mock_resolve(self, raw):
        return Path(raw).resolve()
        
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
    same_resp = {"data": "same"}
    (tmp_path / "fixtures" / "baseline" / "response.json").write_text(json.dumps(same_resp), 'utf-8')
    (tmp_path / "fixtures" / "treatment" / "response.json").write_text(json.dumps(same_resp), 'utf-8')
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("现场重算发现错误" in f or "符合 diagnosis_output" in f for f in validator.failures)

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
    modify_json(tmp_path / "fixtures" / "comparison_review.json", {"risk_flags": {"changed_primary_type": True}})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    valid_matrix["patches"][0]["negative"]["evidence"]["comparison_review"] = str(tmp_path / "fixtures" / "comparison_review.json")
    
    with patch.object(validator, 'load_json', side_effect=mock_load_json(valid_matrix, valid_patch_index)):
        with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
            validator.validate_patch_promotion()
            assert any("False was expected" in f or "Schema" in f for f in validator.failures)
