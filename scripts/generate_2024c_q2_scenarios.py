"""生成 2024-C Q2-A 五组 512 情景母池及 Scenario Manifest。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domains.problem_2024_c.data_loader import load_problem_data, resolve_material_root
from domains.problem_2024_c.scenarios import (
    build_key_catalog,
    generate_manifest_for_catalog,
    sha256_path,
    validate_manifest,
    write_manifest,
)
from validators.problem_2024c_q1.validate import _load_bound_material_manifest


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def generate_q2_scenario_manifest(
    material_root: Path,
    contract_path: Path,
    q1_baseline_path: Path,
    material_manifest_path: Path,
    output_path: Path,
) -> dict:
    """读取已冻结 Q1 基线并生成 Q2-A Manifest。"""

    contract = _read_json(contract_path)
    baseline = _read_json(q1_baseline_path)
    if baseline.get("q1_baseline_frozen") is not True:
        raise ValueError("Q2-A 必须使用已冻结的 Q1 baseline Manifest")
    if baseline.get("production_ready") is not False:
        raise ValueError("Q1 baseline production_ready 必须保持 false")
    baseline_sha = sha256_path(q1_baseline_path)
    material_sha = sha256_path(material_manifest_path)
    attachment_1 = material_root / "2024_C" / "attachments" / "附件1.xlsx"
    attachment_2 = material_root / "2024_C" / "attachments" / "附件2.xlsx"
    _load_bound_material_manifest(material_manifest_path, attachment_1, attachment_2)
    declared_material = next(
        item["sha256"] for item in baseline["files"] if item["role"] == "material_manifest"
    )
    if declared_material != material_sha:
        raise ValueError("Q1 baseline 与实际 Material Manifest SHA 不一致")

    data = load_problem_data(material_root)
    catalog = build_key_catalog(data)
    manifest = generate_manifest_for_catalog(
        catalog,
        contract,
        q1_baseline_manifest_sha256=baseline_sha,
        material_manifest_sha256=material_sha,
        q2_model_contract_sha256=sha256_path(contract_path),
        scenario_generator_module_sha256=sha256_path(
            ROOT / "domains" / "problem_2024_c" / "scenarios.py"
        ),
    )
    validate_manifest(manifest, contract, catalog)
    write_manifest(manifest, output_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--material-root", type=Path, default=resolve_material_root())
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "runtime_contracts" / "2024c_q2_model_contract.json",
    )
    parser.add_argument(
        "--q1-baseline",
        type=Path,
        default=ROOT / "formal_result" / "cases" / "2024_C" / "q1" / "q1_baseline_manifest.json",
    )
    parser.add_argument(
        "--material-manifest",
        type=Path,
        default=ROOT / "formal_result" / "cases" / "2024_C" / "material_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "formal_result" / "cases" / "2024_C" / "q2" / "q2_scenario_manifest.json",
    )
    args = parser.parse_args()
    manifest = generate_q2_scenario_manifest(
        args.material_root.resolve(),
        args.contract.resolve(),
        args.q1_baseline.resolve(),
        args.material_manifest.resolve(),
        args.output.resolve(),
    )
    print(
        json.dumps(
            {
                "manifest": str(args.output.resolve()),
                "manifest_sha256": manifest["manifest_sha256"],
                "scenario_count": manifest["scenario_count"],
                "status": manifest["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
