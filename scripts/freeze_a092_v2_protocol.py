"""生成 a092_confirmatory_v2 的确定性组件冻结记录。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "protocols" / "a092_v2" / "protocol_freeze.json"
COMPONENTS = (
    "protocols/a092_v2/a092_confirmatory_v2.json",
    "protocols/a092_v2/external_validator_contract.md",
    "protocols/a092_v2/2023b_validator_formula_freeze.json",
    "protocols/a092_v2/2024c_validator_contract_freeze.json",
    "prompt_patches/patch_A092_engineering_optimization.md",
    "schemas/a092_confirmatory_v2.schema.json",
    "schemas/a092_data_contract_audit.schema.json",
    "schemas/a092_external_validator_attestation.schema.json",
    "validators/common/external_validation.py",
    "validators/pilot_case/candidate_evaluator_v2.py",
    "validators/pilot_case/external_adapter_v2.py",
    "validators/pilot_case/fixture_v2.json",
    "validators/problem_boundary_v2/__init__.py",
    "validators/problem_boundary_v2/validate.py",
    "validators/problem_positive_v2/__init__.py",
    "validators/problem_positive_v2/validate.py",
    "validators/problem_negative/__init__.py",
    "validators/problem_negative/validate.py",
    "scripts/attempt_workspace.py",
    "scripts/process_tree.py",
    "scripts/run_a092_stage3.py",
    "scripts/run_a092_v2_pilot.py",
    "examples/a092_phase2_pilot_v2/pilot_result.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_freeze_record() -> dict[str, object]:
    manifest = {path: _sha256(ROOT / path) for path in COMPONENTS}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "freeze_record_version": "2.0.0",
        "protocol_id": "A092-CONFIRMATORY-V2",
        "state": "frozen_pre_execution",
        "execution_started": False,
        "component_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "components": manifest,
    }


def main() -> int:
    record = build_freeze_record()
    OUTPUT.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"protocol_id": record["protocol_id"], "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
