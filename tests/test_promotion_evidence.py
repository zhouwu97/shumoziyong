import json
import shutil
from pathlib import Path
import pytest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_repository import RepositoryValidator

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "valid_promotion_evidence"

@pytest.fixture
def validator():
    return RepositoryValidator()

@pytest.fixture
def valid_matrix():
    return json.loads((FIXTURE_DIR / "matrix.json").read_text("utf-8"))

@pytest.fixture
def valid_patch_index():
    return json.loads((FIXTURE_DIR / "patch_index.json").read_text("utf-8"))

def modify_json(path, updates):
    data = json.loads(path.read_text("utf-8"))
    for k, v in updates.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    path.write_text(json.dumps(data), "utf-8")

def test_valid_evidence_passes(validator, valid_matrix, valid_patch_index):
    with patch.object(validator, 'load_json', side_effect=lambda x: valid_matrix if 'matrix' in x else valid_patch_index):
        validator.validate_patch_promotion()
        assert not validator.failures

def test_simulated_precheck_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "baseline" / "run_manifest.json", {"evidence_validity": "simulated_precheck"})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    
    with patch.object(validator, 'load_json', side_effect=lambda x: valid_matrix if 'matrix' in x else valid_patch_index):
        validator.validate_patch_promotion()
        assert any("evidence_validity 不是 real_ai_run" in f for f in validator.failures)

def test_eligible_for_promotion_false_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "baseline" / "run_manifest.json", {"eligible_for_promotion": False})
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    
    with patch.object(validator, 'load_json', side_effect=lambda x: valid_matrix if 'matrix' in x else valid_patch_index):
        validator.validate_patch_promotion()
        assert any("eligible_for_promotion 为 false" in f for f in validator.failures)

def test_request_prompt_empty_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "treatment" / "request.json", {"prompt": ""})
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    
    with patch.object(validator, 'load_json', side_effect=lambda x: valid_matrix if 'matrix' in x else valid_patch_index):
        validator.validate_patch_promotion()
        assert any("request.prompt 为空" in f for f in validator.failures)

def test_same_response_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    same_resp = {"data": "same"}
    modify_json(tmp_path / "fixtures" / "baseline" / "response.json", same_resp)
    modify_json(tmp_path / "fixtures" / "treatment" / "response.json", same_resp)
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = str(tmp_path / "fixtures" / "baseline")
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    
    with patch.object(validator, 'load_json', side_effect=lambda x: valid_matrix if 'matrix' in x else valid_patch_index):
        validator.validate_patch_promotion()
        assert any("baseline 和 treatment 的 response 完全相同" in f for f in validator.failures)

def test_path_traversal_fails(validator, valid_matrix, valid_patch_index):
    valid_matrix["patches"][0]["negative"]["evidence"]["baseline_run"] = "../escape"
    with patch.object(validator, 'load_json', side_effect=lambda x: valid_matrix if 'matrix' in x else valid_patch_index):
        validator.validate_patch_promotion()
        assert any("证据路径逃逸仓库" in f for f in validator.failures)

def test_wrong_target_patch_fails(validator, valid_matrix, valid_patch_index, tmp_path):
    shutil.copytree(FIXTURE_DIR, tmp_path / "fixtures")
    modify_json(tmp_path / "fixtures" / "treatment" / "run_manifest.json", {"target_patch": "WRONG"})
    valid_matrix["patches"][0]["negative"]["evidence"]["treatment_run"] = str(tmp_path / "fixtures" / "treatment")
    
    with patch.object(validator, 'load_json', side_effect=lambda x: valid_matrix if 'matrix' in x else valid_patch_index):
        validator.validate_patch_promotion()
        assert any("treatment 运行记录 target_patch 不匹配" in f for f in validator.failures)
