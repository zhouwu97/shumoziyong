from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from domains.problem_2024_c.scenarios import (
    ScenarioKeyCatalog,
    generate_manifest_for_catalog,
    iter_scenario_payloads,
    validate_manifest,
    write_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "runtime_contracts/2024c_q2_model_contract.json").read_text(encoding="utf-8"))


@pytest.mark.official_integration
def test_q2_official_manifest_generates_all_five_mother_pools(tmp_path: Path) -> None:
    from official_integration import official_2024c_attachments
    from scripts.generate_2024c_q2_scenarios import generate_q2_scenario_manifest

    attachment_1, _ = official_2024c_attachments()
    material_root = attachment_1.parents[2]
    manifest = generate_q2_scenario_manifest(
        material_root=material_root,
        contract_path=ROOT / "runtime_contracts/2024c_q2_model_contract.json",
        q1_baseline_path=ROOT / "formal_result/cases/2024_C/q1/q1_baseline_manifest.json",
        material_manifest_path=ROOT / "formal_result/cases/2024_C/material_manifest.json",
        output_path=tmp_path / "q2_scenario_manifest.json",
    )
    assert manifest["scenario_count"] == 5 * 512
    assert len(manifest["key_catalog"]["sales"]["keys"]) > 0
    assert len(manifest["key_catalog"]["cost"]["keys"]) > 0
    expected_path = ROOT / "formal_result/cases/2024_C/q2/q2_scenario_manifest.json"
    assert (tmp_path / "q2_scenario_manifest.json").read_bytes() == expected_path.read_bytes()


@pytest.mark.official_integration
def test_q2_rejects_attachment_not_bound_to_material_manifest(tmp_path: Path) -> None:
    from official_integration import official_2024c_attachments
    from scripts.generate_2024c_q2_scenarios import generate_q2_scenario_manifest

    attachment_1, attachment_2 = official_2024c_attachments()
    material_root = tmp_path / "materials"
    attachment_dir = material_root / "2024_C" / "attachments"
    attachment_dir.mkdir(parents=True)
    copied_1 = attachment_dir / "附件1.xlsx"
    copied_2 = attachment_dir / "附件2.xlsx"
    shutil.copy2(attachment_1, copied_1)
    shutil.copy2(attachment_2, copied_2)
    copied_1.write_bytes(copied_1.read_bytes() + b"drift")
    with pytest.raises(ValueError, match="附件.*不匹配"):
        generate_q2_scenario_manifest(
            material_root=material_root,
            contract_path=ROOT / "runtime_contracts/2024c_q2_model_contract.json",
            q1_baseline_path=ROOT / "formal_result/cases/2024_C/q1/q1_baseline_manifest.json",
            material_manifest_path=ROOT / "formal_result/cases/2024_C/material_manifest.json",
            output_path=tmp_path / "drift.json",
        )


def _catalog() -> ScenarioKeyCatalog:
    return ScenarioKeyCatalog(
        sales_keys=((1, "单季", 2024), (1, "单季", 2025), (2, "第一季", 2024)),
        sales_base=(100.0, 100.0, 50.0),
        sales_rules=("wheat_corn_growth", "wheat_corn_growth", "other_change"),
        yield_keys=((1, 2024), (1, 2025)),
        cost_keys=(("平旱地", "单季", 1, 2024),),
        cost_base=(100.0,),
        price_keys=((1, "单季", 2024), (3, "第二季", 2024), (4, "第二季", 2024)),
        price_base=(10.0, 20.0, 30.0),
        price_rules=("stable", "vegetable_growth", "morel_fixed_decline"),
    )


def test_q2_scenario_manifest_has_five_512_pools_and_stable_sha(tmp_path: Path) -> None:
    manifest = generate_manifest_for_catalog(
        _catalog(),
        CONTRACT,
        q1_baseline_manifest_sha256="a" * 64,
        material_manifest_sha256="b" * 64,
        q2_model_contract_sha256="c" * 64,
        scenario_generator_module_sha256="d" * 64,
    )
    validate_manifest(manifest, CONTRACT, _catalog())
    assert manifest["scenario_count"] == 5 * 512
    assert len(manifest["scenarios"]) == 5 * 512
    assert manifest["q2_solver_started"] is False
    assert manifest["production_ready"] is False
    ids = {item["scenario_id"] for item in manifest["scenarios"]}
    assert len(ids) == 5 * 512
    assert {item["phase"] for item in manifest["scenarios"]} == {"opt", "eval"}

    output = tmp_path / "manifest.json"
    digest = write_manifest(manifest, output)
    assert digest == manifest["manifest_sha256"]
    assert output.read_bytes()[-1:] != b"\n"
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["manifest_sha256"] == digest
    schema = json.loads((ROOT / "schemas/2024c_q2_scenario_manifest.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(loaded)) == []


def test_q2_prefixes_are_same_mother_pool_and_seed_streams_are_disjoint() -> None:
    full = list(iter_scenario_payloads(_catalog(), CONTRACT, "opt", 20240724, 512))
    prefix = list(iter_scenario_payloads(_catalog(), CONTRACT, "opt", 20240724, 64))
    assert full[:64] == prefix
    assert full[0]["scenario_id"] == "opt_seed_20240724_scenario_0000"
    assert full[-1]["scenario_index"] == 511
    assert full[0]["sales_growth"] != list(iter_scenario_payloads(_catalog(), CONTRACT, "opt", 20240725, 1))[0]["sales_growth"]


def test_q2_manifest_tampering_is_rejected(tmp_path: Path) -> None:
    manifest = generate_manifest_for_catalog(
        _catalog(),
        CONTRACT,
        q1_baseline_manifest_sha256="a" * 64,
        material_manifest_sha256="b" * 64,
        q2_model_contract_sha256="c" * 64,
        scenario_generator_module_sha256="d" * 64,
    )
    altered = copy.deepcopy(manifest)
    altered["scenarios"][0]["parameter_sha256"] = "0" * 64
    altered.pop("manifest_sha256")
    path = tmp_path / "manifest.json"
    write_manifest(altered, path)
    altered = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="参数重放"):
        validate_manifest(altered, CONTRACT, _catalog())


def test_q2_replay_rejects_contract_seed_and_parameter_count_tampering(tmp_path: Path) -> None:
    manifest = generate_manifest_for_catalog(
        _catalog(),
        CONTRACT,
        q1_baseline_manifest_sha256="a" * 64,
        material_manifest_sha256="b" * 64,
        q2_model_contract_sha256="c" * 64,
        scenario_generator_module_sha256="d" * 64,
    )
    altered = copy.deepcopy(manifest)
    altered["scenarios"][0]["seed"] = 999
    altered["scenarios"][0]["scenario_id"] = "opt_seed_999_scenario_0000"
    altered.pop("manifest_sha256")
    path = tmp_path / "unknown_seed.json"
    write_manifest(altered, path)
    with pytest.raises(ValueError, match="合同之外"):
        validate_manifest(json.loads(path.read_text(encoding="utf-8")), CONTRACT, _catalog())

    altered = copy.deepcopy(manifest)
    altered["scenarios"][0]["parameter_counts"]["sales_growth"] += 1
    altered.pop("manifest_sha256")
    path = tmp_path / "parameter_count.json"
    write_manifest(altered, path)
    with pytest.raises(ValueError, match="参数重放"):
        validate_manifest(json.loads(path.read_text(encoding="utf-8")), CONTRACT, _catalog())


def test_q2_replay_rejects_phase_swap_and_missing_index(tmp_path: Path) -> None:
    manifest = generate_manifest_for_catalog(
        _catalog(),
        CONTRACT,
        q1_baseline_manifest_sha256="a" * 64,
        material_manifest_sha256="b" * 64,
        q2_model_contract_sha256="c" * 64,
        scenario_generator_module_sha256="d" * 64,
    )
    altered = copy.deepcopy(manifest)
    altered["scenarios"][0]["phase"] = "eval"
    altered["scenarios"][0]["scenario_id"] = "eval_seed_20240724_scenario_0000"
    altered.pop("manifest_sha256")
    path = tmp_path / "phase_swap.json"
    write_manifest(altered, path)
    with pytest.raises(ValueError, match="合同之外"):
        validate_manifest(json.loads(path.read_text(encoding="utf-8")), CONTRACT, _catalog())

    altered = copy.deepcopy(manifest)
    altered["scenarios"] = [item for item in altered["scenarios"] if item["scenario_index"] != 511]
    altered["scenario_count"] -= 1
    altered.pop("manifest_sha256")
    path = tmp_path / "missing_index.json"
    write_manifest(altered, path)
    with pytest.raises(ValueError, match="总数"):
        validate_manifest(json.loads(path.read_text(encoding="utf-8")), CONTRACT, _catalog())


def test_q2_pool_size_cannot_exceed_contract() -> None:
    with pytest.raises(ValueError, match="母池长度"):
        list(iter_scenario_payloads(_catalog(), CONTRACT, "eval", 20240727, 513))
