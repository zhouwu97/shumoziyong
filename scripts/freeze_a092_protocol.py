"""生成 A092 确认性实验的确定性冻结记录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validator_digest() -> tuple[str, dict[str, str]]:
    """把通用薄壳全部文件绑定为一个稳定摘要。"""

    files = sorted((ROOT / "validators" / "common").glob("*.py"))
    manifest = {path.relative_to(ROOT).as_posix(): _sha256(path) for path in files}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest(), manifest


def build_freeze_record(protocol_commit: str) -> dict[str, Any]:
    validator_sha256, validator_files = _validator_digest()
    paths = {
        "patch_sha256": ROOT / "prompt_patches" / "patch_A092_engineering_optimization.md",
        "scoring_rubric_sha256": ROOT / "protocols" / "a092" / "scoring_rubric.json",
        "baseline_config_sha256": ROOT / "protocols" / "a092" / "baseline_config.json",
        "treatment_config_sha256": ROOT / "protocols" / "a092" / "treatment_config.json",
        "runtime_pack_sha256": ROOT / "protocols" / "a092" / "runtime_pack.json",
        "case_role_manifest_sha256": ROOT / "protocols" / "a092" / "case_role_manifest.json",
    }
    return {
        "freeze_record_version": "1.0.0",
        "protocol_id": "A092-CONFIRMATORY-V1",
        "protocol_commit": protocol_commit,
        "protocol_sha256": _sha256(ROOT / "protocols" / "a092_experiment_protocol.json"),
        **{key: _sha256(path) for key, path in paths.items()},
        "validator_sha256": validator_sha256,
        "validator_files": validator_files,
        "pilot_evidence_allowed": False,
        "protocol_deviation": False,
    }


def _current_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 A092 协议冻结记录")
    parser.add_argument("--protocol-commit", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "protocols" / "a092" / "protocol_freeze.json",
    )
    args = parser.parse_args()
    record = build_freeze_record(args.protocol_commit or _current_commit())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"protocol_commit": record["protocol_commit"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

