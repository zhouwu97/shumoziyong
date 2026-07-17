from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from paper_compiler_common import (
    ROOT,
    load_json,
    relative_posix,
    rhetoric_bundle_digest,
    sha256_file,
    validate_schema,
    write_json,
)


def build_bundle(card_dir: Path, output_path: Path) -> dict[str, Any]:
    cards = []
    for path in sorted(card_dir.glob("RC-*.json")):
        card = load_json(path)
        validate_schema(card, "paper_rhetoric_card.schema.json")
        if card["state"] not in {"task_adapted", "eligible_for_qualification"}:
            raise ValueError(f"卡片 {card['card_id']} 尚不能进入资格候选包")
        cards.append(
            {
                "card_id": card["card_id"],
                "path": relative_posix(path, ROOT),
                "sha256": sha256_file(path),
            }
        )
    if not cards:
        raise ValueError("候选包至少需要一张表达卡片")
    content_sha256 = rhetoric_bundle_digest(cards)
    bundle = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_rhetoric_bundle",
        "bundle_id": f"paper-rhetoric-bundle-2024c-q1-v1-{content_sha256[:12]}",
        "content_sha256": content_sha256,
        "status": "qualification_candidate",
        "cards": cards,
        "compatible_planner_versions": ["human_v1"],
        "compatible_validator_versions": ["paper-fact-validator-v1.1.1"],
        "qualification_evidence": [],
        "production_allowed": False,
    }
    validate_schema(bundle, "paper_rhetoric_bundle.schema.json")
    write_json(output_path, bundle)
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="构建哈希冻结的表达卡片候选包")
    parser.add_argument("--card-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_bundle(args.card_dir, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
