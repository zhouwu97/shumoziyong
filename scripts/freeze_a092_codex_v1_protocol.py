"""生成 A092 Codex V1 确认性实验的组件冻结记录。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from freeze_hash import canonical_file_sha256


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "protocols" / "a092_codex_v1" / "protocol_freeze.json"
COMPONENTS = (
    "protocols/a092_codex_v1/a092_confirmatory_codex_v1.json",
    "schemas/a092_confirmatory_codex_v1.schema.json",
    "protocols/a092_v4/a092_confirmatory_v4.json",
    "protocols/a092_v2/external_validator_contract.md",
    "protocols/a092_v2/2023b_validator_formula_freeze.json",
    "protocols/a092_v2/2024c_validator_contract_freeze.json",
    "prompt_patches/patch_A092_engineering_optimization.md",
    "prompt_base/prompt_base_v1.0.md",
    "prompt_plugins/plugin_optimization_v1.md",
    "schemas/a092_data_contract_audit.schema.json",
    "schemas/a092_external_validator_attestation.schema.json",
    "validators/common/external_validation.py",
    "validators/problem_boundary_v2/validate.py",
    "validators/problem_positive_v2/validate.py",
    "validators/problem_negative/validate.py",
    "scripts/attempt_workspace.py",
    "scripts/process_tree.py",
    "scripts/run_a092_codex_v1.py",
    "scripts/validate_a092_codex_v1.py",
    "scripts/build_a092_codex_v1_pair.py",
    "scripts/validate_a092_formal_run.py",
    "protocols/a092/formal_result_contract.md",
    "protocols/a092/stage3_execution_prompt.md",
    "protocols/a092/baseline_config.json",
    "protocols/a092/treatment_config.json",
    "examples/a092_phase2_pilot_v2/pilot_result.json",
)


def _sha256(path: Path) -> str:
    return canonical_file_sha256(path)


def build_freeze_record() -> dict[str, object]:
    manifest = {path: _sha256(ROOT / path) for path in COMPONENTS}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "freeze_record_version": "1.0.0",
        "protocol_id": "A092-CONFIRMATORY-CODEX-V1",
        "state": "frozen_pre_execution",
        "execution_started": False,
        "component_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "components": manifest,
    }


def main() -> int:
    record = build_freeze_record()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"protocol_id": record["protocol_id"], "output": str(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
