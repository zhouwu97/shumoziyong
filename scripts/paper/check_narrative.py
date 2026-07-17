from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

try:
    from .external_precheck import snapshot_body
except ImportError:  # 允许直接执行脚本。
    from external_precheck import snapshot_body


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT_PATH = ROOT / "runtime_contracts" / "paper_narrative_contract_v1.json"
ELEMENT_NAMES = (
    "thesis",
    "core_contributions",
    "model_choice_reason",
    "result_insights",
    "action_recommendations",
    "limitations",
)


class NarrativeCheckError(ValueError):
    """论文叙事合同无法可靠检查。"""


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} 不存在：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise NarrativeCheckError(f"{label} 必须是 JSON 对象：{path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_payload(payload: dict[str, Any], schema_name: str, label: str) -> None:
    schema = load_json_object(ROOT / "schemas" / schema_name, f"Schema {schema_name}")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise NarrativeCheckError(f"{label} 不符合 Schema：{details}")


def _locations(paper_root: Path, text: str) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for path in sorted(
        item
        for item in paper_root.rglob("*")
        if item.is_file() and item.suffix.lower() in {".typ", ".tex"}
    ):
        source = path.read_text(encoding="utf-8", errors="replace")
        offset = 0
        while True:
            offset = source.find(text, offset)
            if offset < 0:
                break
            locations.append(
                {
                    "path": path.relative_to(paper_root).as_posix(),
                    "line": source.count("\n", 0, offset) + 1,
                }
            )
            offset += len(text)
    return locations


def _single_sentence(text: str) -> bool:
    endings = re.findall(r"(?:[。！？!?]|\.(?=\s|$))", text.strip())
    return len(endings) == 1 and bool(re.search(r"[。！？.!?]$", text.strip()))


def _forbidden_hits(
    paper_root: Path,
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    terms = tuple(str(item) for item in contract["forbidden_main_paper_terms"])
    hash_pattern = re.compile(str(contract["hash_pattern"]))
    hits: list[dict[str, Any]] = []
    for path in sorted(
        item
        for item in paper_root.rglob("*")
        if item.is_file() and item.suffix.lower() in {".typ", ".tex"}
    ):
        relative = path.relative_to(paper_root).as_posix()
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            for term in terms:
                if term in line:
                    hits.append(
                        {
                            "kind": "forbidden_term",
                            "value": term,
                            "path": relative,
                            "line": line_number,
                        }
                    )
            for match in hash_pattern.finditer(line):
                hits.append(
                    {
                        "kind": "hash",
                        "value": match.group(0),
                        "path": relative,
                        "line": line_number,
                    }
                )
    return hits


def build_narrative_report(
    *,
    paper_root: Path,
    narrative_input: dict[str, Any],
    claim_map: dict[str, Any],
    claim_map_path: Path,
    binding: Mapping[str, str],
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict[str, Any]:
    paper_root = paper_root.resolve()
    claim_map_path = claim_map_path.resolve()
    if load_json_object(claim_map_path, "paper_claim_map 文件") != claim_map:
        raise NarrativeCheckError("paper_claim_map 对象与 claim_map_path 文件内容不一致")
    contract = load_json_object(contract_path, "论文叙事合同")
    validate_payload(contract, "paper_narrative_contract.schema.json", "论文叙事合同")
    validate_payload(narrative_input, "paper_narrative_input.schema.json", "论文叙事输入")
    validate_payload(claim_map, "gate_business_artifact.schema.json", "paper_claim_map")
    if claim_map.get("artifact_type") != "paper_claim_map":
        raise NarrativeCheckError("claim_map 不是 paper_claim_map")
    for field, expected in binding.items():
        if claim_map.get(field) != expected:
            raise NarrativeCheckError(f"paper_claim_map.{field} 与当前 Run 绑定不一致")

    known_claims = {
        str(item["claim_id"])
        for item in claim_map.get("claims", [])
        if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
    }
    contract_issues: list[str] = []
    presence_issues: list[str] = []
    binding_issues: list[str] = []
    elements: dict[str, list[dict[str, Any]]] = {}
    for name in ELEMENT_NAMES:
        raw_items = narrative_input[name]
        requirement = contract["requirements"][name]
        if not requirement["min_items"] <= len(raw_items) <= requirement["max_items"]:
            contract_issues.append(
                f"{name} 数量必须在 {requirement['min_items']}..{requirement['max_items']} 之间"
            )
        checked: list[dict[str, Any]] = []
        for index, item in enumerate(raw_items, 1):
            text = str(item["text"])
            locations = _locations(paper_root, text)
            references = [str(value) for value in item["evidence_refs"]]
            evidence_bound = bool(references) and set(references).issubset(known_claims)
            if len(text.strip()) < 10:
                contract_issues.append(f"{name}[{index}] 文本少于 10 个字符")
            if name == "thesis" and not _single_sentence(text):
                contract_issues.append("thesis 必须是一句话且以句号、问号或感叹号结束")
            if not locations:
                presence_issues.append(f"{name}[{index}] 未在正文中精确定位")
            if not evidence_bound:
                binding_issues.append(f"{name}[{index}] 未绑定有效 Claim ID")
            checked.append(
                {
                    "text": text,
                    "evidence_refs": references,
                    "locations": locations,
                    "present": bool(locations),
                    "evidence_bound": evidence_bound,
                }
            )
        elements[name] = checked

    forbidden_hits = _forbidden_hits(paper_root, contract)
    checks = {
        "contract_complete": {
            "status": "failed" if contract_issues else "passed",
            "issues": contract_issues,
        },
        "text_presence": {
            "status": "failed" if presence_issues else "passed",
            "issues": presence_issues,
        },
        "claim_binding": {
            "status": "failed" if binding_issues else "passed",
            "issues": binding_issues,
        },
        "forbidden_terms": {
            "status": "failed" if forbidden_hits else "passed",
            "issues": [
                f"{item['path']}:{item['line']} 出现 {item['kind']}={item['value']}"
                for item in forbidden_hits
            ],
        },
    }
    passed = all(item["status"] == "passed" for item in checks.values())
    report = {
        "schema_version": "paper_narrative_report_v1",
        **binding,
        "contract_sha256": sha256_file(contract_path),
        "paper_body_sha256": snapshot_body(paper_root)["sha256"],
        "claim_map_sha256": sha256_file(claim_map_path),
        "elements": elements,
        "forbidden_scan": {
            "status": "failed" if forbidden_hits else "passed",
            "hits": forbidden_hits,
        },
        "checks": checks,
        "status": "passed" if passed else "failed",
        "submission_allowed": passed,
        "technical_report_allowed": True,
    }
    validate_payload(report, "paper_narrative_report.schema.json", "论文叙事报告")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查论文叙事合同与正文证据定位")
    parser.add_argument("--paper-root", type=Path, required=True)
    parser.add_argument("--narrative-input", type=Path, required=True)
    parser.add_argument("--claim-map", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--problem-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--runtime-pack-sha256", required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = build_narrative_report(
        paper_root=args.paper_root,
        narrative_input=load_json_object(args.narrative_input, "论文叙事输入"),
        claim_map=load_json_object(args.claim_map, "paper_claim_map"),
        claim_map_path=args.claim_map,
        binding={
            "run_id": args.run_id,
            "problem_id": args.problem_id,
            "profile": args.profile,
            "runtime_version": args.runtime_version,
            "runtime_pack_sha256": args.runtime_pack_sha256,
        },
        contract_path=args.contract,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"]}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
