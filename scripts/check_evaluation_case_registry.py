"""CI 使用的授权评估用例注册表只读检查。"""

from __future__ import annotations

from evaluation_case_registry import load_registry, validate_registry


def main() -> None:
    registry = load_registry()
    issues = validate_registry(registry)
    if issues:
        raise SystemExit("授权评估用例注册表无效：\n- " + "\n- ".join(issues))
    print("授权评估用例注册表 Schema、LF、哈希和授权约束检查通过。")


if __name__ == "__main__":
    main()
