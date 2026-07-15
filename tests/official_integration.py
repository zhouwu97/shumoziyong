"""受控官方材料集成测试的公共入口。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS_PATH = ROOT / "tests" / "fixtures" / "official_2024c" / "checksums.json"


def _require_official_tests() -> bool:
    return os.environ.get("SHUMO_REQUIRE_OFFICIAL_TESTS", "").strip() == "1"


def _material_root() -> Path:
    configured = os.environ.get("SHUMO_OFFICIAL_MATERIALS_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else ROOT / "official_materials"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def official_2024c_attachments() -> tuple[Path, Path]:
    """返回经固定 SHA-256 验证的 2024-C 官方附件。

    公开 CI 不持有官方附件，因此仅跳过该测试层；受控 CI 必须设置
    ``SHUMO_REQUIRE_OFFICIAL_TESTS=1``，任何缺失或哈希漂移都会直接失败。
    """

    root = _material_root() / "2024_C" / "attachments"
    attachment_1 = root / "附件1.xlsx"
    attachment_2 = root / "附件2.xlsx"
    missing = [str(path) for path in (attachment_1, attachment_2) if not path.is_file()]
    if missing:
        message = "required official 2024-C materials are missing: " + ", ".join(missing)
        if _require_official_tests():
            pytest.fail(message)
        pytest.skip(message)

    expected = json.loads(CHECKSUMS_PATH.read_text(encoding="utf-8"))["attachments"]
    actual = {
        "附件1.xlsx": _sha256(attachment_1),
        "附件2.xlsx": _sha256(attachment_2),
    }
    mismatches = [
        f"{name}: expected {expected[name]}, got {actual[name]}"
        for name in expected
        if actual.get(name) != expected[name]
    ]
    if mismatches:
        pytest.fail("official 2024-C material SHA-256 mismatch: " + "; ".join(mismatches))
    return attachment_1, attachment_2
