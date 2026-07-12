"""在 Windows 上生成 Sandboxie Milestone 2 机器签名环境证明。"""

from __future__ import annotations

import argparse
import base64
import copy
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formal_result.canonicalization import canonical_bytes  # noqa: E402
from formal_result.hashing import file_sha256, semantic_sha256  # noqa: E402
from formal_result.sandboxie_environment import (  # noqa: E402
    ATTESTATION_FILENAME,
    environment_fingerprint,
    load_and_verify_sandboxie_environment_report,
)


ROOT = Path(__file__).resolve().parents[1]
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
PROBE_SHA256 = hashlib.sha256(PROBE_SCRIPT.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def _source_commit() -> str:
    status = _run(["git", "status", "--porcelain", "--untracked-files=no"], check=True)
    if status.stdout.strip():
        raise RuntimeError("生成机器签名报告前必须先提交全部 tracked 代码变更")
    value = _run(["git", "rev-parse", "HEAD"], check=True).stdout.strip()
    if len(value) != 40:
        raise RuntimeError("无法解析生成器 source commit")
    return value


def _discover_installation() -> Path:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Sandboxie-Plus",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Sandboxie",
    ]
    for root in candidates:
        if all((root / name).is_file() for name in COMPONENT_FILES.values()):
            return root.resolve()
    raise RuntimeError("未发现完整 Sandboxie 安装；缺少 Start.exe、SbieSvc.exe 或 SbieDrv.sys")


def _authenticode(path: Path) -> dict[str, str]:
    escaped = str(path).replace("'", "''")
    value = _powershell(
        "$s=Get-AuthenticodeSignature -LiteralPath '"
        + escaped
        + "'; $c=$s.SignerCertificate; $chain=[Security.Cryptography.X509Certificates.X509Chain]::new(); "
        + "$ok=$chain.Build($c); $selfSigned=($c.Subject -eq $c.Issuer); "
        + "$chainState=if($ok){'Valid'}elseif($selfSigned -and @($chain.ChainStatus).Count -eq 1 -and $chain.ChainStatus[0].Status -eq [Security.Cryptography.X509Certificates.X509ChainStatusFlags]::UntrustedRoot){'ValidSelfSignedRoot'}else{'Invalid'}; "
        + "[pscustomobject]@{Status=[string]($s.Status);Subject=[string]$c.Subject;Issuer=[string]$c.Issuer;Thumbprint=[string]$c.Thumbprint;NotBefore=$c.NotBefore.ToUniversalTime().ToString('o');NotAfter=$c.NotAfter.ToUniversalTime().ToString('o');ChainStatus=$chainState}|ConvertTo-Json -Compress"
    )
    if not isinstance(value, dict):
        raise RuntimeError(f"无法读取组件签名：{path}")
    return {
        "status": str(value["Status"]),
        "subject": str(value["Subject"]),
        "issuer": str(value["Issuer"]),
        "certificate_thumbprint": str(value["Thumbprint"]).lower(),
        "not_before": str(value["NotBefore"]),
        "not_after": str(value["NotAfter"]),
        "chain_status": str(value["ChainStatus"]),
    }


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
    raw_path = str(value["PathName"]).strip('"').removeprefix("\\??\\")
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
            lines.extend(f"{setting}={value}" for value in values or [""])
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
) -> dict[str, Any]:
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
    started_at = _now()
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(3):
        result = _run(command, timeout=45, check=False)
        if result.returncode != TRANSIENT_START_EXIT:
            break
        if attempt < 2:
            time.sleep(1)
    assert result is not None
    return {
        "command_sha256": _sha256_bytes("\0".join(command).encode("utf-8")),
        "started_at": started_at,
        "completed_at": _now(),
        "exit_code": result.returncode,
        "stdout_sha256": _sha256_bytes(result.stdout.encode("utf-8")),
        "stderr_sha256": _sha256_bytes(result.stderr.encode("utf-8")),
    }


def _control(
    control_id: str,
    execution: dict[str, Any],
    expected: str,
    target: str,
) -> dict[str, Any]:
    exit_code = int(execution["exit_code"])
    return {
        "control_id": control_id,
        "status": "passed" if exit_code == 0 else "failed",
        "expected": expected,
        "observed": "sandbox operation denied as expected"
        if exit_code == 0
        else f"unexpected exit code {exit_code}",
        "target": target,
        "probe_sha256": PROBE_SHA256,
        **execution,
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


def _box_process_ids(start: Path, box: str) -> tuple[int, list[int]]:
    result = _run([str(start), f"/box:{box}", "/silent", "/listpids"], check=False)
    pids = sorted(
        int(line.strip())
        for line in result.stdout.splitlines()
        if line.strip().isdigit() and int(line.strip()) > 0
    )
    return result.returncode, pids


def _terminate_new_controllers(preexisting_pids: set[int]) -> tuple[bool, list[int]]:
    for pid in _process_ids("SbieCtrl") - preexisting_pids:
        _run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], check=False)
    time.sleep(1)
    remaining = sorted(_process_ids("SbieCtrl") - preexisting_pids)
    return not remaining, remaining


def _restore_preexisting_configuration(
    sbie_ini: Path,
    backup_text: str,
    preexisting_sections: list[str],
) -> bool:
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


def _sandbox_roots() -> list[Path]:
    return [
        Path(os.environ.get("SystemDrive", "C:")) / "Sandbox",
        Path(os.environ.get("USERPROFILE", "")) / "Sandbox",
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Sandboxie",
    ]


def _find_sandbox_paths(box: str) -> list[Path]:
    found: set[Path] = set()
    for root in _sandbox_roots():
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_dir() and (path.name == box or box in path.name and path.name.startswith("__Delete_")):
                found.add(path.resolve())
    return sorted(found)


def _redact_text(value: str, replacements: list[tuple[str, str]]) -> str:
    result = value
    for raw, token in replacements:
        if raw:
            result = result.replace(raw, token).replace(raw.lower(), token)
    return result


def _redact_value(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, replacements)
    if isinstance(value, list):
        return [_redact_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, replacements) for key, item in value.items()}
    return value


def _sign_attestation(unsigned: dict[str, Any], certificate_thumbprint: str) -> str:
    payload = base64.b64encode(canonical_bytes(unsigned)).decode("ascii")
    thumbprint = certificate_thumbprint.replace("'", "''")
    value = _powershell(
        "$cert=Get-Item -LiteralPath 'Cert:\\CurrentUser\\My\\"
        + thumbprint
        + "'; if(-not $cert.HasPrivateKey){throw 'certificate private key missing'}; "
        + "$rsa=[Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert); "
        + "$data=[Convert]::FromBase64String('"
        + payload
        + "'); $sig=$rsa.SignData($data,[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1); "
        + "[pscustomobject]@{Signature=[Convert]::ToBase64String($sig)}|ConvertTo-Json -Compress"
    )
    if not isinstance(value, dict) or not value.get("Signature"):
        raise RuntimeError("机器证书未返回 Attestation 签名")
    return str(value["Signature"])


def collect_report(
    public_output: Path,
    private_output: Path,
    attestation_output: Path,
    machine_key_id: str,
    certificate_thumbprint: str,
    validity_hours: int,
) -> dict[str, Any]:
    if platform.system() != "Windows":
        raise RuntimeError("Sandboxie 真实环境验证只能在 Windows 上执行")
    source_commit = _source_commit()
    probe_started_at = _now()
    install_root = _discover_installation()
    start = install_root / "Start.exe"
    sbie_ini = install_root / "SbieIni.exe"
    if not sbie_ini.is_file():
        raise RuntimeError("缺少 SbieIni.exe，无法执行配置备份与可逆验证")

    public_output.parent.mkdir(parents=True, exist_ok=True)
    private_output.parent.mkdir(parents=True, exist_ok=True)
    attestation_output.parent.mkdir(parents=True, exist_ok=True)
    raw_backup_path = private_output.parent / "sandboxie_config_backup.raw.txt"
    public_backup_path = public_output.parent / "sandboxie_config_backup.txt"
    backup_text, preexisting_sections = _export_configuration(sbie_ini)
    raw_backup_path.write_text(backup_text, encoding="utf-8", newline="\n")
    preexisting_controller_pids = _process_ids("SbieCtrl")

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
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
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
    cleanup: dict[str, Any] = {
        "terminate_exit_code": 1,
        "delete_exit_code": 1,
        "box_processes_before": [],
        "box_processes_after": [],
        "sandbox_content_path": str(Path(os.environ.get("SystemDrive", "C:")) / "Sandbox" / os.environ.get("USERNAME", "user") / box),
        "sandbox_content_exists_after": True,
        "preexisting_controller_pids": sorted(preexisting_controller_pids),
        "new_controller_pids_after": [],
        "processes_terminated": False,
        "new_controller_processes_terminated": False,
        "sandbox_content_deleted": False,
        "box_configuration_removed": False,
        "preexisting_configuration_restored": False,
    }
    marker: dict[str, Any] | None = None
    controls: list[dict[str, Any]] = []
    dns_results: list[dict[str, Any]] = []
    tcp_results: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    os_value: dict[str, Any] | None = None
    content_paths: list[Path] = []
    protected_host_state_intact = False
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

        marker = _sandbox_run(
            start,
            box,
            probe_path,
            "marker",
            WritableProbe=virtualized_probe,
        )
        controls = [
            _control("blocked_file_read", _sandbox_run(start, box, probe_path, "file_read", TargetFile=protected_file), "host file read denied", str(protected_file)),
            _control("blocked_file_write", _sandbox_run(start, box, probe_path, "file_write", TargetFile=protected_file), "host file write denied", str(protected_file)),
            _control("blocked_file_delete", _sandbox_run(start, box, probe_path, "file_delete", TargetFile=protected_file), "host file delete denied", str(protected_file)),
            _control("blocked_directory_enumeration", _sandbox_run(start, box, probe_path, "directory_enumeration", TargetDir=protected_dir), "host directory enumeration denied", str(protected_dir)),
            _control("blocked_registry_read", _sandbox_run(start, box, probe_path, "registry_read", RegistryPath=registry_path), "host registry read denied", registry_path),
            _control("blocked_registry_write", _sandbox_run(start, box, probe_path, "registry_write", RegistryPath=registry_path), "host registry write denied", registry_path),
            _control("blocked_registry_delete", _sandbox_run(start, box, probe_path, "registry_delete", RegistryPath=registry_path), "host registry delete denied", registry_path),
            _control("dropped_admin_token", _sandbox_run(start, box, probe_path, "dropped_admin"), "administrator token absent", "administrator-token"),
            _control("child_blocked_file_read", _sandbox_run(start, box, probe_path, "child_file_read", TargetFile=protected_file), "child process inherits file denial", str(protected_file)),
        ]
        for index, (host, port) in enumerate(TCP_ENDPOINTS, start=1):
            controls.append(
                _control(
                    f"blocked_tcp_endpoint_{index}",
                    _sandbox_run(start, box, probe_path, "tcp", HostName=host, Port=port),
                    f"sandbox TCP denied for endpoint {index}",
                    f"{host}:{port}",
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
        content_paths = _find_sandbox_paths(box)
        if not content_paths:
            raise RuntimeError("无法定位验证箱真实内容目录")
        cleanup["sandbox_content_path"] = str(content_paths[0])

        os_value = _powershell(
            "$o=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{Caption=$o.Caption; Version=$o.Version; Build=$o.BuildNumber; Architecture=$o.OSArchitecture} | ConvertTo-Json -Compress"
        )
        for role, filename in COMPONENT_FILES.items():
            path = install_root / filename
            components.append(
                {
                    "role": role,
                    "path": str(path),
                    "file_sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                    "file_version": _file_version(path),
                    "signature": _authenticode(path),
                }
            )
        dns_results = [_network_probe_dns(endpoint) for endpoint in DNS_ENDPOINTS]
        tcp_results = [_network_probe_tcp(host, port) for host, port in TCP_ENDPOINTS]
    finally:
        _list_exit, cleanup["box_processes_before"] = _box_process_ids(start, box)
        terminate_result = _run([str(start), f"/box:{box}", "/silent", "/terminate"], check=False)
        cleanup["terminate_exit_code"] = terminate_result.returncode
        _after_exit, cleanup["box_processes_after"] = _box_process_ids(start, box)
        cleanup["processes_terminated"] = (
            terminate_result.returncode == 0 and cleanup["box_processes_after"] == []
        )
        delete_result = _run(
            [str(start), f"/box:{box}", "/silent", "delete_sandbox_silent"],
            timeout=45,
            check=False,
        )
        cleanup["delete_exit_code"] = delete_result.returncode
        cleanup["sandbox_content_exists_after"] = bool(_find_sandbox_paths(box))
        cleanup["sandbox_content_deleted"] = (
            delete_result.returncode == 0 and not cleanup["sandbox_content_exists_after"]
        )
        _run([str(sbie_ini), "set", box, "*", ""], check=False)
        cleanup["box_configuration_removed"] = box not in _sbie_query(sbie_ini, "*")
        (
            cleanup["new_controller_processes_terminated"],
            cleanup["new_controller_pids_after"],
        ) = _terminate_new_controllers(preexisting_controller_pids)
        cleanup["preexisting_configuration_restored"] = _restore_preexisting_configuration(
            sbie_ini,
            backup_text,
            preexisting_sections,
        )
        _run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Remove-Item -LiteralPath '{ps_registry_path}' -Recurse -Force -ErrorAction SilentlyContinue",
            ],
            check=False,
        )
        shutil.rmtree(temp_root, ignore_errors=True)

    if marker is None or os_value is None:
        raise RuntimeError("Sandboxie 验证未生成完整报告")
    probe_completed_at = _now()
    generated_at = _now()
    valid_until = (datetime.now().astimezone() + timedelta(hours=validity_hours)).isoformat(
        timespec="seconds"
    )
    passed = (
        marker["exit_code"] == 0
        and all(item["status"] == "passed" for item in controls)
        and sum(item["status"] == "passed" for item in dns_results) >= 2
        and sum(item["status"] == "passed" for item in tcp_results) >= 2
        and all(item["signature"]["status"] == "Valid" for item in components)
        and protected_host_state_intact
        and all(
            cleanup[field]
            for field in (
                "processes_terminated",
                "new_controller_processes_terminated",
                "sandbox_content_deleted",
                "box_configuration_removed",
                "preexisting_configuration_restored",
            )
        )
    )
    raw_report: dict[str, Any] = {
        "schema_version": "2.0.0",
        "report_kind": "live_attestation",
        "report_id": f"sandboxie-env-{datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%z').replace('+', 'p')}-{token}",
        "generated_at": generated_at,
        "valid_until": valid_until,
        "probe_started_at": probe_started_at,
        "probe_completed_at": probe_completed_at,
        "verification_status": "passed" if passed else "failed",
        "sandboxie_environment_verified": passed,
        "formal_result_executed_in_verified_environment": False,
        "collector": {
            "tool_id": "verify_sandboxie_environment.py",
            "source_commit": source_commit,
            "probe_script_sha256": PROBE_SHA256,
            "challenge_nonce": uuid.uuid4().hex + uuid.uuid4().hex,
            "machine_key_id": machine_key_id,
            "environment_fingerprint": "0" * 64,
            "redaction_policy_version": "none",
        },
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
            "path": raw_backup_path.name,
            "file_sha256": _sha256(raw_backup_path),
            "size_bytes": raw_backup_path.stat().st_size,
            "preexisting_sections": preexisting_sections,
        },
        "sandbox": {
            "box_name": box,
            "start_exit_code": marker["exit_code"],
            "start_exe_sha256": next(
                item["file_sha256"] for item in components if item["role"] == "start_exe"
            ),
            "start_command_sha256": marker["command_sha256"],
            "settings": settings,
            "settings_sha256": _sha256_bytes("\n".join(settings).encode("utf-8")),
            "sandbox_marker_detected": marker["exit_code"] == 0,
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
    raw_report["collector"]["environment_fingerprint"] = environment_fingerprint(raw_report)
    private_output.write_text(
        json.dumps(raw_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    replacements = sorted(
        [
            (str(install_root), r"%PROGRAMFILES%\Sandboxie-Plus"),
            (tempfile.gettempdir(), r"%TEMP%"),
            (os.environ.get("USERPROFILE", ""), r"%USERPROFILE%"),
            (os.environ.get("USERNAME", ""), r"%USERNAME%"),
        ],
        key=lambda item: len(item[0]),
        reverse=True,
    )
    public_backup_text = _redact_text(backup_text, replacements)
    public_backup_path.write_text(public_backup_text, encoding="utf-8", newline="\n")
    public_report = _redact_value(copy.deepcopy(raw_report), replacements)
    public_report["collector"]["redaction_policy_version"] = "1.0.0"
    public_report["configuration_backup"] = {
        **public_report["configuration_backup"],
        "path": public_backup_path.name,
        "file_sha256": _sha256(public_backup_path),
        "size_bytes": public_backup_path.stat().st_size,
    }
    public_report["collector"]["environment_fingerprint"] = environment_fingerprint(public_report)
    public_output.write_text(
        json.dumps(public_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    unsigned_attestation = {
        "attestation_version": "1.0.0",
        "report_kind": "live_attestation",
        "report_id": public_report["report_id"],
        "public_report_sha256": file_sha256(public_output),
        "public_report_semantic_sha256": semantic_sha256(public_report),
        "original_report_sha256": file_sha256(private_output),
        "configuration_backup_sha256": file_sha256(public_backup_path),
        "probe_script_sha256": PROBE_SHA256,
        "collector_source_commit": source_commit,
        "machine_key_id": machine_key_id,
        "environment_fingerprint": public_report["collector"]["environment_fingerprint"],
        "generated_at": generated_at,
        "valid_until": valid_until,
        "signature_algorithm": "RSASSA-PKCS1-v1_5-SHA256",
    }
    attestation = {
        **unsigned_attestation,
        "signature": _sign_attestation(unsigned_attestation, certificate_thumbprint),
    }
    attestation_output.write_text(
        json.dumps(attestation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return public_report


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 Sandboxie Milestone 2 机器签名环境验证")
    parser.add_argument("--output", required=True, type=Path, help="公开脱敏报告输出路径")
    parser.add_argument("--private-output", required=True, type=Path, help="本地私有原始报告路径")
    parser.add_argument(
        "--attestation-output",
        type=Path,
        help=f"机器签名证明路径；默认与公开报告同目录的 {ATTESTATION_FILENAME}",
    )
    parser.add_argument("--machine-key-id", required=True, help="可信环境注册表中的机器密钥 ID")
    parser.add_argument("--certificate-thumbprint", required=True, help="Windows 当前用户证书指纹")
    parser.add_argument("--validity-hours", type=int, default=24, choices=range(1, 169))
    args = parser.parse_args()
    public_output = args.output.resolve()
    private_output = args.private_output.resolve()
    attestation_output = (
        args.attestation_output.resolve()
        if args.attestation_output is not None
        else public_output.with_name(ATTESTATION_FILENAME)
    )
    try:
        report = collect_report(
            public_output,
            private_output,
            attestation_output,
            args.machine_key_id,
            args.certificate_thumbprint,
            args.validity_hours,
        )
        summary = load_and_verify_sandboxie_environment_report(
            public_output,
            attestation_output,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[BLOCKED] Sandboxie 环境验证失败：{exc}", file=sys.stderr)
        return 2
    print(
        f"[VERIFIED] {summary['report_id']}：12/12 负控通过，"
        f"sandboxie_environment_verified={report['sandboxie_environment_verified']}，"
        "formal_result_eligible=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
