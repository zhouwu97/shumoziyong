from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import competition_route_runtime  # noqa: E402
from competition_route_runtime import (  # noqa: E402
    CompetitionRouteRuntimeError,
    evaluate_competition_gate3,
    execute_three_routes,
)
from formal_result.hashing import file_sha256  # noqa: E402
from formal_result_fixtures import write_formal_result_bundle  # noqa: E402
from route_contract_dispatch import RouteContractError  # noqa: E402
from test_route_contract_dispatch import (  # noqa: E402
    _comparison,
    _model_route_v3,
    _operability_contract,
    _operability_report,
    _risk_contract,
    _risk_report,
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _child_manifest(model: dict[str, Any], child_run_id: str) -> dict[str, Any]:
    return {
        "run_id": child_run_id,
        "problem_id": model["problem_id"],
        "profile": model["profile"],
        "runtime_version": model["runtime_version"],
        "runtime_pack_sha256": model["runtime_pack_sha256"],
        "formal_result_policy": "required_v1",
        "execution_contract_version": "1.0.0",
        "formal_result_contract_version": "1.0.0",
        "canonicalization_version": "1.0.0",
        "gate_artifact_contract_version": "1.0.0",
    }


def _prepare_children(parent: Path, model: dict[str, Any]) -> None:
    subproblem = model["subproblems"][0]
    for index, route in enumerate(subproblem["routes"], start=1):
        child = parent / "route_runs" / "Q1" / route["route_id"]
        _write_json(
            child / "run_manifest.json",
            _child_manifest(model, f"child-{route['route_id'].lower()}"),
        )
        write_formal_result_bundle(child, formal_result_id=f"formal-route-{index}")


def _prepare_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    parent = tmp_path / "competition-run"
    parent.mkdir()
    model = _model_route_v3()
    _write_json(parent / "model_route_v3.json", model)
    _write_json(parent / "run_manifest.json", _child_manifest(model, str(model["run_id"])))
    _prepare_children(parent, model)
    monkeypatch.setenv("SHUMO_EXECUTION_CHALLENGE", "fixture-challenge")
    monkeypatch.setenv("SHUMO_RUN_ID", str(model["run_id"]))
    monkeypatch.setenv("SHUMO_EXECUTION_ID", "fixture-execution")
    report = execute_three_routes(parent, "Q1", "fixture-executor")
    assert report["status"] == "completed"
    _write_gate3_evidence(parent, model)
    return parent


def _write_gate3_evidence(parent: Path, model: dict[str, Any]) -> None:
    model_sha = file_sha256(parent / "model_route_v3.json")
    comparison = _comparison()
    comparison["model_route_v3_sha256"] = model_sha
    for route_result in comparison["route_results"]:
        route_id = route_result["route_id"]
        envelope = next(
            (parent / "route_runs" / "Q1" / route_id).glob(
                "formal_results/*/formal_result_envelope.json"
            )
        )
        route_result["formal_result"] = {
            "path": envelope.relative_to(parent).as_posix(),
            "sha256": file_sha256(envelope),
        }
    _write_json(parent / "route_comparison_result_Q1.json", comparison)

    selected_envelope = next(
        (parent / "route_runs" / "Q1" / "R-MAIN").glob(
            "formal_results/*/formal_result_envelope.json"
        )
    )
    operability_contract = _operability_contract()
    operability_contract["model_route_v3_sha256"] = model_sha
    _write_json(parent / "operability_contract_Q1.json", operability_contract)
    operability_report = _operability_report()
    operability_report["operability_contract_sha256"] = file_sha256(
        parent / "operability_contract_Q1.json"
    )
    operability_report["formal_result_sha256"] = file_sha256(selected_envelope)
    _write_json(parent / "operability_report_Q1.json", operability_report)

    risk_contract = _risk_contract()
    risk_contract["model_route_v3_sha256"] = model_sha
    _write_json(parent / "risk_decision_contract_Q1.json", risk_contract)
    risk_report = _risk_report()
    risk_report["risk_decision_contract_sha256"] = file_sha256(
        parent / "risk_decision_contract_Q1.json"
    )
    risk_report["formal_result_sha256"] = file_sha256(selected_envelope)
    _write_json(parent / "risk_decision_report_Q1.json", risk_report)


def _make_formal_results_eligible(monkeypatch: pytest.MonkeyPatch) -> None:
    actual_verify = competition_route_runtime.verify_formal_result_bundle

    def eligible_verify(run_dir: Path, envelope_path: str | Path) -> dict[str, Any]:
        summary = actual_verify(run_dir, envelope_path)
        summary["formal_result_eligible"] = True
        return summary

    monkeypatch.setattr(
        competition_route_runtime, "verify_formal_result_bundle", eligible_verify
    )


def _rewrite_report_for_failed_check(parent: Path, category: str, check_id: str) -> None:
    contract_path = parent / "operability_contract_Q1.json"
    report_path = parent / "operability_report_Q1.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["checks"][0].update(
        {
            "check_id": check_id,
            "category": category,
            "statement": "修复后的方案必须继续满足该硬业务规则",
            "measurement": "逐订单与逐运输段复算违约数量",
            "acceptance_rule": "硬违约数量必须为零",
            "source_ref": f"BC-{category.upper()}",
        }
    )
    _write_json(contract_path, contract)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["operability_contract_sha256"] = file_sha256(contract_path)
    report["checks"][0].update(
        {
            "check_id": check_id,
            "status": "failed",
            "observed": "独立复算发现一个硬违约",
        }
    )
    report["overall_status"] = "failed"
    report["hard_violations"] = [check_id]
    _write_json(report_path, report)


def test_gate2_executes_exactly_three_isolated_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    report = json.loads(
        (parent / "route_execution_report_Q1.json").read_text(encoding="utf-8")
    )
    assert report["all_routes_attempted"] is True
    assert {item["role"] for item in report["routes"]} == {
        "baseline",
        "primary",
        "structural_alternative",
    }
    assert len({item["child_root"] for item in report["routes"]}) == 3
    assert all(item["execution_status"] == "completed" for item in report["routes"])


def test_gate2_preflight_rejects_missing_route_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "missing-route"
    parent.mkdir()
    model = _model_route_v3()
    _write_json(parent / "model_route_v3.json", model)
    _write_json(parent / "run_manifest.json", _child_manifest(model, str(model["run_id"])))
    _prepare_children(parent, model)
    missing = parent / "route_runs" / "Q1" / "R-ALT"
    for path in sorted(missing.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    missing.rmdir()
    monkeypatch.setenv("SHUMO_EXECUTION_CHALLENGE", "fixture-challenge")
    monkeypatch.setenv("SHUMO_RUN_ID", str(model["run_id"]))
    monkeypatch.setenv("SHUMO_EXECUTION_ID", "fixture-execution")
    with pytest.raises(CompetitionRouteRuntimeError, match="缺少路线子 Run"):
        execute_three_routes(parent, "Q1", "fixture-executor")
    assert not list(parent.rglob("candidate_execution_record.json"))


def test_gate2_rejects_parent_run_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent-drift"
    parent.mkdir()
    model = _model_route_v3()
    _write_json(parent / "model_route_v3.json", model)
    manifest = _child_manifest(model, str(model["run_id"]))
    manifest["runtime_pack_sha256"] = "b" * 64
    _write_json(parent / "run_manifest.json", manifest)
    _prepare_children(parent, model)
    with pytest.raises(CompetitionRouteRuntimeError, match="父 run_manifest.runtime_pack_sha256"):
        execute_three_routes(parent, "Q1", "fixture-executor")


def test_gate2_preflights_all_contracts_before_partial_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "invalid-third-route"
    parent.mkdir()
    model = _model_route_v3()
    _write_json(parent / "model_route_v3.json", model)
    _write_json(parent / "run_manifest.json", _child_manifest(model, str(model["run_id"])))
    _prepare_children(parent, model)
    spec_path = parent / "route_runs" / "Q1" / "R-ALT" / "execution_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["tasks"][0]["inputs"][0]["sha256"] = "b" * 64
    _write_json(spec_path, spec)
    with pytest.raises(CompetitionRouteRuntimeError, match="输入缺失或哈希漂移"):
        execute_three_routes(parent, "Q1", "fixture-executor")
    assert not list(parent.rglob("candidate_execution_record.json"))


def test_gate3_allows_paper_only_with_three_eligible_formal_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    _make_formal_results_eligible(monkeypatch)
    decision = evaluate_competition_gate3(parent, "Q1", "independent-validator")
    assert decision["decision"] == "allow_paper"
    assert decision["paper_admission"] is True
    assert decision["decision_codes"] == []
    assert len(decision["formal_results"]) == 3


def test_gate3_downgrades_unqualified_environment_to_technical_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    decision = evaluate_competition_gate3(parent, "Q1", "independent-validator")
    assert decision["decision"] == "technical_report_only"
    assert decision["paper_admission"] is False
    assert decision["technical_report_allowed"] is True
    assert decision["decision_codes"] == ["G3V3_FORMAL_RESULT_INELIGIBLE"]


def test_gate3_validator_must_be_independent_from_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    _make_formal_results_eligible(monkeypatch)
    with pytest.raises(RouteContractError, match="不符合 Schema"):
        evaluate_competition_gate3(parent, "Q1", "fixture-executor")


def test_gate3_rejects_self_reported_execution_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    report_path = parent / "route_execution_report_Q1.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["status"] = "blocked"
    _write_json(report_path, report)
    with pytest.raises(CompetitionRouteRuntimeError, match="顶层 status"):
        evaluate_competition_gate3(parent, "Q1", "independent-validator")


@pytest.mark.parametrize(
    ("category", "check_id"),
    [
        ("continuity", "OP-CONTINUITY-REPAIR"),
        ("minimum_order", "OP-MINIMUM-ORDER"),
        ("transport_split", "OP-TRANSPORT-SPLIT"),
    ],
)
def test_gate3_blocks_repaired_or_operationally_invalid_solutions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    category: str,
    check_id: str,
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    _make_formal_results_eligible(monkeypatch)
    _rewrite_report_for_failed_check(parent, category, check_id)
    decision = evaluate_competition_gate3(parent, "Q1", "independent-validator")
    assert decision["decision"] == "block"
    assert decision["decision_codes"] == ["G3V3_OPERABILITY_FAILED"]


def test_gate3_blocks_time_leakage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    _make_formal_results_eligible(monkeypatch)
    comparison_path = parent / "route_comparison_result_Q1.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    selected = next(
        item for item in comparison["route_results"] if item["route_id"] == "R-MAIN"
    )
    selected["data_leakage_detected"] = True
    _write_json(comparison_path, comparison)
    decision = evaluate_competition_gate3(parent, "Q1", "independent-validator")
    assert decision["decision"] == "block"
    assert "G3V3_DATA_LEAKAGE" in decision["decision_codes"]


def test_gate3_rejects_missing_comparison_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    comparison_path = parent / "route_comparison_result_Q1.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    comparison["pairwise_comparisons"][1] = copy.deepcopy(
        comparison["pairwise_comparisons"][0]
    )
    _write_json(comparison_path, comparison)
    with pytest.raises(RouteContractError, match="路线比较缺少"):
        evaluate_competition_gate3(parent, "Q1", "independent-validator")


def test_gate3_rejects_unexplained_risk_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _prepare_parent(tmp_path, monkeypatch)
    report_path = parent / "risk_decision_report_Q1.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["decisions"][0].update(
        {
            "triggered": True,
            "action": "technical_report_only",
            "downgraded_from_default": True,
        }
    )
    report["overall_action"] = "technical_report_only"
    _write_json(report_path, report)
    with pytest.raises(RouteContractError, match="不符合 Schema"):
        evaluate_competition_gate3(parent, "Q1", "independent-validator")
