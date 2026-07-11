"""从已规范为 LF 的授权 YAML 生成注册表 case_sha256。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atomic_io import atomic_write_bytes
from evaluation_case_registry import REGISTRY_PATH, build_expected_registry, load_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="刷新授权评估用例注册表的派生哈希。")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--check", action="store_true", help="仅检查是否需要更新。")
    args = parser.parse_args()
    registry_path = args.registry.resolve()
    root = Path(__file__).resolve().parents[1]
    registry = load_registry(registry_path)
    expected = build_expected_registry(registry, root=root)
    rendered = (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.check:
        if registry_path.read_bytes() != rendered:
            raise SystemExit(
                "evaluation registry drift; run:\n"
                "python scripts/update_evaluation_case_registry.py"
            )
        print("授权评估用例注册表已同步。")
        return
    atomic_write_bytes(registry_path, rendered)
    print(f"已更新注册表派生哈希：{registry_path}")


if __name__ == "__main__":
    main()
