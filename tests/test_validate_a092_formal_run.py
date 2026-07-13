import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def _load_validator_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate_a092_formal_run.py"
    spec = spec_from_file_location("validate_a092_formal_run", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit_isolation = _load_validator_module().audit_isolation


def _write_events(run_dir: Path, events: list[dict[str, object]]) -> None:
    run_dir.mkdir(parents=True)
    text = "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"
    (run_dir / "runner_events.jsonl").write_text(text, encoding="utf-8")


def test_isolation_audit_accepts_own_run_reference(tmp_path: Path) -> None:
    run_dir = tmp_path / "a092_confirmatory_v1" / "R01"
    _write_events(run_dir, [{"command": str(run_dir / "results" / "formal_result.json")}])

    report = audit_isolation(run_dir)

    assert report["valid"] is True
    assert report["forbidden_reference_count"] == 0


def test_isolation_audit_rejects_other_run_reference(tmp_path: Path) -> None:
    run_dir = tmp_path / "a092_confirmatory_v1" / "R01"
    _write_events(run_dir, [{"command": "type a092_confirmatory_v1/R02/results/formal_result.json"}])

    report = audit_isolation(run_dir)

    assert report["valid"] is False
    assert report["forbidden_reference_count"] == 1
