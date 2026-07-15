"""受控官方材料测试层的失败闭合回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import official_integration


@pytest.mark.unit_contract
def test_required_official_materials_fail_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHUMO_REQUIRE_OFFICIAL_TESTS", "1")
    monkeypatch.setenv("SHUMO_OFFICIAL_MATERIALS_DIR", str(tmp_path))

    with pytest.raises(pytest.fail.Exception, match="materials are missing"):
        official_integration.official_2024c_attachments()


@pytest.mark.unit_contract
def test_official_material_hash_mismatch_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    attachment_root = tmp_path / "2024_C" / "attachments"
    attachment_root.mkdir(parents=True)
    (attachment_root / "附件1.xlsx").write_bytes(b"tampered-1")
    (attachment_root / "附件2.xlsx").write_bytes(b"tampered-2")
    checksums_path = tmp_path / "checksums.json"
    checksums_path.write_text(
        json.dumps({"attachments": {"附件1.xlsx": "0" * 64, "附件2.xlsx": "1" * 64}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SHUMO_REQUIRE_OFFICIAL_TESTS", "1")
    monkeypatch.setenv("SHUMO_OFFICIAL_MATERIALS_DIR", str(tmp_path))
    monkeypatch.setattr(official_integration, "CHECKSUMS_PATH", checksums_path)

    with pytest.raises(pytest.fail.Exception, match="SHA-256 mismatch"):
        official_integration.official_2024c_attachments()
