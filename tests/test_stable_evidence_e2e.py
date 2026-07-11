import pytest
from pathlib import Path
import json
import shutil
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_repository import RepositoryValidator

def mock_load_json(matrix, patch_index):
    def _load_json(x):
        if 'matrix.json' in str(x): return matrix
        if 'patch_index.json' in str(x): return patch_index
        return RepositoryValidator().load_json(x)
    return _load_json

def test_fully_valid_stable_patch_passes_repository_validator(tmp_path):
    validator = RepositoryValidator()
    fix_dir = tmp_path / "fixtures"
    shutil.copytree(ROOT / "tests/fixtures/valid_stable_evidence", fix_dir)
    
    def mock_resolve(self, raw):
        raw_str = str(raw)
        if raw_str.startswith("tests/fixtures/valid_stable_evidence"):
            # replace the prefix with fix_dir
            return fix_dir / Path(raw_str).relative_to("tests/fixtures/valid_stable_evidence")
        return Path(raw).resolve()
    
    with patch.object(RepositoryValidator, 'resolve_repo_path', new=mock_resolve):
        validator.workspace = fix_dir
        patch_index = validator.load_json(fix_dir / "patch_index.json")
        matrix = validator.load_json(fix_dir / "matrix.json")
        with patch.object(validator, 'load_json', side_effect=mock_load_json(matrix, patch_index)):
            validator.validate_patch_promotion()
            assert not validator.failures
