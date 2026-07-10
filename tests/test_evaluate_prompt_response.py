from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_prompt_response import evaluate_manifest_alignment  # noqa: E402


def test_unloaded_patch_semantic_reason_passes() -> None:
    response = {
        "patch_decisions": {
            "A127": {
                "enabled": False,
                "applicable": False,
                "reason": "运行包 patches 数组为空，A127 被显式排除。",
            }
        }
    }
    manifest = {"patches": []}

    assert evaluate_manifest_alignment(response, manifest) == []


def test_unloaded_patch_does_not_require_fixed_phrase() -> None:
    response = {
        "patch_decisions": {
            "A127": {
                "enabled": False,
                "applicable": False,
                "reason": "本轮运行清单不包含该补丁。",
            }
        }
    }
    manifest = {"patches": []}

    assert evaluate_manifest_alignment(response, manifest) == []


def test_unloaded_patch_wrong_enabled_fails() -> None:
    response = {
        "patch_decisions": {
            "A127": {
                "enabled": True,
                "applicable": False,
                "reason": "该补丁没有进入运行包。",
            }
        }
    }
    manifest = {"patches": []}

    errors = evaluate_manifest_alignment(response, manifest)
    assert any("enabled" in error for error in errors)


def test_patch_reason_empty_fails() -> None:
    response = {
        "patch_decisions": {
            "A127": {
                "enabled": False,
                "applicable": False,
                "reason": "",
            }
        }
    }
    manifest = {"patches": []}

    errors = evaluate_manifest_alignment(response, manifest)
    assert any("reason 不能为空" in error for error in errors)


def test_loaded_patch_enabled_true_passes() -> None:
    response = {
        "patch_decisions": {
            "A127": {
                "enabled": True,
                "applicable": False,
                "reason": "运行包包含 A127，但本题不涉及空间布局。",
            }
        }
    }
    manifest = {"patches": [{"patch_id": "A127"}]}

    assert evaluate_manifest_alignment(response, manifest) == []


def test_missing_loaded_patch_decision_fails() -> None:
    response = {"patch_decisions": {}}
    manifest = {"patches": [{"patch_id": "A127"}]}

    errors = evaluate_manifest_alignment(response, manifest)
    assert any("缺少已加载 Patch 的决策" in error for error in errors)
