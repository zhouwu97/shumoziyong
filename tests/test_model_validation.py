from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_validation import validate_model_and_execution  # noqa: E402


def _report(model_type: str = "descriptive") -> dict[str, object]:
    return {
        "metrics": [{"name": "objective", "value": 1.0}],
        "model_contract": {
            "model_type": model_type,
            "variables": [{"name": "x"}],
            "parameters": [{"name": "p"}],
            "formulas": [{"formula_id": "F1", "symbols": ["x", "p"]}],
            "unit_checks": [{"expression": "x+p", "compatible": True}],
            "claim_result_bindings": [{"claim_id": "C001", "metric": "objective"}],
            "optimization_checks": {
                "configured": [],
                "passed": [],
                "not_applicable": {},
            },
        },
    }


def _manifest() -> dict[str, object]:
    return {
        "random_seeds": [0],
        "deterministic_expected": True,
        "repeated_runs": [
            {
                "execution_id": "repeat-1",
                "seed": 0,
                "started_at": "2026-07-11T00:00:00Z",
                "completed_at": "2026-07-11T00:00:01Z",
                "exit_code": 0,
                "output_sha256": "a" * 64,
                "stdout_sha256": "b" * 64,
                "environment_sha256": "c" * 64,
            },
            {
                "execution_id": "repeat-2",
                "seed": 0,
                "started_at": "2026-07-11T00:00:02Z",
                "completed_at": "2026-07-11T00:00:03Z",
                "exit_code": 0,
                "output_sha256": "a" * 64,
                "stdout_sha256": "b" * 64,
                "environment_sha256": "c" * 64,
            },
        ],
        "inputs": [],
        "outputs": [],
    }


def test_undefined_formula_symbol_fails() -> None:
    report = _report()
    report["model_contract"]["formulas"][0]["symbols"].append("undefined")
    errors = validate_model_and_execution(report, _manifest())
    assert any("未定义符号" in error for error in errors)


def test_unit_mismatch_fails() -> None:
    report = _report()
    report["model_contract"]["unit_checks"][0]["compatible"] = False
    errors = validate_model_and_execution(report, _manifest())
    assert any("量纲检查未通过" in error for error in errors)


def test_claim_must_bind_existing_metric_and_claim_map() -> None:
    report = _report()
    report["model_contract"]["claim_result_bindings"][0]["metric"] = "missing"
    claim_map = {"claims": [{"claim_id": "C002"}]}
    errors = validate_model_and_execution(report, _manifest(), claim_map=claim_map)
    assert any("不存在的结果指标" in error for error in errors)
    assert any("绑定不完整" in error for error in errors)


def test_deterministic_repeats_require_same_output_hash() -> None:
    manifest = _manifest()
    manifest["repeated_runs"][1]["output_sha256"] = "b" * 64
    errors = validate_model_and_execution(_report(), manifest)
    assert any("输出哈希不一致" in error for error in errors)


def test_mip_enables_model_specific_checks() -> None:
    errors = validate_model_and_execution(_report("mip"), _manifest())
    assert any("mip_gap" in error and "feasibility" in error for error in errors)


def test_not_applicable_reason_can_cover_irrelevant_special_check() -> None:
    report = _report("mip")
    required = {
        "baseline",
        "feasibility",
        "constraint_residual",
        "mip_gap",
        "bounds",
        "sensitivity",
    }
    report["model_contract"]["optimization_checks"] = {
        "configured": sorted(required - {"mip_gap"}),
        "passed": sorted(required - {"mip_gap"}),
        "not_applicable": {
            "mip_gap": {
                "reason": "The selected solver does not expose a MIP gap.",
                "condition": "The model is solved by a continuous relaxation only.",
            }
        },
    }
    assert validate_model_and_execution(report, _manifest()) == []


def test_repeated_runs_require_unique_execution_ids() -> None:
    manifest = _manifest()
    manifest["repeated_runs"][1]["execution_id"] = "repeat-1"

    errors = validate_model_and_execution(_report(), manifest)

    assert any("execution_id" in error and "唯一" in error for error in errors)


def test_randomized_model_requires_distinct_repeat_seeds() -> None:
    manifest = _manifest()
    manifest["deterministic_expected"] = False

    errors = validate_model_and_execution(_report("heuristic"), manifest)

    assert any("不同 seed" in error for error in errors)


def test_mandatory_optimization_checks_cannot_be_not_applicable() -> None:
    report = _report("mip")
    report["model_contract"]["optimization_checks"] = {
        "configured": ["baseline", "mip_gap", "sensitivity"],
        "passed": ["baseline", "mip_gap", "sensitivity"],
        "not_applicable": {
            "feasibility": "The author chose not to run this check.",
            "constraint_residual": "The author chose not to run this check.",
            "bounds": "The author chose not to run this check.",
        },
    }

    errors = validate_model_and_execution(report, _manifest())

    assert any("不可豁免" in error and "feasibility" in error for error in errors)
