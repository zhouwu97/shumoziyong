from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from paper_compiler_common import (
    ROOT,
    load_json,
    relative_posix,
    sha256_file,
    validate_schema,
    write_json,
)


PILOT_ID = "paper-compiler-2024c-q1-v1.1.1"
IMPLEMENTATION_BASE_COMMIT = "2c132858c2f271374fcfa80904251a4cc40f5da5"
REVIEW_SEEDS = {"reviewer_1": 20260717, "reviewer_2": 20260718, "adjudicator": 20260720}
PILOT_SOURCE_FILES = (
    "scripts/paper/paper_compiler_common.py",
    "scripts/paper/build_fact_projection.py",
    "scripts/paper/validate_fact_projection.py",
    "scripts/paper/render_fact_references.py",
    "scripts/paper/validate_fact_realization.py",
    "scripts/paper/parse_typed_exemptions.py",
    "scripts/paper/build_rhetoric_bundle.py",
    "scripts/paper/retrieve_candidate_cards.py",
    "scripts/paper/check_rhetoric_overlap.py",
    "scripts/paper/run_paper_compiler_fault_injection.py",
    "scripts/paper/build_qualification_boundary.py",
    "scripts/paper/build_review_freeze.py",
    "scripts/paper/validate_exploratory_review.py",
    "scripts/paper/build_paper_compiler_pilot.py",
    "schemas/paper_claim_binding.schema.json",
    "schemas/paper_fact_projection.schema.json",
    "schemas/minimal_argument_graph.schema.json",
    "schemas/paper_rhetoric_card.schema.json",
    "schemas/paper_rhetoric_bundle.schema.json",
    "schemas/paper_fact_realization_plan.schema.json",
    "schemas/paper_fact_realization_report.schema.json",
    "schemas/paper_typed_exemptions.schema.json",
    "schemas/paper_rhetoric_overlap_report.schema.json",
    "schemas/paper_compiler_qualification_boundary.schema.json",
    "schemas/paper_compiler_exploratory_review.schema.json",
    "schemas/paper_compiler_review_freeze.schema.json",
    "schemas/paper_compiler_human_overlap_review.schema.json",
    "schemas/paper_compiler_review_status.schema.json",
    "schemas/paper_compiler_pilot_manifest.schema.json",
)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_binding(role: str, path: Path) -> dict[str, str]:
    return {
        "role": role,
        "path": relative_posix(path, ROOT),
        "sha256": sha256_file(path),
    }


def source_snapshot() -> tuple[str, list[dict[str, str]]]:
    paths = [ROOT / value for value in PILOT_SOURCE_FILES]
    paths.extend(sorted(ROOT.glob("papers/rhetoric_cards/RC-*.json")))
    bindings = [file_binding("pilot_source", path) for path in paths]
    return canonical_digest(bindings), bindings


def reviewer_mapping(seed: int) -> dict[str, str]:
    versions = ["A", "B", "C"]
    random.Random(seed).shuffle(versions)
    return dict(zip(("X", "Y", "Z"), versions))


def review_template(reviewer_id: str, freeze_id: str) -> dict[str, Any]:
    dimensions = (
        "result_location",
        "comparison_clarity",
        "attribution_quality",
        "boundary_awareness",
        "paragraph_coherence",
        "template_repetition",
    )
    return {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_exploratory_review",
        "freeze_id": freeze_id,
        "reviewer_id": reviewer_id,
        "human_reviewer_required": True,
        "status": "pending",
        "independent_review_attestation": False,
        "versions": {
            label: {
                "scores": {dimension: None for dimension in dimensions},
                "modification_minutes": None,
                "fact_drift_detected": None,
                "comments": [],
            }
            for label in ("X", "Y", "Z")
        },
        "overall_preference": None,
        "decision": None,
        "completed_at": None,
        "signature": None,
    }


def pending_review_is_empty(path: Path) -> bool:
    if not path.exists():
        return True
    payload = load_json(path)
    if payload.get("status") != "pending" or payload.get("signature") is not None:
        return False
    return all(
        all(value is None for value in version.get("scores", {}).values())
        and version.get("modification_minutes") is None
        and not version.get("comments")
        for version in payload.get("versions", {}).values()
    )


def build_protocol() -> str:
    return """# A/B/C 探索性盲评冻结协议

评阅人只能使用分配给自己的 `reviewer_packages/<reviewer_id>/` 目录，不得查看 `private/`、其他评阅人的评分或项目实现文件。

评阅顺序固定为 X、Y、Z。每份文本独立计时，分别评价结果定位、比较清晰度、归因质量、边界意识、段落连贯性、模板化程度和达到可提交水平所需修改时间。发现事实漂移必须单独标记，不能用语言评分抵消。

两名评阅人须先独立完成并签署 JSON。完成前不得讨论、互看评分或获知版本映射。材料冻结后发现的问题只记录，不中途替换文本、评分维度或判定规则。明显分歧时启用 adjudicator，最后才解盲。

本轮最终只允许 `continue`、`revise` 或 `stop`；任何结果都不能直接授予 `production_ready`。
"""


def decision_policy() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_exploratory_decision_policy",
        "policy_id": "paper-compiler-v1.1.1-exploratory-policy-v1",
        "allowed_decisions": ["continue", "revise", "stop"],
        "hard_stop": [
            "任一版本被人工确认存在事实漂移",
            "人工原文复核结论为 probable_source_reuse",
        ],
        "continue": [
            "两名评阅人的独立建议均为 continue",
            "B 相对 A 的结构指标均值为正",
            "C 相对 B 的主要指标均值不低于 -0.25",
            "C 的平均修改时间不超过 A 的 110%",
            "人工原文复核仅为 no_concern 或 generic_academic_overlap",
        ],
        "stop": [
            "两名评阅人的独立建议均为 stop",
            "或 B、C 的结构指标均不优于 A 且修改时间均超过 A 的 110%",
        ],
        "revise": "无硬停止项但不满足 continue 或 stop 时；评委明显分歧时先仲裁",
        "material_disagreement": "两名评阅人的 decision 不一致，或一名为 continue 而另一名为 stop",
        "production_ready_allowed": False,
    }


def verify_frozen_file(binding: dict[str, str]) -> None:
    path = ROOT / binding["path"]
    if not path.is_file() or sha256_file(path) != binding["sha256"]:
        raise ValueError(f"冻结文件发生变化：{binding['path']}")


def validate_existing_freeze(freeze_path: Path) -> dict[str, Any]:
    freeze = load_json(freeze_path)
    validate_schema(freeze, "paper_compiler_review_freeze.schema.json")
    for binding in freeze["frozen_inputs"]:
        verify_frozen_file(binding)
    private_key = freeze_path.parent / "private/review_keys.json"
    if not private_key.is_file() or sha256_file(private_key) != freeze["private_key_sha256"]:
        raise ValueError("冻结版本映射缺失或发生变化")
    for package in freeze["reviewer_packages"]:
        path = ROOT / package["package_manifest"]
        if not path.is_file() or sha256_file(path) != package["sha256"]:
            raise ValueError(f"评阅包清单发生变化：{package['package_manifest']}")
        manifest = load_json(path)
        for binding in manifest["files"]:
            verify_frozen_file(binding)
    return freeze


def build_human_overlap_template(
    freeze_id: str,
    overlap_path: Path,
) -> dict[str, Any]:
    overlap = load_json(overlap_path)
    items = [
        {
            "item_id": card["card_id"],
            "scope": "rhetoric_card",
            "evidence": {
                "longest_contiguous_match": card["longest_contiguous_match"],
                "char_ngram_overlap": card["char_ngram_overlap"],
                "highest_match": card["highest_match"],
            },
            "verdict": None,
            "comment": None,
        }
        for card in overlap["cards"]
    ]
    generated = overlap["generated_text"]
    items.append(
        {
            "item_id": "VERSION-C",
            "scope": "generated_version_c",
            "evidence": {
                "longest_contiguous_match": generated["longest_contiguous_match"],
                "char_ngram_overlap": generated["char_ngram_overlap"],
                "highest_match": generated["highest_match"],
            },
            "verdict": None,
            "comment": None,
        }
    )
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_human_overlap_review",
        "freeze_id": freeze_id,
        "human_reviewer_required": True,
        "status": "pending",
        "automatic_evidence": {
            "path": relative_posix(overlap_path, ROOT),
            "sha256": sha256_file(overlap_path),
        },
        "items": items,
        "completed_at": None,
        "signature": None,
    }
    validate_schema(payload, "paper_compiler_human_overlap_review.schema.json")
    return payload


def build_review_freeze(
    baseline_dir: Path,
    current_dir: Path,
    review_dir: Path,
    qualification_boundary_path: Path,
) -> dict[str, Any]:
    freeze_path = review_dir / "review_freeze_manifest.json"
    if freeze_path.exists():
        return validate_existing_freeze(freeze_path)

    protocol_path = review_dir / "REVIEW_PROTOCOL.md"
    policy_path = review_dir / "decision_policy.json"
    write_text(protocol_path, build_protocol())
    write_json(policy_path, decision_policy())

    versions = {
        "A": baseline_dir / "version_a.md",
        "B": current_dir / "version_b.md",
        "C": current_dir / "version_c.md",
    }
    mappings = {reviewer_id: reviewer_mapping(seed) for reviewer_id, seed in REVIEW_SEEDS.items()}
    source_digest, source_bindings = source_snapshot()
    identity = {
        "versions": {key: sha256_file(path) for key, path in versions.items()},
        "mappings": mappings,
        "source_snapshot_sha256": source_digest,
        "qualification_boundary_sha256": sha256_file(qualification_boundary_path),
    }
    freeze_id = f"review-freeze-{canonical_digest(identity)[:16]}"

    key_path = review_dir / "private/review_keys.json"
    write_json(
        key_path,
        {
            "schema_version": "1.0.0",
            "artifact_type": "paper_compiler_private_review_keys",
            "freeze_id": freeze_id,
            "mappings": mappings,
            "disclosure": "全部独立评阅完成并锁定前不得向评阅人提供",
        },
    )

    package_bindings = []
    for reviewer_id, mapping in mappings.items():
        package_dir = review_dir / "reviewer_packages" / reviewer_id
        bindings = []
        for label, version in mapping.items():
            target = package_dir / f"version_{label}.md"
            write_text(target, versions[version].read_text(encoding="utf-8"))
            bindings.append(file_binding(f"blinded_version_{label}", target))
        package_protocol = package_dir / "REVIEW_PROTOCOL.md"
        write_text(package_protocol, protocol_path.read_text(encoding="utf-8"))
        bindings.append(file_binding("review_protocol", package_protocol))
        manifest_path = package_dir / "PACKAGE_MANIFEST.json"
        write_json(
            manifest_path,
            {
                "schema_version": "1.0.0",
                "artifact_type": "paper_compiler_reviewer_package",
                "freeze_id": freeze_id,
                "reviewer_id": reviewer_id,
                "display_order": ["X", "Y", "Z"],
                "mapping_disclosed": False,
                "files": bindings,
            },
        )
        package_bindings.append(
            {
                "reviewer_id": reviewer_id,
                "package_manifest": relative_posix(manifest_path, ROOT),
                "sha256": sha256_file(manifest_path),
            }
        )

    for reviewer_id in REVIEW_SEEDS:
        review_path = review_dir / f"{reviewer_id}.json"
        if not pending_review_is_empty(review_path):
            raise ValueError(f"已有非空人工评阅，不能重新绑定冻结包：{review_path}")
        write_json(review_path, review_template(reviewer_id, freeze_id))

    overlap_path = current_dir / "rhetoric_overlap_report.json"
    overlap_review_path = review_dir / "human_overlap_review.json"
    write_json(overlap_review_path, build_human_overlap_template(freeze_id, overlap_path))

    working_tree_clean = not subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    frozen_inputs = [
        file_binding("version_a", versions["A"]),
        file_binding("version_b", versions["B"]),
        file_binding("version_c", versions["C"]),
        file_binding("review_protocol", protocol_path),
        file_binding(
            "review_schema", ROOT / "schemas/paper_compiler_exploratory_review.schema.json"
        ),
        file_binding("decision_policy", policy_path),
        file_binding("rhetoric_bundle", current_dir / "rhetoric_bundle.json"),
        file_binding("overlap_evidence", overlap_path),
        file_binding("qualification_boundary", qualification_boundary_path),
        *source_bindings,
    ]
    freeze = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_review_freeze",
        "freeze_id": freeze_id,
        "pilot_id": PILOT_ID,
        "frozen_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "review_started_at": None,
        "source_state": {
            "implementation_base_commit_sha": IMPLEMENTATION_BASE_COMMIT,
            "pilot_commit_sha": IMPLEMENTATION_BASE_COMMIT if working_tree_clean else None,
            "working_tree_clean": working_tree_clean,
            "source_snapshot_sha256": source_digest,
        },
        "generation_config": {
            "planner": "human_v1",
            "realization": "manual_structured_plan",
            "renderer": "deterministic_fact_renderer_v1.1.1",
            "language_model": None,
            "prompt_sha256": None,
            "temperature": None,
            "review_seeds": REVIEW_SEEDS,
        },
        "frozen_inputs": frozen_inputs,
        "reviewer_packages": package_bindings,
        "private_key_sha256": sha256_file(key_path),
        "mutation_policy": "fail_closed_no_rebuild_after_freeze",
    }
    validate_schema(freeze, "paper_compiler_review_freeze.schema.json")
    write_json(freeze_path, freeze)
    return freeze


def main() -> int:
    parser = argparse.ArgumentParser(description="冻结论文编译器探索性双人盲评材料")
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--current-dir", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--qualification-boundary", type=Path, required=True)
    args = parser.parse_args()
    freeze = build_review_freeze(
        args.baseline_dir,
        args.current_dir,
        args.review_dir,
        args.qualification_boundary,
    )
    print({"freeze_id": freeze["freeze_id"], "review_started_at": freeze["review_started_at"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
