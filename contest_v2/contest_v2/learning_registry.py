"""优秀论文评审规则注册表的晋级证据校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


PRODUCTION_EVIDENCE_TYPES = {"production_replay", "unseen_full_production"}


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value)


def validate_registry(registry: Mapping[str, Any]) -> None:
    """拒绝没有来源 claim 或真实生产证据的全局规则。"""

    sources = registry.get("sources")
    if not isinstance(sources, list):
        raise ValueError("注册表缺少 sources")
    source_index = {
        str(source.get("paper_id")): source
        for source in sources
        if isinstance(source, dict) and _text(source.get("paper_id"))
    }

    patterns = registry.get("verified_cross_problem_patterns")
    if not isinstance(patterns, list):
        raise ValueError("注册表缺少 verified_cross_problem_patterns")
    for pattern in patterns:
        if not isinstance(pattern, dict) or pattern.get("status") != "verified":
            raise ValueError("跨题模式必须显式标记为 verified")
        source = source_index.get(str(pattern.get("source")))
        if source is None or source.get("claim_verification_status") != "verified":
            raise ValueError("跨题模式来源未核验")
        if not _text_list(pattern.get("source_claim_ids")):
            raise ValueError("跨题模式缺少 source_claim_ids")

    rules = registry.get("review_rules")
    if not isinstance(rules, list):
        raise ValueError("注册表缺少 review_rules")
    for rule in rules:
        if not isinstance(rule, dict) or not _text(rule.get("rule_id")):
            raise ValueError("注册表包含无效规则")
        rule_id = str(rule["rule_id"])
        if not _text_list(rule.get("source_claim_ids")):
            raise ValueError(f"规则缺少 source_claim_ids：{rule_id}")
        if not _text(rule.get("last_reviewed")):
            raise ValueError(f"规则缺少 last_reviewed：{rule_id}")
        evidence = rule.get("validation_evidence")
        if not isinstance(evidence, list):
            raise ValueError(f"规则 validation_evidence 必须是列表：{rule_id}")
        valid_production_evidence = [
            item
            for item in evidence
            if isinstance(item, dict)
            and item.get("type") in PRODUCTION_EVIDENCE_TYPES
            and _text(item.get("run_id"))
            and item.get("result") == "supported"
        ]
        if rule.get("status") == "global_active" and not valid_production_evidence:
            raise ValueError(f"global_active 规则缺少有效生产 Run 证据：{rule_id}")
        if rule.get("status") != "global_active" and not valid_production_evidence:
            blockers = rule.get("activation_blockers")
            if not _text_list(blockers):
                raise ValueError(f"候选规则缺少 activation_blockers：{rule_id}")


def validate_registry_file(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("注册表必须是 JSON 对象")
    validate_registry(value)
