"""Gate F2 内容完整性与论文实质增量的机器校验。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 对象预期：{path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_identity(path: Path | None) -> tuple[str | None, str | None]:
    if path is None:
        return None, None
    payload = _load_json(path)
    return payload.get("candidate_id"), sha256_file(path)


def load_contract(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"内容合同必须是 YAML 对象：{path}")
    return value


def _specific_roles(contract: Mapping[str, Any]) -> list[dict[str, str]]:
    roles: list[dict[str, str]] = []
    requirements = contract.get("role_requirements", {})
    if not isinstance(requirements, Mapping):
        raise ValueError("role_requirements 必须是对象")
    for question, entries in requirements.items():
        if isinstance(entries, Mapping):
            entries = [dict(entries, role=question)]
        if not isinstance(entries, list):
            raise ValueError(f"{question} 的 role_requirements 必须是数组")
        for entry in entries:
            if not isinstance(entry, Mapping) or not entry.get("role"):
                raise ValueError(f"{question} 存在无效 Required Role")
            roles.append(
                {
                    "question": str(question),
                    "role": str(entry["role"]),
                    "severity": str(entry.get("severity", "major")),
                }
            )
    return roles


def _role_index(registry: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for role in registry.get("roles", []):
        if not isinstance(role, Mapping):
            continue
        key = (str(role.get("question", "")), str(role.get("role", "")))
        if key in result:
            raise ValueError(f"Evidence Role 重复：{key[0]}/{key[1]}")
        result[key] = dict(role)
    return result


def _artifact_path(base_dir: Path | None, artifact: Mapping[str, Any]) -> Path | None:
    raw = str(artifact.get("path", ""))
    if not raw:
        return None
    path = Path(raw)
    if base_dir is not None and not path.is_absolute():
        path = base_dir / path
    return path


def _check_artifacts(
    artifacts: Any,
    *,
    base_dir: Path | None,
    label: str,
    require_formal_id: bool = True,
    allowed_formal_ids: set[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    if not isinstance(artifacts, list) or not artifacts:
        return [f"{label} 缺失"]
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, Mapping):
            issues.append(f"{label}[{index}] 不是对象")
            continue
        path = _artifact_path(base_dir, artifact)
        if path is None or not path.is_file():
            issues.append(f"{label}[{index}] 源文件不存在：{artifact.get('path')}")
            continue
        expected = str(artifact.get("sha256", ""))
        if expected != sha256_file(path):
            issues.append(f"{label}[{index}] SHA-256 不匹配：{artifact.get('path')}")
        if require_formal_id and not str(artifact.get("formal_result_id", "")):
            issues.append(f"{label}[{index}] 缺少 formal_result_id")
        if allowed_formal_ids is not None and str(artifact.get("formal_result_id")) not in allowed_formal_ids:
            issues.append(f"{label}[{index}] formal_result_id 不属于当前 Run")
    return issues


def _check_paper_locations(
    locations: Any, *, base_dir: Path | None, label: str
) -> list[str]:
    if not isinstance(locations, list) or not locations:
        return [f"{label} 缺失"]
    if base_dir is None:
        return []
    issues: list[str] = []
    for location in locations:
        raw = str(location)
        path_text, _, anchor = raw.partition("#")
        path = (base_dir / path_text).resolve()
        if not path.is_file():
            issues.append(f"{label} 文件不存在：{path_text}")
        elif anchor and anchor not in path.read_text(encoding="utf-8", errors="replace"):
            issues.append(f"{label} 锚点不存在：{raw}")
    return issues


def _duplicate_artifact_issues(registry: Mapping[str, Any]) -> dict[str, str]:
    seen: dict[tuple[str, str], list[tuple[dict[str, Any], bool]]] = {}
    for role in registry.get("roles", []):
        if not isinstance(role, Mapping):
            continue
        role_id = str(role.get("role_id", ""))
        for field in ("source_artifacts", "validator_artifacts"):
            for artifact in role.get(field, []):
                if isinstance(artifact, Mapping):
                    key = (str(artifact.get("path")), str(artifact.get("sha256")))
                    seen.setdefault(key, []).append((dict(role), bool(artifact.get("shared"))))
    issues: dict[str, str] = {}
    for entries in seen.values():
        if len(entries) > 1 and not all(shared for _role, shared in entries):
            for role, _shared in entries:
                issues[str(role.get("role_id"))] = "同一证据产物被多个 Role 重复注册，未声明 shared=true"
    return issues


def _validate_registry_schema(registry: Mapping[str, Any]) -> None:
    schema = _load_json(ROOT / "schemas" / "paper_evidence_role_registry.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(registry))
    if errors:
        message = "; ".join(error.message for error in errors[:8])
        raise ValueError(f"Evidence Role Registry Schema 校验失败：{message}")


def _missing(question: str, role: str, reason: str) -> dict[str, str]:
    return {"question": question, "role": role, "reason": reason}


def build_substantive_completeness_report(
    contract_path: Path,
    registry_path: Path,
    *,
    base_dir: Path | None = None,
    claim_ids: set[str] | None = None,
    claim_map: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """根据题目合同和真实证据注册表生成 Gate F2 报告。"""
    contract = load_contract(contract_path)
    registry = _load_json(registry_path)
    _validate_registry_schema(registry)
    if registry.get("contract_id") != contract.get("contract_id"):
        raise ValueError("Registry 与内容合同 contract_id 不一致")
    allowed_formal_ids = {str(value) for value in registry.get("formal_result_ids", [])}
    duplicate_issues = _duplicate_artifact_issues(registry)
    claims_by_id = {
        str(item.get("claim_id")): item
        for item in (claim_map or {}).get("claims", [])
        if isinstance(item, Mapping) and item.get("claim_id")
    }
    expected = _specific_roles(contract)
    indexed = _role_index(registry)
    critical: list[dict[str, str]] = []
    major: list[dict[str, str]] = []
    minor: list[dict[str, str]] = []
    coverage: dict[str, dict[str, Any]] = {}
    realized_count = 0
    for item in expected:
        question, role, severity = item["question"], item["role"], item["severity"]
        entry = indexed.get((question, role))
        reason: str | None = None
        if entry is None:
            reason = "Required Role 未注册"
        elif entry.get("applicability") != "required":
            reason = "Required Role 被错误标记为非 required"
        elif entry.get("status") != "realized":
            reason = f"Role 状态为 {entry.get('status')}"
        else:
            issues = _check_artifacts(
                entry.get("source_artifacts"), base_dir=base_dir, label=f"{question}/{role} source", allowed_formal_ids=allowed_formal_ids
            )
            issues += _check_artifacts(
                entry.get("validator_artifacts"),
                base_dir=base_dir,
                label=f"{question}/{role} validator",
                allowed_formal_ids=allowed_formal_ids,
            )
            if str(entry.get("role_id")) in duplicate_issues:
                issues.append(duplicate_issues[str(entry.get("role_id"))])
            if not entry.get("claim_ids"):
                issues.append("缺少 claim_ids")
            elif claim_ids is not None and not set(entry["claim_ids"]).issubset(claim_ids):
                issues.append("存在未定义 Claim")
            if claim_map is not None:
                for claim_id in entry.get("claim_ids", []):
                    claim = claims_by_id.get(str(claim_id))
                    if not claim or not claim.get("result_refs") or not claim.get("evidence_refs"):
                        issues.append(f"Claim {claim_id} 缺少 result_refs/evidence_refs")
            issues += _check_paper_locations(entry.get("paper_locations"), base_dir=base_dir, label=f"{question}/{role} paper_locations")
            if issues:
                reason = "；".join(issues)
            else:
                realized_count += 1
        bucket = critical if severity == "critical" else major if severity == "major" else minor
        if reason:
            bucket.append(_missing(question, role, reason))
    for question in sorted({item["question"] for item in expected}):
        q_expected = [item for item in expected if item["question"] == question]
        q_missing = {
            "critical": [x["role"] for x in critical if x["question"] == question],
            "major": [x["role"] for x in major if x["question"] == question],
            "minor": [x["role"] for x in minor if x["question"] == question],
        }
        coverage[question] = {
            "required_roles": len(q_expected),
            "realized_roles": len(q_expected)
            - sum(len(values) for values in q_missing.values()),
            "critical_missing": q_missing["critical"],
            "major_missing": q_missing["major"],
            "minor_missing": q_missing["minor"],
        }
    required_count = len(expected)
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_substantive_completeness_report",
        "problem_id": str(contract.get("problem_id", registry.get("problem_id", ""))),
        "contract_id": str(contract["contract_id"]),
        "question_coverage": coverage,
        "required_evidence_roles": required_count,
        "realized_evidence_roles": realized_count,
        "required_role_coverage": realized_count / required_count if required_count else 1.0,
        "critical_missing": critical,
        "major_missing": major,
        "minor_missing": minor,
        "status": "passed" if not critical and not major else "content_repair_required",
    }
    schema = _load_json(ROOT / "schemas" / "paper_substantive_completeness_report.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(report))
    if errors:
        raise ValueError("完整性报告 Schema 校验失败：" + "; ".join(error.message for error in errors[:8]))
    return report


def _fingerprint(entry: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
    if entry is None:
        return None
    source = tuple(
        sorted(
            (str(item.get("path")), str(item.get("sha256")), str(item.get("formal_result_id")))
            for item in entry.get("source_artifacts", [])
            if isinstance(item, Mapping)
        )
    )
    validator = tuple(
        sorted(
            (str(item.get("path")), str(item.get("sha256")), str(item.get("formal_result_id")))
            for item in entry.get("validator_artifacts", [])
            if isinstance(item, Mapping)
        )
    )
    return source, validator


def build_content_delta_report(
    after_registry_path: Path,
    *,
    before_registry_path: Path | None = None,
    before_candidate_path: Path | None = None,
    after_candidate_path: Path | None = None,
    revision_type: str = "new_clean_run",
) -> dict[str, Any]:
    """仅依据证据绑定变化派生论文实质增量。"""
    after = _load_json(after_registry_path)
    before = _load_json(before_registry_path) if before_registry_path else {"roles": []}
    before_formal_ids = {str(value) for value in before.get("formal_result_ids", [])}
    after_formal_ids = {str(value) for value in after.get("formal_result_ids", [])}
    before_candidate = _load_json(before_candidate_path) if before_candidate_path else {}
    after_candidate = _load_json(after_candidate_path) if after_candidate_path else {}
    before_candidate_id, before_candidate_sha = _candidate_identity(before_candidate_path)
    after_candidate_id, after_candidate_sha = _candidate_identity(after_candidate_path)
    before_index = {str(x.get("role_id")): x for x in before.get("roles", []) if isinstance(x, Mapping)}
    after_index = {str(x.get("role_id")): x for x in after.get("roles", []) if isinstance(x, Mapping)}
    deltas: list[dict[str, Any]] = []
    for role_id in sorted(set(before_index) | set(after_index)):
        old, new = before_index.get(role_id), after_index.get(role_id)
        old_fp, new_fp = _fingerprint(old), _fingerprint(new)
        if old is None:
            change_type, substantive = "new_analysis", bool(new and new.get("status") == "realized")
        elif new is None:
            change_type, substantive = "removed_analysis", False
        elif old_fp == new_fp:
            change_type, substantive = "unchanged", False
        else:
            change_type, substantive = "updated_analysis", bool(new.get("status") == "realized")
        if substantive and revision_type in {"new_clean_run", "legal_technical_revision"} and before_formal_ids & after_formal_ids:
            substantive = False
        if revision_type == "writing_only":
            substantive = False
        if change_type == "unchanged":
            continue
        deltas.append(
            {
                "delta_id": f"DELTA-{role_id}",
                "change_type": change_type,
                "role_id": role_id,
                "substantive": substantive,
                "formal_result_ids": sorted(
                    {
                        str(item.get("formal_result_id"))
                        for item in (new or {}).get("source_artifacts", []) + (new or {}).get("validator_artifacts", [])
                        if isinstance(item, Mapping) and item.get("formal_result_id")
                    }
                ),
                "source_before": old.get("source_artifacts", [None])[0] if old else None,
                "source_after": new.get("source_artifacts", [None])[0] if new else None,
                "validator_ref": new.get("validator_artifacts", [None])[0] if new else None,
                "claim_ids": list(new.get("claim_ids", [])) if new else [],
                "paper_locations": list(new.get("paper_locations", [])) if new else [],
            }
        )
    substantive = any(item["substantive"] for item in deltas)
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_content_delta_report",
        "before_registry": str(before_registry_path) if before_registry_path else None,
        "after_registry": str(after_registry_path),
        "before_candidate_id": before_candidate.get("candidate_id") or before.get("candidate_id"),
        "after_candidate_id": after_candidate.get("candidate_id") or after.get("candidate_id"),
        "before_candidate_sha256": before_candidate_sha,
        "after_candidate_sha256": after_candidate_sha,
        "before_run_id": before.get("run_id"),
        "after_run_id": str(after.get("run_id", "")),
        "before_formal_result_ids": sorted(before_formal_ids),
        "after_formal_result_ids": sorted(after_formal_ids),
        "revision_type": revision_type,
        "deltas": deltas,
        "substantive_paper_improvement": substantive,
        "reason": "检测到新的或变更的真实证据角色。" if substantive else "本轮只完成流程或证据链修复，未增加模型实验与论文论证。",
    }
    schema = _load_json(ROOT / "schemas" / "paper_content_delta_report.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(report))
    if errors:
        raise ValueError("Content Delta Schema 校验失败：" + "; ".join(error.message for error in errors[:8]))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成 Gate F2 内容完整性与 Content Delta 报告")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path)
    parser.add_argument("--claim-map", type=Path)
    parser.add_argument("--before-registry", type=Path)
    parser.add_argument("--delta-output", type=Path)
    parser.add_argument("--before-candidate", type=Path)
    parser.add_argument("--after-candidate", type=Path)
    parser.add_argument("--revision-type", choices=("new_clean_run", "legal_technical_revision", "writing_only"), default="new_clean_run")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    claim_ids = None
    if args.claim_map:
        claim_map = _load_json(args.claim_map)
        claim_ids = {str(item.get("claim_id")) for item in claim_map.get("claims", []) if isinstance(item, Mapping)}
    report = build_substantive_completeness_report(
        args.contract, args.registry, base_dir=args.base_dir, claim_ids=claim_ids, claim_map=claim_map if args.claim_map else None
    )
    _write_json(args.output, report)
    if args.delta_output:
        delta = build_content_delta_report(
            args.registry,
            before_registry_path=args.before_registry,
            before_candidate_path=args.before_candidate,
            after_candidate_path=args.after_candidate,
            revision_type=args.revision_type,
        )
        _write_json(args.delta_output, delta)
    print(json.dumps({"status": report["status"], "required_role_coverage": report["required_role_coverage"]}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
