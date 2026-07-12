"""在 Windows 上执行 Sandboxie Milestone 2 真实环境验证。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formal_result.sandboxie_environment import (  # noqa: E402
    load_and_verify_sandboxie_environment_report,
)


COMPONENT_FILES = {
    "start_exe": "Start.exe",
    "service_exe": "SbieSvc.exe",
    "driver_sys": "SbieDrv.sys",
}
DNS_ENDPOINTS = ("www.baidu.com", "www.microsoft.com", "www.python.org")
TCP_ENDPOINTS = (("www.baidu.com", 443), ("www.microsoft.com", 443), ("www.python.org", 443))
TRANSIENT_START_EXIT = 0x40010004
HOST_POWERSHELL = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"
PROBE_SCRIPT = r'''
param(
    [Parameter(Mandatory=$true)][string]$Mode,
    [string]$TargetFile,
    [string]$TargetDir,
    [string]$RegistryPath,
    [string]$WritableProbe,
    [string]$HostName,
    [int]$Port
)
$ErrorActionPreference = "Stop"

function Denied([scriptblock]$Action) {
    try { & $Action; exit 41 } catch { exit 0 }
}

switch ($Mode) {
    "marker" {
        $names = [System.Diagnostics.Process]::GetCurrentProcess().Modules | ForEach-Object {$_.ModuleName}
        if ($names -notcontains "SbieDll.dll") { exit 42 }
        try { Set-Content -LiteralPath $WritableProbe -Value "sandbox-only"; exit 0 } catch { exit 47 }
    }
    "file_read" { Denied { Get-Content -LiteralPath $TargetFile -Raw | Out-Null } }
    "file_write" { Denied { Set-Content -LiteralPath $TargetFile -Value "unexpected" } }
    "file_delete" { Denied { Remove-Item -LiteralPath $TargetFile -Force } }
    "directory_enumeration" { Denied { Get-ChildItem -LiteralPath $TargetDir | Out-Null } }
    "registry_read" { Denied { Get-ItemProperty -LiteralPath ("Registry::" + $RegistryPath) | Out-Null } }
    "registry_write" { Denied { Set-ItemProperty -LiteralPath ("Registry::" + $RegistryPath) -Name Value -Value "unexpected" } }
    "registry_delete" { Denied { Remove-Item -LiteralPath ("Registry::" + $RegistryPath) -Recurse -Force } }
    "dropped_admin" {
        $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
        if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 43 } else { exit 0 }
    }
    "child_file_read" {
        $p = Start-Process powershell.exe -ArgumentList @("-NoProfile", "-Command", "Get-Content -LiteralPath '$TargetFile' -Raw -ErrorAction Stop") -PassThru -Wait -WindowStyle Hidden
        if ($p.ExitCode -ne 0) { exit 0 } else { exit 44 }
    }
    "tcp" {
        try {
            $client = [Net.Sockets.TcpClient]::new()
            $task = $client.ConnectAsync($HostName, $Port)
            if (-not $task.Wait(3000)) { $client.Dispose(); exit 0 }
            $client.Dispose()
            exit 45
        } catch { exit 0 }
    }
    default { exit 46 }
}
'''


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
    no_window: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if no_window else 0,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit={result.returncode}"
        raise RuntimeError(f"命令失败：{Path(command[0]).name}: {detail}")
    return result


def _powershell(script: str) -> Any:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = _run(
        [HOST_POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        timeout=30,
        no_window=False,
    )
    text = result.stdout.strip()
    return json.loads(text) if text else None


def _discover_installation() -> Path:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Sandboxie-Plus",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Sandboxie",
    ]
    for root in candidates:
        if all((root / name).is_file() for name in COMPONENT_FILES.values()):
            return root.resolve()
    raise RuntimeError("未发现完整 Sandboxie 安装；缺少 Start.exe、SbieSvc.exe 或 SbieDrv.sys")


def _signature(path: Path) -> dict[str, str]:
    escaped = str(path).replace("'", "''")
    value = _powershell(
        "Get-AuthenticodeSignature -LiteralPath '"
        + escaped
        + "' | Select-Object @{Name='Status';Expression={[string]$_.Status}},"
        + "@{Name='Subject';Expression={[string]$_.SignerCertificate.Subject}} | ConvertTo-Json -Compress"
    )
    if not isinstance(value, dict):
        raise RuntimeError(f"无法读取组件签名：{path}")
    return {"signature_status": str(value["Status"]), "signer_subject": str(value["Subject"])}


def _file_version(path: Path) -> str:
    escaped = str(path).replace("'", "''")
    value = _powershell(
        "[pscustomobject]@{Version=(Get-Item -LiteralPath '"
        + escaped
        + "').VersionInfo.FileVersion} | ConvertTo-Json -Compress"
    )
    return str(value["Version"])


def _cim(class_name: str, name: str) -> dict[str, Any]:
    query_name = name.replace("'", "''")
    value = _powershell(
        f"Get-CimInstance {class_name} -Filter \"Name='{query_name}'\" | "
        "Select-Object Name,State,StartMode,PathName | ConvertTo-Json -Compress"
    )
    if not isinstance(value, dict):
        raise RuntimeError(f"未发现运行组件：{name}")
    raw_path = str(value["PathName"]).strip('"')
    raw_path = raw_path.removeprefix("\\??\\")
    return {
        "name": str(value["Name"]),
        "state": str(value["State"]),
        "start_mode": str(value["StartMode"]),
        "path": str(Path(raw_path).resolve()),
    }


def _sbie_query(sbie_ini: Path, section: str, setting: str | None = None) -> list[str]:
    command = [str(sbie_ini), "query", section]
    if setting is not None:
        command.append(setting)
    result = _run(command)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _export_configuration(sbie_ini: Path) -> tuple[str, list[str]]:
    sections = _sbie_query(sbie_ini, "*")
    lines: list[str] = []
    for section in sections:
        lines.append(f"[{section}]")
        for setting in _sbie_query(sbie_ini, section, "*"):
            values = _sbie_query(sbie_ini, section, setting)
            if values:
                lines.extend(f"{setting}={value}" for value in values)
            else:
                lines.append(f"{setting}=")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", sections


def _set(sbie_ini: Path, box: str, setting: str, value: str) -> None:
    _run([str(sbie_ini), "set", box, setting, value])


def _append(sbie_ini: Path, box: str, setting: str, value: str) -> None:
    _run([str(sbie_ini), "append", box, setting, value])


def _network_probe_dns(endpoint: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        addresses = sorted({str(item[4][0]) for item in socket.getaddrinfo(endpoint, 443)})
        status, observed = "passed", ",".join(addresses[:4])
    except OSError as exc:
        status, observed = "failed", f"{type(exc).__name__}: {exc}"
    return {
        "endpoint": endpoint,
        "status": status,
        "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
        "observed": observed,
    }


def _network_probe_tcp(host: str, port: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=5):
            status, observed = "passed", "connected"
    except OSError as exc:
        status, observed = "failed", f"{type(exc).__name__}: {exc}"
    return {
        "endpoint": f"{host}:{port}",
        "status": status,
        "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
        "observed": observed,
    }


def _sandbox_run(
    start: Path,
    box: str,
    probe: Path,
    mode: str,
    **kwargs: str | int | Path,
) -> int:
    command = [
        str(start),
        f"/box:{box}",
        "/silent",
        "/wait",
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(probe),
        "-Mode",
        mode,
    ]
    for key, value in kwargs.items():
        command.extend([f"-{key}", str(value)])
    for attempt in range(3):
        exit_code = _run(command, timeout=45, check=False).returncode
        if exit_code != TRANSIENT_START_EXIT:
            return exit_code
        if attempt < 2:
            time.sleep(1)
    return TRANSIENT_START_EXIT


def _control(control_id: str, exit_code: int, expected: str) -> dict[str, Any]:
    return {
        "control_id": control_id,
        "status": "passed" if exit_code == 0 else "failed",
        "expected": expected,
        "observed": "sandbox operation denied as expected" if exit_code == 0 else f"unexpected exit code {exit_code}",
        "exit_code": exit_code,
    }


def _process_ids(name: str) -> set[int]:
    escaped = name.replace("'", "''")
    value = _powershell(
        f"[int[]]$ids=@(Get-Process -Name '{escaped}' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id); ConvertTo-Json -Compress -InputObject $ids"
    )
    if value is None:
        return set()
    if isinstance(value, int):
        return {value}
    if isinstance(value, list):
        return {int(item) for item in value}
    raise RuntimeError(f"无法解析进程列表：{name}")


def _terminate_new_controllers(preexisting_pids: set[int]) -> bool:
    new_pids = _process_ids("SbieCtrl") - preexisting_pids
    for pid in new_pids:
        _run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], check=False)
    time.sleep(1)
    return not (_process_ids("SbieCtrl") - preexisting_pids)


def _restore_preexisting_configuration(
    sbie_ini: Path,
    backup_text: str,
    preexisting_sections: list[str],
) -> bool:
    """等待 Sandboxie 异步写入完成后，删除本次验证新增的辅助段。"""
    expected_sections = set(preexisting_sections)
    for _ in range(4):
        time.sleep(1)
        current_sections = _sbie_query(sbie_ini, "*")
        for section in set(current_sections) - expected_sections:
            _run([str(sbie_ini), "set", section, "*", ""], check=False)
        time.sleep(1)
        after_text, after_sections = _export_configuration(sbie_ini)
        if after_text == backup_text and after_sections == preexisting_sections:
            return True
    return False


def collect_report(output: Path) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise RuntimeError("Sandboxie 真实环境验证只能在 Windows 上执行")

    install_root = _discover_installation()
    start = install_root / "Start.exe"
    sbie_ini = install_root / "SbieIni.exe"
    if not sbie_ini.is_file():
        raise RuntimeError("缺少 SbieIni.exe，无法执行配置备份与可逆验证")

    output.parent.mkdir(parents=True, exist_ok=True)
    backup_path = output.parent / "sandboxie_config_backup.txt"
    backup_text, preexisting_sections = _export_configuration(sbie_ini)
    preexisting_controller_pids = _process_ids("SbieCtrl")
    backup_path.write_text(backup_text, encoding="utf-8", newline="\n")

    token = uuid.uuid4().hex[:12]
    box = f"ShumoM2{token}"
    temp_root = Path(tempfile.mkdtemp(prefix="shumo-m2-host-"))
    protected_dir = temp_root / "protected"
    protected_dir.mkdir()
    protected_file = protected_dir / "secret.txt"
    protected_baseline = "sandboxie-negative-control-secret\n"
    protected_file.write_text(protected_baseline, encoding="utf-8")
    probe_path = temp_root / "sandboxie_probe.ps1"
    probe_path.write_text(PROBE_SCRIPT, encoding="utf-8", newline="\n")
    virtualized_probe = temp_root / "sandbox-only.txt"
    registry_path = rf"HKEY_CURRENT_USER\Software\ShumoM2Probe_{token}"
    ps_registry_path = rf"HKCU:\Software\ShumoM2Probe_{token}"
    _run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            f"New-Item -Path '{ps_registry_path}' -Force | Out-Null; Set-ItemProperty -Path '{ps_registry_path}' -Name Value -Value baseline",
        ]
    )

    settings = [
        "Enabled=y",
        "AutoDelete=n",
        "DropAdminRights=y",
        "BlockNetworkFiles=y",
        "NotifyInternetAccessDenied=n",
        f"ClosedFilePath={protected_dir}",
        f"ClosedKeyPath={registry_path}",
        r"ClosedFilePath=\Device\Afd*",
        r"ClosedFilePath=\Device\Tcp*",
        r"ClosedFilePath=\Device\RawIp",
    ]
    cleanup = {
        "processes_terminated": False,
        "new_controller_processes_terminated": False,
        "sandbox_content_deleted": False,
        "box_configuration_removed": False,
        "preexisting_configuration_restored": False,
    }
    report: dict[str, Any] | None = None
    try:
        _set(sbie_ini, box, "Enabled", "y")
        _set(sbie_ini, box, "AutoDelete", "n")
        _set(sbie_ini, box, "DropAdminRights", "y")
        _set(sbie_ini, box, "BlockNetworkFiles", "y")
        _set(sbie_ini, box, "NotifyInternetAccessDenied", "n")
        _set(sbie_ini, box, "ClosedFilePath", str(protected_dir))
        _set(sbie_ini, box, "ClosedKeyPath", registry_path)
        for value in (r"\Device\Afd*", r"\Device\Tcp*", r"\Device\RawIp"):
            _append(sbie_ini, box, "ClosedFilePath", value)

        marker_exit = _sandbox_run(
            start,
            box,
            probe_path,
            "marker",
            WritableProbe=virtualized_probe,
        )
        controls = [
            _control("blocked_file_read", _sandbox_run(start, box, probe_path, "file_read", TargetFile=protected_file), "host file read denied"),
            _control("blocked_file_write", _sandbox_run(start, box, probe_path, "file_write", TargetFile=protected_file), "host file write denied"),
            _control("blocked_file_delete", _sandbox_run(start, box, probe_path, "file_delete", TargetFile=protected_file), "host file delete denied"),
            _control("blocked_directory_enumeration", _sandbox_run(start, box, probe_path, "directory_enumeration", TargetDir=protected_dir), "host directory enumeration denied"),
            _control("blocked_registry_read", _sandbox_run(start, box, probe_path, "registry_read", RegistryPath=registry_path), "host registry read denied"),
            _control("blocked_registry_write", _sandbox_run(start, box, probe_path, "registry_write", RegistryPath=registry_path), "host registry write denied"),
            _control("blocked_registry_delete", _sandbox_run(start, box, probe_path, "registry_delete", RegistryPath=registry_path), "host registry delete denied"),
            _control("dropped_admin_token", _sandbox_run(start, box, probe_path, "dropped_admin"), "administrator token absent"),
            _control("child_blocked_file_read", _sandbox_run(start, box, probe_path, "child_file_read", TargetFile=protected_file), "child process inherits file denial"),
        ]
        for index, (host, port) in enumerate(TCP_ENDPOINTS, start=1):
            controls.append(
                _control(
                    f"blocked_tcp_endpoint_{index}",
                    _sandbox_run(start, box, probe_path, "tcp", HostName=host, Port=port),
                    f"sandbox TCP denied for endpoint {index}",
                )
            )

        registry_value = _powershell(
            f"[string](Get-ItemPropertyValue -LiteralPath '{ps_registry_path}' -Name Value) | ConvertTo-Json -Compress"
        )
        protected_host_state_intact = (
            protected_file.is_file()
            and protected_file.read_text(encoding="utf-8") == protected_baseline
            and registry_value == "baseline"
            and not virtualized_probe.exists()
        )

        os_value = _powershell(
            "$o=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{Caption=$o.Caption; Version=$o.Version; Build=$o.BuildNumber; Architecture=$o.OSArchitecture} | ConvertTo-Json -Compress"
        )
        components = []
        for role, filename in COMPONENT_FILES.items():
            path = install_root / filename
            components.append(
                {
                    "role": role,
                    "path": str(path),
                    "file_sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                    "file_version": _file_version(path),
                    **_signature(path),
                }
            )
        dns_results = [_network_probe_dns(endpoint) for endpoint in DNS_ENDPOINTS]
        tcp_results = [_network_probe_tcp(host, port) for host, port in TCP_ENDPOINTS]
        passed = (
            marker_exit == 0
            and all(item["status"] == "passed" for item in controls)
            and sum(item["status"] == "passed" for item in dns_results) >= 2
            and sum(item["status"] == "passed" for item in tcp_results) >= 2
            and all(item["signature_status"] == "Valid" for item in components)
            and protected_host_state_intact
        )
        report = {
            "schema_version": "1.0.0",
            "report_id": f"sandboxie-env-{datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%z').replace('+', 'p')}-{token}",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "verification_status": "passed" if passed else "failed",
            "sandboxie_environment_verified": passed,
            "platform": {
                "system": "Windows",
                "caption": str(os_value["Caption"]),
                "version": str(os_value["Version"]),
                "build": str(os_value["Build"]),
                "architecture": str(os_value["Architecture"]),
            },
            "installation": {
                "product": "Sandboxie-Plus",
                "product_version": _file_version(install_root / "SandMan.exe"),
                "install_root": str(install_root),
                "origin": "preexisting",
                "components": components,
                "service": _cim("Win32_Service", "SbieSvc"),
                "driver": _cim("Win32_SystemDriver", "SbieDrv"),
            },
            "configuration_backup": {
                "method": "sbieini_export",
                "path": backup_path.name,
                "file_sha256": _sha256(backup_path),
                "size_bytes": backup_path.stat().st_size,
                "preexisting_sections": preexisting_sections,
            },
            "sandbox": {
                "box_name": box,
                "start_exit_code": marker_exit,
                "settings": settings,
                "settings_sha256": hashlib.sha256("\n".join(settings).encode("utf-8")).hexdigest(),
                "sandbox_marker_detected": marker_exit == 0,
                "protected_host_state_intact": protected_host_state_intact,
            },
            "negative_controls": controls,
            "network_probes": {
                "minimum_successful_dns": 2,
                "minimum_successful_tcp": 2,
                "dns": dns_results,
                "tcp": tcp_results,
            },
            "cleanup": cleanup,
        }
    finally:
        _run([str(start), f"/box:{box}", "/terminate"], check=False)
        cleanup["processes_terminated"] = True
        delete_result = _run(
            [str(start), f"/box:{box}", "/silent", "delete_sandbox_silent"],
            timeout=45,
            check=False,
        )
        cleanup["sandbox_content_deleted"] = delete_result.returncode == 0
        _run([str(sbie_ini), "set", box, "*", ""], check=False)
        cleanup["box_configuration_removed"] = box not in _sbie_query(sbie_ini, "*")
        cleanup["new_controller_processes_terminated"] = _terminate_new_controllers(
            preexisting_controller_pids
        )
        cleanup["preexisting_configuration_restored"] = _restore_preexisting_configuration(
            sbie_ini,
            backup_text,
            preexisting_sections,
        )
        _run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"Remove-Item -LiteralPath '{ps_registry_path}' -Recurse -Force -ErrorAction SilentlyContinue"],
            check=False,
        )
        shutil.rmtree(temp_root, ignore_errors=True)

    if report is None:
        raise RuntimeError("Sandboxie 验证未生成报告")
    cleanup_passed = all(cleanup.values())
    report["verification_status"] = "passed" if report["sandboxie_environment_verified"] and cleanup_passed else "failed"
    report["sandboxie_environment_verified"] = report["verification_status"] == "passed"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 Sandboxie Milestone 2 真实环境验证")
    parser.add_argument("--output", required=True, type=Path, help="环境报告输出路径")
    args = parser.parse_args()
    try:
        report = collect_report(args.output.resolve())
        summary = load_and_verify_sandboxie_environment_report(args.output.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[BLOCKED] Sandboxie 环境验证失败：{exc}", file=sys.stderr)
        return 2
    print(
        f"[VERIFIED] {summary['report_id']}："
        f"12/12 负控通过，sandboxie_environment_verified={report['sandboxie_environment_verified']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
