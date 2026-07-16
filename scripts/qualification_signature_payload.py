"""生成资格人工签名载荷，并把外部 RSA 签名回填到私有 JSON。"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from formal_result.canonicalization import canonical_bytes


class SignaturePayloadError(ValueError):
    """签名载荷无法安全生成或回填。"""


def _load_artifact(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SignaturePayloadError(f"签名对象无法读取：{exc}") from exc
    if not isinstance(value, dict):
        raise SignaturePayloadError("签名对象必须是 JSON object")
    if value.get("signature_algorithm") != "RSASSA-PKCS1-v1_5-SHA256":
        raise SignaturePayloadError("签名对象必须冻结 RSASSA-PKCS1-v1_5-SHA256")
    return value


def signing_payload(artifact: dict[str, Any]) -> bytes:
    """返回与资格验证器完全相同的无签名规范化字节。"""
    unsigned = dict(artifact)
    unsigned.pop("signature", None)
    return canonical_bytes(unsigned)


def attach_signature(artifact: dict[str, Any], signature: bytes) -> dict[str, Any]:
    """把外部工具生成的二进制 RSA 签名编码为严格 Base64。"""
    if len(signature) < 64:
        raise SignaturePayloadError("RSA 签名长度异常")
    result = dict(artifact)
    result["signature"] = base64.b64encode(signature).decode("ascii")
    return result


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="生成供外部 RSA 工具签名的规范化载荷")
    prepare.add_argument("--artifact", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)

    attach = subparsers.add_parser("attach", help="把二进制 RSA 签名回填为 Base64")
    attach.add_argument("--artifact", required=True, type=Path)
    attach.add_argument("--signature", required=True, type=Path)
    attach.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()
    try:
        artifact = _load_artifact(args.artifact)
        if args.command == "prepare":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(signing_payload(artifact))
        else:
            signature = args.signature.read_bytes()
            _write_json(args.output, attach_signature(artifact, signature))
    except (OSError, SignaturePayloadError) as exc:
        raise SystemExit(f"签名载荷处理失败：{exc}") from exc


if __name__ == "__main__":
    main()
