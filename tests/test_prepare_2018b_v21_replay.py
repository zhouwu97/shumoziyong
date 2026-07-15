from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_2018b_v21_replay import (  # noqa: E402
    EVENT_FIELDS,
    METRIC_FIELDS,
    OUTPUT_REQUIRED_FILES,
    PART_FIELDS,
    REPAIR_REQUIRED_FILES,
    OutputContractError,
    build_matlab_inputs,
    prepare_contracts,
    sha256_file,
    validate_candidate_outputs,
)
from run_matlab_recomputation import run_recomputation, validate_input  # noqa: E402


MATLAB = Path(r"E:\Matlab\bin\matlab.exe")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parameters() -> dict:
    return {
        "schema_version": "1.0.0",
        "problem_id": "2018-B",
        "horizon_seconds": 40,
        "initial_rgv_position": 0,
        "cnc_positions": {str(i): (i - 1) // 2 for i in range(1, 9)},
        "parameter_groups": {
            "1": {
                "move_seconds": {"0": 0, "1": 2, "2": 3, "3": 4},
                "one_stage_process_seconds": 10,
                "two_stage_process_seconds": {"1": 6, "2": 7},
                "service_seconds": {"odd": 2, "even": 2},
                "clean_seconds": 1,
            },
            "2": {
                "move_seconds": {"0": 0, "1": 2, "2": 3, "3": 4},
                "one_stage_process_seconds": 10,
                "two_stage_process_seconds": {"1": 6, "2": 7},
                "service_seconds": {"odd": 2, "even": 2},
                "clean_seconds": 1,
            },
            "3": {
                "move_seconds": {"0": 0, "1": 2, "2": 3, "3": 4},
                "one_stage_process_seconds": 10,
                "two_stage_process_seconds": {"1": 6, "2": 7},
                "service_seconds": {"odd": 2, "even": 2},
                "clean_seconds": 1,
            },
        },
        "fault_model": {},
        "formal_seed": 2018001,
        "stochastic_seeds": list(range(2018001, 2018101)),
        "counting_rule": "unique part with clean_end_seconds <= horizon_seconds",
        "return_rule": "post_shift",
    }


def _initialized_run(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_json(
        run_dir / "run_manifest.json",
        {
            "run_id": "2018b-v21-test",
            "problem_id": "2018-B",
            "profile": "engineering_optimization",
            "runtime_version": "0.2.0",
            "runtime_pack_sha256": "a" * 64,
            "runtime_manifest_version": "1.3.0",
            "gate_contract_version": "2.1.0",
            "classification": "development_benchmark",
            "blind_generalization": False,
            "profile_promotion_eligible": False,
        },
    )
    _write_json(run_dir / "problem_manifest.json", {"problem_id": "2018-B"})
    repair = tmp_path / "repair"
    for relative in REPAIR_REQUIRED_FILES:
        path = repair / relative
        if relative == "parameters.json":
            _write_json(path, _parameters())
        elif relative == "manual_case.json":
            _write_json(path, {"schema_version": "1.0.0", "cnc_count": 2})
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'"""测试冻结文件 {relative}。"""\n', encoding="utf-8")
    official = tmp_path / "official"
    _write_json(
        official / "material_manifest.json",
        {
            "manifest_version": "1.0.0",
            "problem_id": "2018-B",
            "categories": {},
        },
    )
    prepare_contracts(
        run_dir,
        repair,
        official,
        git_identity={
            "repository": str(tmp_path),
            "workspace_relative_path": "repair",
            "commit": "b" * 40,
            "dirty": False,
        },
    )
    return run_dir, repair, official


def _event(run_key: str, sequence: int, event_type: str, start: int, end: int, resource_type: str, resource_id: str, **overrides: object) -> dict:
    value = {
        "run_key": run_key,
        "sequence": sequence,
        "start_seconds": start,
        "end_seconds": end,
        "event_type": event_type,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action_id": None,
        "part_id": None,
        "stage": None,
        "state_before": None,
        "state_after": None,
        "payload": {},
    }
    value.update(overrides)
    assert set(EVENT_FIELDS) <= set(value)
    return value


def _candidate_outputs(run_dir: Path) -> None:
    output = run_dir / "workspace" / "output"
    run_key = "det-g1-p1-ect_rollout"
    metrics = {
        "completed_clean_products": 1,
        "scrapped_parts": 0,
        "started_parts": 1,
        "unfinished_parts": 0,
        "rgv_busy_seconds": 5,
        "rgv_wait_seconds": 10,
        "rgv_utilization": 0.125,
        "cnc_processing_seconds": 10,
        "cnc_utilization": 0.03125,
        "cnc_waiting_seconds": 0,
        "n_wip_at_horizon": 0,
        "rgv_end_seconds": 15,
        "post_shift_return_seconds": 0,
        "final_rgv_position": 0,
        "action_count": 2,
        "fallback_count": 0,
    }
    assert set(METRIC_FIELDS) <= set(metrics)
    _write_json(
        output / "run_summary.json",
        {
            "schema_version": "1.0.0",
            "problem_id": "2018-B",
            "horizon_seconds": 28800,
            "counting_rule": "unique clean end",
            "objective_contract": {
                "directions": ["maximize", "minimize", "minimize", "minimize"],
                "lexicographic_order": ["N_clean(H)", "N_WIP(H)", "W_CNC", "T_RGV_end"],
            },
            "deterministic_runs": [
                {
                    "run_key": run_key,
                    "parameter_group": 1,
                    "process_type": 1,
                    "policy": "ect_rollout",
                    "comparison_protocol": "same_machine_configuration",
                    "metrics": metrics,
                }
            ],
        },
    )
    part = {
        "part_id": 1,
        "process_type": 1,
        "stage1_cnc": 1,
        "stage1_load_seconds": 2,
        "stage1_unload_seconds": 14,
        "stage2_cnc": None,
        "stage2_load_seconds": None,
        "stage2_unload_seconds": None,
        "clean_start_seconds": 14,
        "clean_end_seconds": 15,
        "status": "cleaned",
        "scrapped_at_seconds": None,
    }
    assert set(PART_FIELDS) <= set(part)
    _write_json(output / "schedules.json", {"schema_version": "1.0.0", "runs": [{"run_key": run_key, "parts": [part]}]})
    events = [
        _event(run_key, 1, "rgv_move", 0, 0, "RGV", "RGV", action_id="a1", payload={"from_position": 0, "to_position": 0}),
        _event(run_key, 2, "rgv_service", 0, 2, "RGV", "RGV", action_id="a1", payload={"cnc_id": 1}),
        _event(run_key, 3, "cnc_service", 0, 2, "CNC", "1", action_id="a1", state_before="idle"),
        _event(run_key, 4, "rgv_wait", 2, 12, "RGV", "RGV"),
        _event(run_key, 5, "cnc_processing", 2, 12, "CNC", "1", part_id=1, stage=1, state_before="processing", state_after="ready"),
        _event(run_key, 6, "cnc_process_end", 12, 12, "CNC", "1", part_id=1, stage=1, state_before="processing", state_after="ready"),
        _event(run_key, 7, "rgv_move", 12, 12, "RGV", "RGV", action_id="a2", payload={"from_position": 0, "to_position": 0}),
        _event(run_key, 8, "rgv_service", 12, 14, "RGV", "RGV", action_id="a2", payload={"cnc_id": 1}),
        _event(run_key, 9, "cnc_service", 12, 14, "CNC", "1", action_id="a2", state_before="ready"),
        _event(run_key, 10, "rgv_clean", 14, 15, "RGV", "RGV", action_id="a2", part_id=1),
        _event(run_key, 11, "cleaning_slot", 14, 15, "cleaning_slot", "slot_1", action_id="a2", part_id=1),
        _event(run_key, 12, "clean_end", 15, 15, "part", "1", action_id="a2", part_id=1, state_after="cleaned"),
    ]
    output.mkdir(parents=True, exist_ok=True)
    with gzip.open(output / "events.jsonl.gz", "wt", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    _write_json(output / "constraint_self_check.json", {"passed": True})
    _write_json(output / "random_trials.json", {"schema_version": "1.0.0", "rows": []})
    _write_json(output / "figure_data.json", {"schema_version": "1.0.0"})
    _write_json(
        output / "validity_evidence.json",
        {"schema_version": "1.0.0", "status": "passed"},
    )
    _write_json(output / "result.json", {"objective": 1})


def test_prepare_contracts_freezes_source_identity_and_valid_schemas(tmp_path: Path) -> None:
    run_dir, _repair, _official = _initialized_run(tmp_path)
    schema_pairs = {
        "model_route_v2_1.json": "model_route_v2_1.schema.json",
        "model_validity_contract.json": "model_validity_contract.schema.json",
        "validator_independence_manifest.json": "validator_independence_manifest.schema.json",
        "execution_spec.json": "execution_spec.schema.json",
    }
    for artifact, schema in schema_pairs.items():
        value = json.loads((run_dir / artifact).read_text(encoding="utf-8"))
        contract = json.loads((ROOT / "schemas" / schema).read_text(encoding="utf-8"))
        assert list(Draft202012Validator(contract).iter_errors(value)) == []
    source = json.loads((run_dir / "repair_source_manifest.json").read_text(encoding="utf-8"))
    assert source["source_git"]["commit"] == "b" * 40
    assert source["source_git"]["dirty"] is False
    assert all(item["sha256"] == sha256_file(run_dir / item["target_path"]) for item in source["files"])
    execution = json.loads((run_dir / "execution_spec.json").read_text(encoding="utf-8"))
    task = execution["tasks"][0]
    assert task["timeout_seconds"] == 7200
    assert {item["path"] for item in task["inputs"]} == {
        "problem/parameters.json",
        "problem/manual_case.json",
    }
    assert {item["path"] for item in task["required_outputs"]} == {
        f"workspace/output/{name}" for name in OUTPUT_REQUIRED_FILES
    }
    benchmark = json.loads((run_dir / "benchmark_classification.json").read_text(encoding="utf-8"))
    assert all(item["blind_generalization"] is False for item in benchmark["cases"].values())
    binding = json.loads((run_dir / "formal_result_binding_plan.json").read_text(encoding="utf-8"))
    assert binding["required_fields"] == [
        "run_id",
        "problem_manifest_sha256",
        "execution_spec_sha256",
        "source_manifest_sha256",
        "execution_started_at",
        "created_at",
        "activation_status",
        "formal_result_ref",
    ]


def test_missing_candidate_outputs_fail_closed_with_expected_fields(tmp_path: Path) -> None:
    run_dir, _repair, _official = _initialized_run(tmp_path)
    with pytest.raises(OutputContractError) as exc_info:
        validate_candidate_outputs(run_dir)
    message = str(exc_info.value)
    assert "run_summary.json 不存在" in message
    assert "schedules.json 不存在" in message
    assert "events.jsonl.gz 不存在" in message
    assert not (run_dir / "matlab_level_a_input.json").exists()


def test_incomplete_candidate_metrics_fail_closed_with_field_names(tmp_path: Path) -> None:
    run_dir, _repair, _official = _initialized_run(tmp_path)
    _candidate_outputs(run_dir)
    summary_path = run_dir / "workspace" / "output" / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    del summary["deterministic_runs"][0]["metrics"]["cnc_waiting_seconds"]
    _write_json(summary_path, summary)
    with pytest.raises(OutputContractError) as exc_info:
        validate_candidate_outputs(run_dir)
    assert "deterministic_runs[0].metrics 缺字段: cnc_waiting_seconds" in str(exc_info.value)


def test_matlab_inputs_bind_all_rgv_files_and_two_to_four_cnc_cases(tmp_path: Path) -> None:
    run_dir, _repair, _official = _initialized_run(tmp_path)
    _candidate_outputs(run_dir)
    build_matlab_inputs(run_dir)
    level_a_path = run_dir / "matlab_level_a_input.json"
    level_a = json.loads(level_a_path.read_text(encoding="utf-8"))
    assert level_a["model_kind"] == "rgv_2018b"
    assert level_a["rgv_contract"]["objective_order"] == ["N_clean(H)", "-N_WIP(H)", "-W_CNC", "-T_RGV_end"]
    refs = validate_input(run_dir, level_a, "A")["additional_input_refs"]
    assert set(refs) == {"parameters_ref", "schedules_ref", "events_ref", "constraint_self_check_ref"}
    level_b = json.loads((run_dir / "matlab_level_b_input.json").read_text(encoding="utf-8"))
    assert [item["cnc_count"] for item in level_b["small_examples"]] == [2, 4]
    assert all(item["example_kind"] == "rgv_dynamic_one_stage" for item in level_b["small_examples"])
    assert all("不代表完整模型独立求解" in item["model_scope"] for item in level_b["small_examples"])

    (run_dir / "workspace" / "output" / "schedules.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        validate_input(run_dir, level_a, "A")


def test_matlab_source_contains_dedicated_rgv_branch() -> None:
    source = (ROOT / "matlab" / "v21" / "v21_level_a.m").read_text(encoding="utf-8")
    assert "rgv_2018b_checks" in source
    assert "maximum_resource_overlap" in source
    assert "official_duration_residual" in source
    assert "read_gzip_json_lines" in source


@pytest.mark.skipif(not MATLAB.is_file(), reason="MATLAB executable unavailable")
def test_rgv_level_a_and_level_b_execute_in_real_matlab(tmp_path: Path) -> None:
    run_dir, _repair, _official = _initialized_run(tmp_path)
    _candidate_outputs(run_dir)
    # 测试时域改为40秒，使人工原子事件与冻结参数形成可手算闭环。
    parameters_path = run_dir / "problem" / "parameters.json"
    parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
    parameters["horizon_seconds"] = 40
    _write_json(parameters_path, parameters)
    build_matlab_inputs(run_dir)
    report_a = run_recomputation(run_dir, run_dir / "matlab_level_a_input.json", run_dir / "matlab_level_a_report.json", "A")
    report_b = run_recomputation(run_dir, run_dir / "matlab_level_b_input.json", run_dir / "matlab_level_b_report.json", "B")
    assert report_a["status"] == "passed"
    assert report_b["status"] == "passed"
    assert all(item["passed"] for item in report_a["checks"])
    assert all(item["passed"] for item in report_b["checks"])
