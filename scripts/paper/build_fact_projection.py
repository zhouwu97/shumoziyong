from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from paper_compiler_common import (
    ROOT,
    decimal_operation,
    format_binding_value,
    load_json,
    normalize_formula_tokens,
    relative_posix,
    resolve_inside,
    resolve_json_pointer,
    sha256_file,
    validate_schema,
    write_json,
)


def find_claim_map(run_dir: Path) -> Path:
    for name in ("paper_claim_map.json", "paper_claim_map_v2.json"):
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("运行目录中不存在 paper_claim_map.json 或 paper_claim_map_v2.json")


def find_formal_result_manifest(run_dir: Path) -> Path:
    candidates = sorted(run_dir.glob("formal_results/*/formal_result_manifest.json"))
    if len(candidates) != 1:
        raise ValueError(f"应存在且只存在一个 Formal Result Manifest，实际为 {len(candidates)} 个")
    return candidates[0]


def normalize_legacy_bindings(payload: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """把旧 claim_bindings.json 转为统一内部合同，不改写历史文件。"""
    if payload.get("artifact_type") == "paper_claim_bindings":
        return payload
    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise ValueError("Claim Binding 必须符合新合同或包含旧版 claims 列表")
    bindings = []
    for item in claims:
        display_value = str(item["display_value"])
        unit = str(item.get("unit", ""))
        literal = display_value if not unit or display_value.endswith(unit) else f"{display_value} {unit}"
        bindings.append(
            {
                "binding_id": str(item["claim_id"]).upper().replace("_", "-") + "-LEGACY",
                "claim_id": str(item["claim_id"]),
                "ref_type": "metric",
                "source": {
                    "kind": "direct",
                    "path": str(item["source_file"]),
                    "json_pointer": str(item["json_pointer"]),
                },
                "display": {
                    "decimal_places": None,
                    "scale": 1,
                    "prefix": "",
                    "suffix": "",
                    "unit": unit,
                    "literal": literal,
                },
                "usage": {
                    "requirement": "required_at_least_once",
                    "allowed_sections": ["result_analysis", "model_boundary"],
                },
            }
        )
    return {
        "schema_version": "1.0.0",
        "artifact_type": "paper_claim_bindings",
        "run_id": run_dir.name,
        "problem_id": str(payload.get("paper_id", "legacy")),
        "bindings": bindings,
    }


def resolve_bindings(run_dir: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for binding in contract["bindings"]:
        binding_id = binding["binding_id"]
        if binding_id in by_id:
            raise ValueError(f"重复 binding_id：{binding_id}")
        source = binding["source"]
        source_refs: list[str]
        derives_from: list[str] = []
        source_unit = ""
        if source["kind"] == "direct":
            source_path = resolve_inside(run_dir, source["path"])
            document = load_json(source_path)
            value = resolve_json_pointer(document, source["json_pointer"])
            source_refs = [f"{source['path']}#{source['json_pointer']}"]
            if source.get("unit_pointer"):
                source_unit = str(resolve_json_pointer(document, source["unit_pointer"]))
        else:
            input_ids = source["input_binding_ids"]
            if any(item not in by_id for item in input_ids):
                raise ValueError(f"派生绑定 {binding_id} 引用了尚未解析的输入")
            left, right = (by_id[item]["resolved_value"] for item in input_ids)
            value = decimal_operation(source["operation"], left, right)
            derives_from = list(input_ids)
            source_refs = sorted(
                {ref for item in input_ids for ref in by_id[item]["source_refs"]}
            )
        rendered_text = format_binding_value(value, binding["display"])
        item = {
            "binding_id": binding_id,
            "claim_id": binding["claim_id"],
            "ref_type": binding["ref_type"],
            "source_refs": source_refs,
            "resolved_value": float(value) if hasattr(value, "as_tuple") else value,
            "source_unit": source_unit,
            "rendered_text": rendered_text,
            "display": binding["display"],
            "usage": binding["usage"],
        }
        if derives_from:
            item["derives_from"] = derives_from
        if binding["ref_type"] == "formula" and isinstance(value, str):
            item["display"] = {
                **binding["display"],
                "normalized_tokens": normalize_formula_tokens(value),
            }
        resolved.append(item)
        by_id[binding_id] = item
    return resolved


def build_projection(
    run_dir: Path,
    bindings_path: Path,
    subproblem_id: str,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    claim_map_path = find_claim_map(run_dir)
    result_report_path = run_dir / "result_report.json"
    formal_manifest_path = find_formal_result_manifest(run_dir)
    if not result_report_path.is_file():
        raise FileNotFoundError(result_report_path)

    claim_map = load_json(claim_map_path)
    validate_schema(claim_map, "paper_claim_map_v2.schema.json")
    raw_contract = load_json(bindings_path)
    contract = normalize_legacy_bindings(raw_contract, run_dir)
    validate_schema(contract, "paper_claim_binding.schema.json")
    if contract["run_id"] != claim_map["run_id"]:
        raise ValueError("Claim Binding 与 Claim Map 的 run_id 不一致")
    if contract["problem_id"] != claim_map["problem_id"]:
        raise ValueError("Claim Binding 与 Claim Map 的 problem_id 不一致")

    fact_bindings = resolve_bindings(run_dir, contract)
    binding_ids_by_claim: dict[str, list[str]] = {}
    for binding in fact_bindings:
        binding_ids_by_claim.setdefault(binding["claim_id"], []).append(binding["binding_id"])
    claims = []
    for claim in claim_map["claims"]:
        claim_id = claim["claim_id"]
        if claim_id not in binding_ids_by_claim:
            continue
        claims.append(
            {
                "claim_id": claim_id,
                "semantic_claim": claim["claim"],
                "scope": claim["scope"],
                "status": claim["status"],
                "evidence_refs": claim["evidence_refs"],
                "figure_refs": claim.get("figure_refs", []),
                "claim_binding_ids": binding_ids_by_claim[claim_id],
            }
        )
    unknown_claims = sorted(set(binding_ids_by_claim) - {item["claim_id"] for item in claims})
    if unknown_claims:
        raise ValueError(f"Claim Binding 引用了 Claim Map 中不存在的 Claim：{unknown_claims}")

    upstream_paths = [
        ("claim_map", "run_dir", claim_map_path, run_dir),
        ("claim_bindings", "repository", bindings_path.resolve(), ROOT),
        ("result_report", "run_dir", result_report_path, run_dir),
        ("formal_result_manifest", "run_dir", formal_manifest_path, run_dir),
    ]
    projection = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_fact_projection",
        "run_id": claim_map["run_id"],
        "problem_id": claim_map["problem_id"],
        "subproblem_id": subproblem_id,
        "upstream_bindings": [
            {
                "role": role,
                "base": base_name,
                "path": relative_posix(path, base_path),
                "sha256": sha256_file(path),
            }
            for role, base_name, path, base_path in upstream_paths
        ],
        "claims": claims,
        "fact_bindings": fact_bindings,
        "typed_exemptions": [],
    }
    validate_schema(projection, "paper_fact_projection.schema.json")
    return projection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从上游事实资产构建只读论文事实投影")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--subproblem", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    projection = build_projection(args.run_dir, args.bindings, args.subproblem)
    write_json(args.output, projection)
    print(f"已生成 {len(projection['fact_bindings'])} 个事实绑定：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
