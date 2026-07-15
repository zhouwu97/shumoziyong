"""检查当前状态生成物与历史训练日志的职责边界。"""

from __future__ import annotations

import re
from pathlib import Path

from render_current_status import (
    CAPABILITY_POLICY_PATH,
    EVIDENCE_PATH,
    OUTPUT_PATH,
    PROFILE_PATH,
    RUNTIME_PROFILE_SCHEMA_PATH,
    ROOT,
    render_current_status,
)


TRAINING_LOG_PATH = ROOT / "training_log.md"
CURRENT_SECTION_HEADING = "## 当前状态说明"
REQUIRED_CURRENT_SECTION_TEXT = (
    "docs/status/CURRENT_STATUS.md",
    "runtime_profiles/engineering_optimization.json",
    "不构成当前机器状态或 Profile Qualification",
)
FORBIDDEN_CURRENT_CLAIMS = (
    re.compile(
        r"当前机器可读状态为[^\n]*(?:verified_candidate|candidate\+|stable candidate|L4)", re.I
    ),
    re.compile(r"当前\s*maturity\s*为[^\n]*(?:verified_candidate|L4)", re.I),
    re.compile(r"当前\s*Profile\s*(?:已|为)\s*qualified", re.I),
    re.compile(r"assembled\s*(?:高于|低于|覆盖)\s*foundation", re.I),
    re.compile(r"foundation\s*(?:高于|低于|覆盖)\s*assembled", re.I),
    re.compile(r"因为[^\n]*assembled[^\n]*(?:capability|能力)[^\n]*qualified", re.I),
)


def _current_status_section(training_log: str) -> str | None:
    marker = training_log.find(CURRENT_SECTION_HEADING)
    if marker < 0:
        return None
    section_start = marker + len(CURRENT_SECTION_HEADING)
    next_heading = training_log.find("\n## ", section_start)
    return training_log[marker:] if next_heading < 0 else training_log[marker:next_heading]


def validate_training_log(training_log: str) -> list[str]:
    """仅检查当前状态说明，历史记录中的旧标签继续合法保留。"""
    section = _current_status_section(training_log)
    if section is None:
        return [f"training_log.md 缺少 `{CURRENT_SECTION_HEADING}`"]
    errors = [
        f"当前状态说明缺少职责边界文本：{required}"
        for required in REQUIRED_CURRENT_SECTION_TEXT
        if required not in section
    ]
    for pattern in FORBIDDEN_CURRENT_CLAIMS:
        match = pattern.search(section)
        if match:
            errors.append(f"当前状态说明包含越级或混用声明：{match.group(0)}")
    return errors


def check_state_consistency(
    *,
    evidence_path: Path = EVIDENCE_PATH,
    profile_path: Path = PROFILE_PATH,
    status_path: Path = OUTPUT_PATH,
    training_log_path: Path = TRAINING_LOG_PATH,
    capability_policy_path: Path = CAPABILITY_POLICY_PATH,
    runtime_profile_schema_path: Path = RUNTIME_PROFILE_SCHEMA_PATH,
) -> list[str]:
    """重新渲染状态并做字节比较，同时验证历史日志当前说明。"""
    errors: list[str] = []
    try:
        expected = render_current_status(
            evidence_path=evidence_path,
            profile_path=profile_path,
            capability_policy_path=capability_policy_path,
            runtime_profile_schema_path=runtime_profile_schema_path,
        ).encode("utf-8")
    except ValueError as exc:
        errors.append(str(exc))
        expected = None

    try:
        actual = status_path.read_bytes()
    except FileNotFoundError:
        errors.append(f"缺少生成状态文件：{status_path}")
    except OSError as exc:
        errors.append(f"无法读取生成状态文件：{status_path}: {exc}")
    else:
        if expected is not None and actual != expected:
            errors.append(
                "CURRENT_STATUS.md 与现场重新渲染结果不一致；"
                "请运行 python scripts/render_current_status.py"
            )

    try:
        training_log = training_log_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"缺少训练日志：{training_log_path}")
    except OSError as exc:
        errors.append(f"无法读取训练日志：{training_log_path}: {exc}")
    else:
        errors.extend(validate_training_log(training_log))
    return errors


def main() -> int:
    errors = check_state_consistency()
    if errors:
        print("状态一致性检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("状态一致性检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
