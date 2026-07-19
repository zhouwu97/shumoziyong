from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from contest_v2.learning_registry import validate_registry, validate_registry_file


REGISTRY = Path(__file__).parents[2] / "papers" / "EXCELLENT_PAPER_REVIEW_STANDARD_REGISTRY.json"


def test_repository_registry_has_complete_governance() -> None:
    validate_registry_file(REGISTRY)


def test_rejects_global_rule_without_production_run() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    broken = deepcopy(registry)
    broken["review_rules"][0]["status"] = "global_active"
    broken["review_rules"][0]["validation_evidence"] = []

    with pytest.raises(ValueError, match="缺少有效生产 Run 证据"):
        validate_registry(broken)


def test_accepts_global_rule_with_supported_production_run() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    promoted = deepcopy(registry)
    rule = promoted["review_rules"][0]
    rule["status"] = "global_active"
    rule["validation_evidence"] = [
        {
            "type": "production_replay",
            "run_id": "example-clean-run",
            "result": "supported",
        }
    ]

    validate_registry(promoted)
