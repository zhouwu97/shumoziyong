from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collector_isolation import prepare_isolated_run  # noqa: E402


def _source(root: Path) -> Path:
    root.mkdir()
    for name in ("execution_spec.json", "model_route_v2.json", "environment_lock.json"):
        (root / name).write_text("{}", encoding="utf-8")
    (root / "workspace" / "code").mkdir(parents=True)
    (root / "workspace" / "code" / "solve.py").write_text("print('ok')", encoding="utf-8")
    (root / "materials").mkdir()
    (root / "materials" / "input.txt").write_text("official", encoding="utf-8")
    return root


def test_collector_copies_only_whitelisted_inputs_to_fresh_directory(tmp_path: Path) -> None:
    target, hashes = prepare_isolated_run(_source(tmp_path / "source"), tmp_path / "collector")
    assert (target / "workspace" / "output").is_dir()
    assert not any((target / "workspace" / "output").iterdir())
    assert "workspace/code/solve.py" in hashes
    assert json.loads((target / "manifest.json").read_text("utf-8"))["input_hashes"] == hashes


def test_collector_rejects_candidate_output_in_input_tree(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    (source / "candidate_execution_record.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="未声明|Candidate"):
        prepare_isolated_run(source, tmp_path / "collector")
