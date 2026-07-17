from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from paper_compiler_common import ROOT, load_json, resolve_inside, sha256_file, validate_schema, write_json


def validate_projection(projection_path: Path, run_dir: Path) -> dict[str, Any]:
    projection = load_json(projection_path)
    issues: list[dict[str, str]] = []
    try:
        validate_schema(projection, "paper_fact_projection.schema.json")
    except ValueError as exc:
        issues.append({"code": "PFP_SCHEMA_INVALID", "message": str(exc)})
        return {"status": "failed", "issues": issues}

    for source in projection["upstream_bindings"]:
        try:
            base = run_dir if source["base"] == "run_dir" else ROOT
            path = resolve_inside(base, source["path"])
        except (FileNotFoundError, ValueError) as exc:
            issues.append({"code": "PFP_UPSTREAM_MISSING", "message": str(exc)})
            continue
        if sha256_file(path) != source["sha256"]:
            issues.append(
                {
                    "code": "PFP_UPSTREAM_HASH_DRIFT",
                    "message": f"上游文件哈希变化：{source['path']}",
                }
            )

    binding_ids = [item["binding_id"] for item in projection["fact_bindings"]]
    if len(binding_ids) != len(set(binding_ids)):
        issues.append({"code": "PFP_DUPLICATE_BINDING", "message": "存在重复 binding_id"})
    known = set(binding_ids)
    for claim in projection["claims"]:
        missing = sorted(set(claim["claim_binding_ids"]) - known)
        if missing:
            issues.append(
                {
                    "code": "PFP_CLAIM_BINDING_MISSING",
                    "message": f"{claim['claim_id']} 引用不存在的绑定：{missing}",
                }
            )
    return {
        "schema_version": "1.0.0",
        "artifact_type": "paper_fact_projection_validation",
        "status": "failed" if issues else "passed",
        "projection": str(projection_path.resolve()),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证论文事实投影及其上游哈希")
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate_projection(args.projection, args.run_dir)
    write_json(args.output, report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
