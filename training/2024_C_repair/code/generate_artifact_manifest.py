"""记录大体积随机情景原件的哈希、种子和可再生成位置，供失败现场提交。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
ARTIFACTS = {
    "q2_stochastic_training_samples": (RESULTS / "q2_stochastic" / "scenario_samples.csv", 2024071402),
    "q3_stochastic_training_samples": (RESULTS / "q3_stochastic" / "scenario_samples.csv", 2024071403),
    "q3_stochastic_independent_comparison_samples": (
        RESULTS / "q3_stochastic" / "independent_comparison_samples.csv",
        2024071499,
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    records = []
    for artifact_id, (path, seed) in ARTIFACTS.items():
        records.append(
            {
                "artifact_id": artifact_id,
                "local_path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "seed": seed,
                "regeneration_entrypoint": "code/scenario_generation.py",
            }
        )
    (RESULTS / "scenario_artifacts_sha256.json").write_text(
        json.dumps({"artifacts": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
