from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from check_template_matrix import plan_matrix, run_matrix  # noqa: E402
from template_registry import DEFAULT_MANIFEST_PATH, DEFAULT_VENDOR_ROOT  # noqa: E402


def _manifest() -> dict[str, object]:
    value = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_ordinary_matrix_is_all_typst_plus_five_representative_xelatex() -> None:
    planned = plan_matrix(_manifest(), mode="ordinary")
    assert len(planned) == 22
    assert sum(item["engine"] == "typst" for item in planned) == 17
    assert sum(item["engine"] == "xelatex" for item in planned) == 5
    assert {item["logical_key"] for item in planned if item["engine"] == "xelatex"} == {
        "en/mcm",
        "zh/cumcm",
        "zh/huaweibei",
        "zh/shuweibei",
        "zh/stats",
    }


def test_full_matrix_contains_all_34_templates() -> None:
    planned = plan_matrix(_manifest(), mode="full")
    assert len(planned) == 34
    assert len({item["template_id"] for item in planned}) == 34


def test_local_typst_matrix_compiles_all_templates() -> None:
    if not DEFAULT_VENDOR_ROOT.is_dir():
        import pytest

        pytest.skip("本地只读 Source Asset 未同步")
    report = run_matrix(mode="ordinary", only_engine="typst")
    assert report["planned"] == 17
    assert report["passed"] == 17
    assert report["failed"] == 0
    assert report["status"] == "passed"
