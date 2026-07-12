"""Sandboxie 环境观察报告与机器签名证明的失败即关闭验证。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

from .canonicalization import canonical_bytes
from .errors import FormalResultVerificationError
from .hashing import file_sha256, semantic_sha256
from .schema import validate_schema


ROOT = Path(__file__).resolve().parents[1]
TRUST_REGISTRY_PATH = ROOT / "policies" / "trusted_environment_registry.json"
ATTESTATION_FILENAME = "sandboxie_environment_attestation.json"
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
COMPONENT_FILES = {
    "start_exe": "Start.exe",
    "service_exe": "SbieSvc.exe",
    "driver_sys": "SbieDrv.sys",
}
SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FormalResultVerificationError(f"{label}不存在") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormalResultVerificationError(f"{label}不是严格 UTF-8 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise FormalResultVerificationError(f"{label}必须是 JSON 对象")
    return value


def _assert_regular_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FormalResultVerificationError(f"{label}不存在")
    if path.is_symlink():
        raise FormalResultVerificationError(f"{label}禁止符号链接")
    if os.stat(path, follow_symlinks=False).st_nlink != 1:
        raise FormalResultVerificationError(f"{label}禁止 hardlink")


def _parse_time(value: str, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:  # pragma: no cover - Schema 已拦截普通错误
        raise FormalResultVerificationError(f"{label}不是合法时间") from exc


def environment_fingerprint(report: Mapping[str, Any]) -> str:
    """对会使环境证明失效的稳定字段生成语义指纹。"""
    installation = report["installation"]
    value = {
        "platform": report["platform"],
        "product": installation["product"],
        "product_version": installation["product_version"],
        "install_root": installation["install_root"],
        "components": [
            {
                "role": item["role"],
                "path": item["path"],
                "file_sha256": item["file_sha256"],
                "file_version": item["file_version"],
                "certificate_thumbprint": item["signature"]["certificate_thumbprint"],
            }
            for item in installation["components"]
        ],
        "service": installation["service"],
        "driver": installation["driver"],
        "settings_sha256": report["sandbox"]["settings_sha256"],
    }
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _verify_rsa_signature(payload: bytes, signature_text: str, key: Mapping[str, Any]) -> None:
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except ValueError as exc:
        raise FormalResultVerificationError("Sandboxie Attestation 签名不是严格 Base64") from exc
    modulus = int(str(key["rsa_modulus_hex"]), 16)
    exponent = int(key["rsa_exponent"])
    width = (modulus.bit_length() + 7) // 8
    if len(signature) != width:
        raise FormalResultVerificationError("Sandboxie Attestation 签名长度与可信公钥不一致")
    decoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(width, "big")
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(payload).digest()
    padding_size = width - len(digest_info) - 3
    expected = b"\x00\x01" + b"\xff" * padding_size + b"\x00" + digest_info
    if padding_size < 8 or not hmac.compare_digest(decoded, expected):
        raise FormalResultVerificationError("Sandboxie Attestation 机器签名验证失败")


def _verify_source_commit(source_commit: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise FormalResultVerificationError("Sandboxie 报告引用的生成器提交不存在")


def _verify_report_contract(report: Mapping[str, Any]) -> None:
    if report["verification_status"] != "passed" or report["sandboxie_environment_verified"] is not True:
        raise FormalResultVerificationError("Sandboxie 环境报告未通过")
    if report["formal_result_executed_in_verified_environment"] is not False:
        raise FormalResultVerificationError("Milestone 2 报告禁止声明 Run 已在验证环境执行")

    generated = _parse_time(str(report["generated_at"]), "generated_at")
    started = _parse_time(str(report["probe_started_at"]), "probe_started_at")
    completed = _parse_time(str(report["probe_completed_at"]), "probe_completed_at")
    valid_until = _parse_time(str(report["valid_until"]), "valid_until")
    if not started <= completed <= generated < valid_until:
        raise FormalResultVerificationError("Sandboxie 报告时间窗口顺序非法")

    installation = report["installation"]
    components = {item["role"]: item for item in installation["components"]}
    if set(components) != set(COMPONENT_FILES) or len(components) != 3:
        raise FormalResultVerificationError("Sandboxie 组件角色必须精确覆盖 Start、Service 和 Driver")
    install_root = str(installation["install_root"]).rstrip("\\")
    for role, filename in COMPONENT_FILES.items():
        component = components[role]
        component_path = str(component["path"])
        if not component_path.casefold().startswith((install_root + "\\").casefold()):
            raise FormalResultVerificationError(f"Sandboxie {role} 不在 install_root 下")
        if PureWindowsPath(component_path).name.casefold() != filename.casefold():
            raise FormalResultVerificationError(f"Sandboxie {role} 文件名绑定错误")
        signature = component["signature"]
        if signature["status"] != "Valid" or signature["chain_status"] not in {
            "Valid",
            "ValidSelfSignedRoot",
        }:
            raise FormalResultVerificationError(f"Sandboxie {role} 组件签名或证书链无效")
        if not _parse_time(signature["not_before"], f"{role}.not_before") <= generated <= _parse_time(
            signature["not_after"], f"{role}.not_after"
        ):
            raise FormalResultVerificationError(f"Sandboxie {role} 证书不覆盖报告生成时间")

    service = installation["service"]
    driver = installation["driver"]
    if service != {
        "name": "SbieSvc",
        "state": "Running",
        "start_mode": service["start_mode"],
        "path": components["service_exe"]["path"],
    } or service["start_mode"] not in {"Auto", "Manual"}:
        raise FormalResultVerificationError("Sandboxie Service 未与 SbieSvc.exe 交叉绑定")
    if driver != {
        "name": "SbieDrv",
        "state": "Running",
        "start_mode": driver["start_mode"],
        "path": components["driver_sys"]["path"],
    } or driver["start_mode"] not in {"Auto", "Manual"}:
        raise FormalResultVerificationError("Sandboxie Driver 未与 SbieDrv.sys 交叉绑定")

    sandbox = report["sandbox"]
    if sandbox["start_exe_sha256"] != components["start_exe"]["file_sha256"]:
        raise FormalResultVerificationError("Sandboxie 启动命令未绑定 Start.exe SHA-256")
    settings = sandbox["settings"]
    settings_sha = hashlib.sha256("\n".join(settings).encode("utf-8")).hexdigest()
    if sandbox["settings_sha256"] != settings_sha:
        raise FormalResultVerificationError("Sandboxie settings_sha256 未按有序设置数组重算")
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
    if not required_settings.issubset(set(settings)):
        raise FormalResultVerificationError("Sandboxie 报告缺少固定隔离设置")
    if sandbox["start_exit_code"] != 0 or not sandbox["sandbox_marker_detected"] or not sandbox[
        "protected_host_state_intact"
    ]:
        raise FormalResultVerificationError("Sandboxie 启动链或宿主状态验证失败")

    collector = report["collector"]
    if collector["environment_fingerprint"] != environment_fingerprint(report):
        raise FormalResultVerificationError("Sandboxie environment_fingerprint 不匹配")
    _verify_source_commit(str(collector["source_commit"]))

    controls = report["negative_controls"]
    control_ids = [item["control_id"] for item in controls]
    if len(set(control_ids)) != 12 or set(control_ids) != NEGATIVE_CONTROL_IDS:
        raise FormalResultVerificationError("Sandboxie 真实负控必须精确覆盖 12 个唯一控制项")
    for control in controls:
        if control["status"] != "passed" or control["exit_code"] != 0:
            raise FormalResultVerificationError("Sandboxie 真实负控存在未通过项")
        if control["probe_sha256"] != collector["probe_script_sha256"]:
            raise FormalResultVerificationError("Sandboxie 负控未绑定当前探针 SHA-256")
        control_started = _parse_time(control["started_at"], f"{control['control_id']}.started_at")
        control_completed = _parse_time(
            control["completed_at"], f"{control['control_id']}.completed_at"
        )
        if not started <= control_started <= control_completed <= completed:
            raise FormalResultVerificationError("Sandboxie 负控时间未落入报告探针窗口")

    dns = report["network_probes"]["dns"]
    tcp = report["network_probes"]["tcp"]
    if len({item["endpoint"] for item in dns}) != len(dns) or len(
        {item["endpoint"] for item in tcp}
    ) != len(tcp):
        raise FormalResultVerificationError("Sandboxie 网络探针端点必须互不重复")
    if sum(item["status"] == "passed" for item in dns) < 2 or sum(
        item["status"] == "passed" for item in tcp
    ) < 2:
        raise FormalResultVerificationError("Sandboxie DNS/TCP 多端点探针通过数不足")
    controls_by_id = {item["control_id"]: item for item in controls}
    for index, network_result in enumerate(tcp, start=1):
        if controls_by_id[f"blocked_tcp_endpoint_{index}"]["target"] != network_result["endpoint"]:
            raise FormalResultVerificationError("Sandboxie TCP 负控未与宿主预检端点一一绑定")

    cleanup = report["cleanup"]
    expected_cleanup = {
        "processes_terminated": cleanup["terminate_exit_code"] == 0
        and cleanup["box_processes_after"] == [],
        "new_controller_processes_terminated": cleanup["new_controller_pids_after"] == [],
        "sandbox_content_deleted": cleanup["delete_exit_code"] == 0
        and cleanup["sandbox_content_exists_after"] is False,
        "box_configuration_removed": True,
        "preexisting_configuration_restored": True,
    }
    for field, expected in expected_cleanup.items():
        if cleanup[field] is not expected:
            raise FormalResultVerificationError(f"Sandboxie 清理状态未由现场结果派生：{field}")


def load_and_validate_sandboxie_fixture_report(path: Path) -> dict[str, Any]:
    """Fixture 只允许测试 Schema，不产生任何环境或 Formal Result 资格。"""
    _assert_regular_file(path, "Sandboxie Fixture 报告")
    report = _load_object(path, "Sandboxie Fixture 报告")
    validate_schema(report, "sandboxie_environment_report.schema.json", "Sandboxie Fixture 报告")
    if report.get("report_kind") != "fixture_report":
        raise FormalResultVerificationError("Fixture 验证入口只接受 fixture_report")
    return {
        "sandboxie_environment_observed": True,
        "sandboxie_environment_verified": False,
        "formal_result_executed_in_verified_environment": False,
        "formal_result_eligible": False,
    }


def load_and_verify_sandboxie_environment_report(
    path: Path,
    attestation_path: Path | None = None,
    registry_path: Path = TRUST_REGISTRY_PATH,
) -> dict[str, Any]:
    """验证公开报告、机器签名与信任注册表；Milestone 2 不授予 Run eligibility。"""
    attestation_path = attestation_path or path.with_name(ATTESTATION_FILENAME)
    _assert_regular_file(path, "Sandboxie 公开报告")
    report = _load_object(path, "Sandboxie 公开报告")
    validate_schema(report, "sandboxie_environment_report.schema.json", "Sandboxie 公开报告")
    if report["report_kind"] != "live_attestation":
        raise FormalResultVerificationError("Fixture 报告永远不能产生 Sandboxie 环境资格")
    for candidate, label in (
        (attestation_path, "Sandboxie Attestation"),
        (registry_path, "可信环境注册表"),
    ):
        _assert_regular_file(candidate, label)
    attestation = _load_object(attestation_path, "Sandboxie Attestation")
    registry = _load_object(registry_path, "可信环境注册表")
    validate_schema(
        attestation,
        "sandboxie_environment_attestation.schema.json",
        "Sandboxie Attestation",
    )
    validate_schema(
        registry,
        "trusted_environment_registry.schema.json",
        "可信环境注册表",
    )
    if report["collector"]["redaction_policy_version"] != "1.0.0":
        raise FormalResultVerificationError("仓库公开报告必须应用脱敏政策 v1")
    _verify_report_contract(report)

    backup = report["configuration_backup"]
    backup_path = path.parent / backup["path"]
    _assert_regular_file(backup_path, "Sandboxie 配置备份")
    if backup_path.stat().st_size != backup["size_bytes"] or file_sha256(backup_path) != backup[
        "file_sha256"
    ]:
        raise FormalResultVerificationError("Sandboxie 配置备份大小或 SHA-256 不匹配")

    unsigned_attestation = dict(attestation)
    signature = str(unsigned_attestation.pop("signature"))
    expected_attestation = {
        "report_id": report["report_id"],
        "public_report_sha256": file_sha256(path),
        "public_report_semantic_sha256": semantic_sha256(report),
        "configuration_backup_sha256": backup["file_sha256"],
        "probe_script_sha256": report["collector"]["probe_script_sha256"],
        "collector_source_commit": report["collector"]["source_commit"],
        "machine_key_id": report["collector"]["machine_key_id"],
        "environment_fingerprint": report["collector"]["environment_fingerprint"],
        "generated_at": report["generated_at"],
        "valid_until": report["valid_until"],
    }
    for field, expected in expected_attestation.items():
        if attestation[field] != expected:
            raise FormalResultVerificationError(f"Sandboxie Attestation 未绑定公开报告字段：{field}")

    keys = {item["machine_key_id"]: item for item in registry["keys"]}
    if len(keys) != len(registry["keys"]):
        raise FormalResultVerificationError("可信环境注册表 machine_key_id 重复")
    key = keys.get(attestation["machine_key_id"])
    if key is None or key["status"] != "active":
        raise FormalResultVerificationError("Sandboxie Attestation 未使用 active 可信机器密钥")
    if attestation["signature_algorithm"] != key["signature_algorithm"]:
        raise FormalResultVerificationError("Sandboxie Attestation 签名算法与注册表不一致")
    if attestation["probe_script_sha256"] not in key["allowed_probe_sha256"]:
        raise FormalResultVerificationError("Sandboxie 探针 SHA-256 未被可信注册表批准")
    generated = _parse_time(attestation["generated_at"], "attestation.generated_at")
    if not _parse_time(key["not_before"], "key.not_before") <= generated <= _parse_time(
        key["not_after"], "key.not_after"
    ):
        raise FormalResultVerificationError("可信机器证书有效期不覆盖报告生成时间")
    _verify_rsa_signature(canonical_bytes(unsigned_attestation), signature, key)

    return {
        "report_id": report["report_id"],
        "report_file_sha256": file_sha256(path),
        "report_semantic_sha256": semantic_sha256(report),
        "attestation_path": attestation_path.name,
        "attestation_file_sha256": file_sha256(attestation_path),
        "attestation_semantic_sha256": semantic_sha256(attestation),
        "original_report_sha256": attestation["original_report_sha256"],
        "configuration_backup_path": backup["path"],
        "configuration_backup_sha256": backup["file_sha256"],
        "environment_fingerprint": report["collector"]["environment_fingerprint"],
        "machine_key_id": report["collector"]["machine_key_id"],
        "formal_result_activation_status": "sandboxie_environment_verified",
        "sandboxie_environment_observed": True,
        "sandboxie_environment_verified": True,
        "formal_result_executed_in_verified_environment": False,
        "formal_result_eligible": False,
    }
