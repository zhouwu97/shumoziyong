from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_repository import RepositoryValidator  # noqa: E402


def test_unverified_card_keeps_empty_claims_without_fabrication() -> None:
    card = json.loads(
        (ROOT / "papers" / "2023_A092_知识卡片.json").read_text(encoding="utf-8")
    )
    assert card["source"]["verification_status"] == "unverified"
    assert card["source"]["claims"] == []
    validator = RepositoryValidator()
    assert validator.validate_schema(card, "knowledge_card.schema.json", "unverified card")


def test_verified_card_requires_claim_level_source_evidence() -> None:
    card = json.loads(
        (ROOT / "papers" / "2023_A092_知识卡片.json").read_text(encoding="utf-8")
    )
    card["source"]["verification_status"] = "verified"
    validator = RepositoryValidator()
    assert not validator.validate_schema(card, "knowledge_card.schema.json", "empty verified card")

    card["source"]["claims"] = [
        {
            "claim_id": "A092-C001",
            "page": 12,
            "source_excerpt": "A source-grounded excerpt of sufficient length.",
            "confidence": "high",
            "transfer_scope": "Transfer only the optimization decomposition strategy.",
            "misuse_risk": "Do not copy problem-specific formulas or numerical values.",
        }
    ]
    validator = RepositoryValidator()
    assert validator.validate_schema(card, "knowledge_card.schema.json", "verified claim card")


def test_unverified_source_cannot_enter_regression_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    patches = json.loads(
        (ROOT / "prompt_patches" / "patch_index.json").read_text(encoding="utf-8")
    )
    patches = copy.deepcopy(patches)
    patches[0]["status"] = "regression_verified"
    validator = RepositoryValidator()
    original_load = validator.load_json

    def load_json(path: str):
        if str(path).replace("\\", "/") == "prompt_patches/patch_index.json":
            return patches
        return original_load(path)

    monkeypatch.setattr(validator, "load_json", load_json)
    validator.validate_patch_index()
    assert any("必须引用已验证 Claim ID" in failure for failure in validator.failures)
