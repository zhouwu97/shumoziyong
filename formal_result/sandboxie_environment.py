"""Sandboxie 环境报告的失败即关闭验证与派生。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import FormalResultVerificationError
from .hashing import file_sha256, semantic_sha256
from .schema import validate_schema


NEGATIVE_CONTROL_IDS = frozenset(
    {
        "blocked_file_read",
        "blocked_file_write",
        "blocked_file_delete",
        "blocked_directory_enumeration",
        "blocked_registry_read",
        "blocked_registry_write",
        "blocked_registry_delete",
        "dropped_admin_token",
        "child_blocked_file_read",
        "blocked_tcp_endpoint_1",
        "blocked_tcp_endpoint_2",
        "blocked_tcp_endpoint_3",
    }
)
COMPONENT_ROLES = frozenset({"start_exe", "service_exe", "driver_sys"})


def load_and_verify_sandboxie_environment_report(path: Path) -> dict[str, Any]:
    """验证真实环境报告及其外置配置备份，返回可供上层绑定的摘要。"""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FormalResultVerificationError("Sandboxie 环境报告不存在") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormalResultVerificationError(f"Sandboxie 环境报告不是严格 UTF-8 JSON：{exc}") from exc
    if not isinstance(report, dict):
        raise FormalResultVerificationError("Sandboxie 环境报告必须是 JSON 对象")
    validate_schema(report, "sandboxie_environment_report.schema.json", "Sandboxie 环境报告")

    if report["verification_status"] != "passed" or report["sandboxie_environment_verified"] is not True:
        raise FormalResultVerificationError("Sandboxie 环境报告未通过，禁止激活 Formal Result")

    roles = [item["role"] for item in report["installation"]["components"]]
    if len(set(roles)) != 3 or set(roles) != COMPONENT_ROLES:
        raise FormalResultVerificationError("Sandboxie 组件角色必须精确覆盖 Start、Service 和 Driver")
    for component in report["installation"]["components"]:
        if component["signature_status"] != "Valid" or not component["signer_subject"]:
            raise FormalResultVerificationError("Sandboxie 组件签名必须有效且具有签发主体")
    for role in ("service", "driver"):
        component = report["installation"][role]
        if component["state"] != "Running" or component["start_mode"] not in {"Auto", "Manual"}:
            raise FormalResultVerificationError(f"Sandboxie {role} 未以预期状态运行")
    sandbox = report["sandbox"]
    if (
        sandbox["start_exit_code"] != 0
        or sandbox["sandbox_marker_detected"] is not True
        or sandbox["protected_host_state_intact"] is not True
    ):
        raise FormalResultVerificationError("Sandboxie 启动链未证明进程处于沙箱内")
    settings = set(sandbox["settings"])
    required_settings = {
        "Enabled=y",
        "AutoDelete=n",
        "DropAdminRights=y",
        "BlockNetworkFiles=y",
        "NotifyInternetAccessDenied=n",
        r"ClosedFilePath=\Device\Afd*",
        r"ClosedFilePath=\Device\Tcp*",
        r"ClosedFilePath=\Device\RawIp",
    }
    if not required_settings.issubset(settings):
        raise FormalResultVerificationError("Sandboxie 报告缺少固定隔离设置")
    if not any(item.startswith("ClosedFilePath=") and ":\\" in item for item in settings):
        raise FormalResultVerificationError("Sandboxie 报告缺少宿主文件拒绝路径")
    if not any(item.startswith("ClosedKeyPath=HKEY_CURRENT_USER\\") for item in settings):
        raise FormalResultVerificationError("Sandboxie 报告缺少宿主注册表拒绝路径")

    control_ids = [item["control_id"] for item in report["negative_controls"]]
    if len(set(control_ids)) != 12 or set(control_ids) != NEGATIVE_CONTROL_IDS:
        raise FormalResultVerificationError("Sandboxie 真实负控必须精确覆盖 12 个唯一控制项")
    if any(item["status"] != "passed" or item["exit_code"] != 0 for item in report["negative_controls"]):
        raise FormalResultVerificationError("Sandboxie 真实负控存在未通过项")

    dns = report["network_probes"]["dns"]
    tcp = report["network_probes"]["tcp"]
    if len({item["endpoint"] for item in dns}) != len(dns):
        raise FormalResultVerificationError("DNS 网络探针端点必须互不重复")
    if len({item["endpoint"] for item in tcp}) != len(tcp):
        raise FormalResultVerificationError("TCP 网络探针端点必须互不重复")
    if sum(item["status"] == "passed" for item in dns) < 2:
        raise FormalResultVerificationError("DNS 多端点探针通过数不足 2")
    if sum(item["status"] == "passed" for item in tcp) < 2:
        raise FormalResultVerificationError("TCP 多端点探针通过数不足 2")
    if not all(report["cleanup"].values()):
        raise FormalResultVerificationError("Sandboxie 验证后的清理或配置恢复未完成")

    backup = report["configuration_backup"]
    backup_path = path.parent / backup["path"]
    if not backup_path.is_file():
        raise FormalResultVerificationError("Sandboxie 配置备份不存在")
    if path.is_symlink() or backup_path.is_symlink():
        raise FormalResultVerificationError("Sandboxie 报告与配置备份禁止符号链接")
    if os.stat(path, follow_symlinks=False).st_nlink != 1 or os.stat(
        backup_path, follow_symlinks=False
    ).st_nlink != 1:
        raise FormalResultVerificationError("Sandboxie 报告与配置备份禁止 hardlink")
    content = backup_path.read_bytes()
    if len(content) != backup["size_bytes"] or file_sha256(backup_path) != backup["file_sha256"]:
        raise FormalResultVerificationError("Sandboxie 配置备份大小或 SHA-256 不匹配")

    return {
        "report_id": report["report_id"],
        "report_file_sha256": file_sha256(path),
        "report_semantic_sha256": semantic_sha256(report),
        "configuration_backup_path": backup["path"],
        "configuration_backup_sha256": backup["file_sha256"],
        "formal_result_activation_status": "sandboxie_environment_verified",
        "sandboxie_environment_verified": True,
        "formal_result_eligible": True,
    }
