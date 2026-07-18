from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from freeze_hash import canonical_file_sha256  # noqa: E402


def test_text_freeze_hash_is_stable_across_line_endings(tmp_path: Path) -> None:
    lf = tmp_path / "lf.md"
    crlf = tmp_path / "crlf.md"
    lf.write_bytes(b"first\nsecond\n")
    crlf.write_bytes(b"first\r\nsecond\r\n")

    assert canonical_file_sha256(lf) == canonical_file_sha256(crlf)


def test_text_freeze_hash_ignores_utf8_bom(tmp_path: Path) -> None:
    plain = tmp_path / "plain.py"
    bom = tmp_path / "bom.py"
    plain.write_bytes("print('ok')\n".encode("utf-8"))
    bom.write_bytes(b"\xef\xbb\xbf" + "print('ok')\r\n".encode("utf-8"))

    assert canonical_file_sha256(plain) == canonical_file_sha256(bom)
