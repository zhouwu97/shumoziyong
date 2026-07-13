"""在已验证 Sandboxie 环境中执行单个 Run，并生成机器签名证明。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formal_result.canonicalization import canonical_bytes
from formal_result.collector_policy import (
    COLLECTOR_ID,
    COLLECTOR_SCRIPT_PATH,
    DERIVATION_CONTRACT_ID,
    TRUSTED_DERIVATION_CONTRACT,
    bound_collector_source_commit,
    derivation_contract_sha256,
    domain_policy_sha256,
)
from formal_result.derivation import (
    DERIVATION_ATTESTATION_FILENAME,
    PAYLOAD_MANIFEST_FILENAME,
    core_semantic_hashes,
)
from formal_result.execution_contract import (
    compile_execution_command,
    launch_command_sha256,
    sandbox_policy_sha256,
)
from formal_result.hashing import file_sha256, semantic_sha256
from formal_result.run_execution_attestation import (
    ATTESTATION_FILENAME,
    EXECUTION_RECORD_FILENAME,
    OUTPUT_MANIFEST_FILENAME,
    verify_run_execution_attestation,
)
from formal_result.runtime_isolation import (
    ALLOWED_READ_ROOTS,
    ALLOWED_WRITE_ROOTS,
    READ_ISOLATION_MODE,
    RUNTIME_MANIFEST_FILENAME,
    SYSTEM_RUNTIME_READ_ROOTS,
    logical_drive_roots,
    materialize_runtime,
)
from formal_result.sandboxie_environment import (
    TRUST_REGISTRY_PATH,
    load_and_verify_sandboxie_environment_report,
)
from formal_result.verifier import verify_formal_result_bundle


ROOT = Path(__file__).resolve().parents[1]
TRANSIENT_START_EXIT = 0x40010004


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象：{path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(
    command: list[str],
    *,
    timeout: int = 60,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        cwd=cwd,
        env=env,
    )


def _sign(unsigned: Mapping[str, Any], thumbprint: str) -> str:
    payload = base64.b64encode(canonical_bytes(unsigned)).decode("ascii")
    command = (
        "Import-Module Microsoft.PowerShell.Security;"
        "$cert=Get-Item -LiteralPath 'Cert:\\CurrentUser\\My\\" + thumbprint + "';"
        "$rsa=[Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert);"
        "$data=[Convert]::FromBase64String('" + payload + "');"
        "$sig=$rsa.SignData($data,[Security.Cryptography.HashAlgorithmName]::SHA256,"
        "[Security.Cryptography.RSASignaturePadding]::Pkcs1);"
        "[Convert]::ToBase64String($sig)"
    )
    shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"
    result = _run([shell, "-NoProfile", "-NonInteractive", "-Command", command])
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("机器证书无法签署 Run Execution Attestation：" + result.stderr.strip())
    return result.stdout.strip()


def _manifest_items(manifest: Mapping[str, Any], field: str) -> list[dict[str, str]]:
    items = manifest.get("payload", {}).get(field)
    if not isinstance(items, list):
        raise ValueError(f"清单缺少 payload.{field}")
    return [{"path": str(item["path"]), "sha256": str(item["sha256"])} for item in items]


def _copy_manifest_files(run_dir: Path, target: Path, items: list[dict[str, str]], prefix: str) -> None:
    marker = prefix.rstrip("/") + "/"
    for item in items:
        if not item["path"].startswith(marker):
            raise ValueError(f"清单文件越出白名单前缀 {prefix}：{item['path']}")
        source = run_dir.joinpath(*PurePosixPath(item["path"]).parts)
        relative = item["path"].removeprefix(marker)
        destination = target.joinpath(*PurePosixPath(relative).parts)
        cursor = run_dir
        for part in PurePosixPath(item["path"]).parts:
            cursor /= part
            is_junction = getattr(cursor, "is_junction", lambda: False)
            if cursor.is_symlink() or is_junction():
                raise ValueError(f"白名单物化拒绝 symlink 或 junction：{item['path']}")
        if os.stat(source, follow_symlinks=False).st_nlink != 1:
            raise ValueError(f"白名单物化拒绝链接文件：{item['path']}")
        if file_sha256(source) != item["sha256"]:
            raise ValueError(f"物化前文件 SHA 漂移：{item['path']}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in root.rglob("*")
        if path.is_file()
    }


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _process_ids(name: str) -> set[int]:
    command = (
        f"@(Get-Process -Name {_ps_quote(name)} -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty Id) -join ','"
    )
    result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command])
    return {int(item) for item in result.stdout.strip().split(",") if item.strip().isdigit()}


def _sandbox_paths(box: str) -> list[str]:
    system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\") + "\\"
    roots = [
        Path(system_drive) / "Sandbox",
        Path(os.environ.get("USERPROFILE", "")) / "Sandbox",
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Sandboxie",
    ]
    found: list[str] = []
    for root in roots:
        if root.is_dir():
            found.extend(
                str(path)
                for path in root.rglob("*")
                if path.is_dir() and (path.name == box or path.name.startswith(f"__Delete_{box}"))
            )
    return sorted(set(found))


def _wait_sandbox_removed(box: str, timeout_seconds: int = 20) -> list[str]:
    deadline = time.monotonic() + timeout_seconds
    paths = _sandbox_paths(box)
    while paths and time.monotonic() < deadline:
        time.sleep(1)
        paths = _sandbox_paths(box)
    return paths


def _read_negative_control(
    start: Path,
    box: str,
    target: Path,
    control_id: str,
    cwd: Path,
    runtime_python: Path,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    probe = (
        "import ctypes,pathlib,sys;"
        "sys.exit(42) if not ctypes.windll.kernel32.GetModuleHandleW('SbieDll.dll') else None;"
        f"target=pathlib.Path({str(target)!r});"
        "\ntry:\n target.read_bytes()\nexcept OSError:\n sys.exit(0)\nelse:\n sys.exit(41)"
    )
    command = [
        str(start), f"/box:{box}", "/silent", "/wait", str(runtime_python), "-c", probe,
    ]
    result: subprocess.CompletedProcess[str] | None = None
    attempt_exit_codes: list[int] = []
    for attempt in range(3):
        result = _run(command, timeout=30, cwd=cwd, env=environment)
        attempt_exit_codes.append(result.returncode)
        if result.returncode != TRANSIENT_START_EXIT:
            break
        if attempt < 2:
            time.sleep(1)
    assert result is not None
    return {
        "control_id": control_id,
        "target_class": control_id.removeprefix("blocked_read_"),
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "attempt_exit_codes": attempt_exit_codes,
        "command_sha256": hashlib.sha256("\0".join(command).encode("utf-8")).hexdigest(),
    }


def _expand_report_path(value: str) -> Path:
    """只展开公开报告允许的固定脱敏令牌。"""
    replacements = {
        "%PROGRAMFILES%": os.environ.get("ProgramFiles", r"C:\Program Files"),
        "%PROGRAMDATA%": os.environ.get("ProgramData", r"C:\ProgramData"),
        "%SYSTEMROOT%": os.environ.get("SystemRoot", r"C:\Windows"),
        "%TEMP%": tempfile.gettempdir(),
    }
    expanded = value
    for token, replacement in replacements.items():
        expanded = expanded.replace(token, replacement)
    if "%" in expanded:
        raise ValueError(f"环境报告包含未批准的路径令牌：{value}")
    return Path(expanded).resolve(strict=True)


def _require_supporter_certificate(sbie_ini: Path) -> None:
    """Premium 隔离规则必须在物化或启动前确认合法凭据存在。"""
    result = _run([str(sbie_ini), "query", "global", "Certificate"], timeout=30)
    if result.returncode != 0:
        raise RuntimeError("无法查询 Sandboxie supporter certificate 状态")
    if not result.stdout.strip():
        raise RuntimeError(
            "Sandboxie 缺少 supporter certificate；UsePrivacyMode/UseRuleSpecificity "
            "不可用，拒绝生成 default_deny Attestation"
        )


def _rebind_formal_bundle(run_dir: Path, formal_result_id: str, run_summary: Mapping[str, Any]) -> None:
    """在 Run 证明落盘后，重新闭合 Formal Result 的不可变哈希链。"""
    formal = run_dir / "formal_results" / formal_result_id
    environment_path = formal / "environment_manifest.json"
    environment = _load(environment_path)
    payload = environment["payload"]
    payload.update(
        {
            "formal_result_activation_status": "run_execution_verified",
            "sandboxie_environment_observed": True,
            "sandboxie_environment_verified": True,
            "formal_result_executed_in_verified_environment": True,
            "formal_result_eligible": True,
            "sandboxie_run_execution_attestation": {
                "path": ATTESTATION_FILENAME,
                "file_sha256": run_summary["run_attestation_file_sha256"],
                "semantic_sha256": run_summary["run_attestation_semantic_sha256"],
                "execution_id": run_summary["execution_id"],
            },
        }
    )
    _write(environment_path, environment)

    collector_path = formal / "collector_attestation.json"
    collector = _load(collector_path)
    collector["environment_manifest_sha256"] = file_sha256(environment_path)
    _write(collector_path, collector)

    manifest_path = formal / "formal_result_manifest.json"
    manifest = _load(manifest_path)
    for name in list(manifest["semantic_hashes"]):
        manifest["semantic_hashes"][name] = semantic_sha256(_load(formal / name))
    _write(manifest_path, manifest)

    domain_path = formal / "domain_manifest.json"
    domain = _load(domain_path)
    for descriptor in domain["required_artifacts"]:
        artifact = formal / descriptor["path"]
        descriptor["file_sha256"] = file_sha256(artifact)
        if descriptor["media_type"] == "application/json":
            descriptor["semantic_sha256"] = semantic_sha256(_load(artifact))
    domain["semantic_hashes"] = {
        item["path"]: item["semantic_sha256"]
        for item in domain["required_artifacts"]
        if item["media_type"] == "application/json"
    }
    _write(domain_path, domain)

    envelope_path = formal / "formal_result_envelope.json"
    envelope = _load(envelope_path)
    envelope.update(
        {
            "domain_manifest_file_sha256": file_sha256(domain_path),
            "domain_manifest_semantic_sha256": semantic_sha256(domain),
            "formal_result_manifest_file_sha256": file_sha256(manifest_path),
            "formal_result_manifest_semantic_sha256": semantic_sha256(manifest),
            "collector_attestation_semantic_sha256": semantic_sha256(collector),
        }
    )
    _write(envelope_path, envelope)


def _derive_formal_result(
    run_dir: Path,
    formal_result_id: str,
    execution_id: str,
    derived_at: str,
    collector_source_commit: str,
    collector_script_sha256: str,
) -> dict[str, Any]:
    """按固定 JSON Pointer 合同从 raw result 生成最小工程优化 Formal core。"""
    raw_path = run_dir / "workspace" / "output" / "result.json"
    raw = _load(raw_path)
    objective = raw.get("objective")
    if not isinstance(objective, (int, float)) or isinstance(objective, bool):
        raise RuntimeError("Fixture raw result 缺少数值 objective，无法派生 Formal Result")
    formal = run_dir / "formal_results" / formal_result_id
    decision_path = formal / "decision_variables.json"
    decision = _load(decision_path)
    decision["payload"] = {"x": objective}
    _write(decision_path, decision)
    validation_path = formal / "optimization_validation.json"
    validation = _load(validation_path)
    validation["bindings"] = {"decision_variables.json": semantic_sha256(decision)}
    validation["payload"]["metrics"]["objective"] = objective
    _write(validation_path, validation)
    certificate_path = formal / "optimality_certificate.json"
    certificate = _load(certificate_path)
    certificate["bindings"] = {"optimization_validation.json": semantic_sha256(validation)}
    certificate["status"] = raw.get("solver_status")
    certificate["payload"]["solver_status"] = raw.get("solver_status")
    certificate["payload"]["raw_output_sha256"] = file_sha256(raw_path)
    _write(certificate_path, certificate)
    negative_path = formal / "negative_tests.json"
    negative = _load(negative_path)
    negative["status"] = raw.get("negative_tests_status")
    negative["payload"]["results"] = raw.get("negative_tests")
    _write(negative_path, negative)

    contract = TRUSTED_DERIVATION_CONTRACT
    hashes = core_semantic_hashes(formal)
    core_digest = semantic_sha256(hashes)
    output_sha = file_sha256(run_dir / OUTPUT_MANIFEST_FILENAME)
    derivation = {
        "schema_version": "1.0.0",
        "artifact_type": "collector_derivation_attestation",
        "run_id": _load(run_dir / "run_manifest.json")["run_id"],
        "formal_result_id": formal_result_id,
        "execution_id": execution_id,
        "run_output_manifest_sha256": output_sha,
        "result_derivation_contract": contract,
        "formal_core_semantic_sha256": hashes,
        "formal_result_core_digest": core_digest,
        "collector_id": COLLECTOR_ID,
        "collector_source_commit": collector_source_commit,
        "collector_script_path": COLLECTOR_SCRIPT_PATH,
        "collector_script_sha256": collector_script_sha256,
        "derivation_contract_id": DERIVATION_CONTRACT_ID,
        "derivation_contract_sha256": derivation_contract_sha256(),
        "domain_policy_sha256": domain_policy_sha256(),
        "derived_at": derived_at,
    }
    _write(run_dir / DERIVATION_ATTESTATION_FILENAME, derivation)
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "formal_result_payload_manifest",
        "run_id": derivation["run_id"],
        "formal_result_id": formal_result_id,
        "execution_id": execution_id,
        "run_output_manifest_sha256": output_sha,
        "formal_core_semantic_sha256": hashes,
        "formal_result_core_digest": core_digest,
        "result_derivation_contract": contract,
        "collector_derivation_attestation_sha256": file_sha256(
            run_dir / DERIVATION_ATTESTATION_FILENAME
        ),
    }
    _write(run_dir / PAYLOAD_MANIFEST_FILENAME, payload)
    return {
        "payload_manifest_sha256": file_sha256(run_dir / PAYLOAD_MANIFEST_FILENAME),
        "collector_derivation_attestation_sha256": file_sha256(
            run_dir / DERIVATION_ATTESTATION_FILENAME
        ),
        "formal_result_core_digest": core_digest,
    }


def execute_in_verified_sandbox(run_dir: Path, formal_result_id: str) -> dict[str, Any]:
    """执行白名单物化目录；任何现场漂移都不会生成资格证明。"""
    run_dir = run_dir.resolve()
    envelope = run_dir / "formal_results" / formal_result_id / "formal_result_envelope.json"
    initial = verify_formal_result_bundle(run_dir, envelope)
    if initial["formal_result_activation_status"] != "sandboxie_environment_verified":
        raise ValueError("新执行必须从仅环境已验证、尚未获得资格的 Formal Result 开始")
    environment = load_and_verify_sandboxie_environment_report(
        run_dir / "sandboxie_environment_report.json",
        run_dir / "sandboxie_environment_attestation.json",
    )
    if not environment["environment_attestation_currently_valid"]:
        raise ValueError("环境报告已过期，拒绝启动新执行")
    collector_source_commit, collector_script_sha = bound_collector_source_commit()

    spec_path = run_dir / "execution_spec.json"
    spec = _load(spec_path)
    if spec["run_id"] != _load(run_dir / "run_manifest.json")["run_id"]:
        raise ValueError("Execution Spec 与 Run ID 不匹配")
    task = spec["tasks"][0]
    formal = run_dir / "formal_results" / formal_result_id
    code_items = _manifest_items(_load(formal / "code_manifest.json"), "files")
    input_items = _manifest_items(_load(formal / "input_manifest.json"), "inputs")
    report = _load(run_dir / "sandboxie_environment_report.json")
    components = {item["role"]: item for item in report["installation"]["components"]}
    start = _expand_report_path(str(components["start_exe"]["path"]))
    sbie_ini = start.with_name("SbieIni.exe")
    _require_supporter_certificate(sbie_ini)

    archived_execution_root = run_dir / "execution_sandbox"
    if archived_execution_root.exists():
        raise ValueError("execution_sandbox 已存在；拒绝覆盖既有执行现场")
    execution_root = Path(tempfile.mkdtemp(prefix="shumo-m3a-execution-"))
    for child in ("code", "input", "output", "tmp"):
        (execution_root / child).mkdir(parents=True, exist_ok=True)
    _copy_manifest_files(run_dir, execution_root / "code", code_items, f"{spec['declared_workspace']}/code")
    unique_inputs = {item["path"]: item for item in input_items}
    _copy_manifest_files(run_dir, execution_root / "input", list(unique_inputs.values()), "problem")
    shutil.copyfile(spec_path, execution_root / "execution_spec.json")
    python, runtime_manifest = materialize_runtime(
        execution_root / "runtime", ROOT / "requirements.lock"
    )
    runtime_manifest_path = execution_root / RUNTIME_MANIFEST_FILENAME
    _write(runtime_manifest_path, runtime_manifest)
    runtime_manifest_sha = file_sha256(runtime_manifest_path)
    before = _snapshot(execution_root)

    box = f"ShumoM3A{uuid.uuid4().hex[:12]}"
    execution_id = f"sandboxie-exec-{uuid.uuid4().hex}"
    challenge = secrets.token_hex(32)
    compiled = compile_execution_command(
        spec,
        execution_root,
        execution_id=execution_id,
        challenge_nonce=challenge,
    )
    stdout_path = execution_root / "output" / "stdout.log"
    stderr_path = execution_root / "output" / "stderr.log"
    working_path = Path(str(compiled["resolved_working_directory_path"]))
    working_path.mkdir(parents=True, exist_ok=True)
    command = [
        str(start),
        f"/box:{box}",
        "/silent",
        "/wait",
        str(python),
        str(execution_root / "runtime" / "shumo_launch_wrapper.py"),
        str(working_path),
        *(str(item) for item in compiled["resolved_argv"][1:]),
    ]
    child_environment = dict(os.environ)
    child_environment.update(
        {name: str(value) for name, value in compiled["environment_overrides"].items()}
    )
    child_environment.update(
        {
            "PYTHONHOME": str(execution_root / "runtime"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": str(execution_root / "tmp"),
            "TMP": str(execution_root / "tmp"),
        }
    )
    start_sha = file_sha256(start)
    python_sha = file_sha256(python)
    command_sha = launch_command_sha256(
        compiled,
        start_exe_sha256=start_sha,
        python_sha256=python_sha,
        runtime_manifest_sha256=runtime_manifest_sha,
        sandboxie_box_name=box,
    )
    started_at = _now()
    other_temp_root = Path(tempfile.mkdtemp(prefix="shumo-m3a-sentinel-"))
    other_temp_sentinel = other_temp_root / "secret.txt"
    other_temp_sentinel.write_text(secrets.token_hex(16), encoding="utf-8")
    user_sentinel = Path.home() / f".shumo-m3a-sentinel-{uuid.uuid4().hex}.txt"
    user_sentinel.write_text(secrets.token_hex(16), encoding="utf-8")
    denied_host_roots = logical_drive_roots()
    normalized_policy = [
        "Enabled=y",
        "AutoDelete=n",
        "DropAdminRights=y",
        "BlockNetworkFiles=y",
        "UsePrivacyMode=y",
        "UseRuleSpecificity=y",
        "HideMessage=2203",
        "NotifyInternetAccessDenied=n",
        *(f"ReadFilePath=%EXECUTION_ROOT%\\{item}" for item in ALLOWED_READ_ROOTS),
        *(f"OpenFilePath=%EXECUTION_ROOT%\\{item}" for item in ALLOWED_WRITE_ROOTS),
        r"ClosedFilePath=\Device\Afd*",
        r"ClosedFilePath=\Device\Tcp*",
        r"ClosedFilePath=\Device\RawIp",
    ]
    policy_sha = sandbox_policy_sha256(normalized_policy)
    random_host_root = Path(tempfile.mkdtemp(prefix="shumo-m3a-unregistered-host-"))
    random_host_sentinel = random_host_root / f"unregistered-{uuid.uuid4().hex}.txt"
    random_host_sentinel.write_text(secrets.token_hex(16), encoding="utf-8")
    sentinels = {
        "blocked_read_original_run": run_dir / "run_manifest.json",
        "blocked_read_repo_unlisted": ROOT / "README.md",
        "blocked_read_other_temp": other_temp_sentinel,
        "blocked_read_user_home": user_sentinel,
        "blocked_read_random_unregistered_host_file": random_host_sentinel,
    }
    settings = [
        ("Enabled", "y"), ("AutoDelete", "n"), ("DropAdminRights", "y"),
        ("BlockNetworkFiles", "y"), ("NotifyInternetAccessDenied", "n"),
        ("UsePrivacyMode", "y"), ("UseRuleSpecificity", "y"), ("HideMessage", "2203"),
        *(("ReadFilePath", str(execution_root / item)) for item in ALLOWED_READ_ROOTS),
        *(("OpenFilePath", str(execution_root / item)) for item in ALLOWED_WRITE_ROOTS),
        ("ClosedFilePath", r"\Device\Afd*"),
        ("ClosedFilePath", r"\Device\Tcp*"),
        ("ClosedFilePath", r"\Device\RawIp"),
    ]
    result: subprocess.CompletedProcess[str] | None = None
    candidate_attempt_exit_codes: list[int] = []
    negative_controls: list[dict[str, Any]] = []
    controller_pids_before = sorted(_process_ids("SbieCtrl"))
    sections_before_result = _run([str(sbie_ini), "query", "*"])
    sections_before = sorted(
        line.strip() for line in sections_before_result.stdout.splitlines() if line.strip()
    )
    cleanup: dict[str, Any] = {}
    execution_error: Exception | None = None
    try:
        for index, (name, value) in enumerate(settings):
            verb = "set" if index == 0 or name not in {item[0] for item in settings[:index]} else "append"
            configured = _run([str(sbie_ini), verb, box, name, value])
            if configured.returncode != 0:
                raise RuntimeError(f"Sandboxie 配置失败：{name}")
        negative_controls = [
            _read_negative_control(
                start,
                box,
                target,
                control_id,
                execution_root,
                python,
                child_environment,
            )
            for control_id, target in sentinels.items()
        ]
        if any(item["status"] != "passed" for item in negative_controls):
            raise RuntimeError(
                "Sandboxie Run 外宿主读取负控失败："
                + json.dumps(negative_controls, ensure_ascii=False)
            )
        for attempt in range(3):
            result = _run(
                command,
                timeout=int(task["timeout_seconds"]) + 30,
                cwd=execution_root,
                env=child_environment,
            )
            candidate_attempt_exit_codes.append(result.returncode)
            if result.returncode != TRANSIENT_START_EXIT:
                break
            if attempt < 2:
                time.sleep(1)
    except Exception as exc:
        execution_error = exc
    finally:
        terminate = _run([str(start), f"/box:{box}", "/silent", "/terminate_all"], timeout=30)
        listed = _run([str(start), f"/box:{box}", "/silent", "/listpids"], timeout=30)
        delete = _run(
            [str(start), f"/box:{box}", "/silent", "delete_sandbox_silent"],
            timeout=45,
        )
        paths_after = _wait_sandbox_removed(box)
        remove_config = _run([str(sbie_ini), "set", box, "*", ""], timeout=30)
        query_config = _run([str(sbie_ini), "query", box, "*"], timeout=30)
        controller_pids_after = sorted(_process_ids("SbieCtrl"))
        remaining_pids = [
            int(line.strip())
            for line in listed.stdout.splitlines()
            if line.strip().isdigit() and int(line.strip()) > 0
        ]
        sections_after_result = _run([str(sbie_ini), "query", "*"])
        sections_after = sorted(
            line.strip()
            for line in sections_after_result.stdout.splitlines()
            if line.strip()
        )
        cleanup = {
            "terminate_exit_code": terminate.returncode,
            "delete_exit_code": delete.returncode,
            "box_processes_after": remaining_pids,
            "sandbox_paths_after": paths_after,
            "controller_pids_before": controller_pids_before,
            "new_controller_pids_after": sorted(
                set(controller_pids_after) - set(controller_pids_before)
            ),
            "configuration_remove_exit_code": remove_config.returncode,
            "box_configuration_removed": not query_config.stdout.strip(),
            "preexisting_configuration_sections": sections_before,
            "configuration_sections_after": sections_after,
            "preexisting_configuration_restored": sections_after == sections_before,
        }
        user_sentinel.unlink(missing_ok=True)
        shutil.rmtree(other_temp_root, ignore_errors=True)
        shutil.rmtree(random_host_root, ignore_errors=True)
    cleanup_passed = (
        cleanup.get("terminate_exit_code") == 0
        and cleanup.get("delete_exit_code") == 0
        and cleanup.get("box_processes_after") == []
        and cleanup.get("sandbox_paths_after") == []
        and cleanup.get("new_controller_pids_after") == []
        and cleanup.get("configuration_remove_exit_code") == 0
        and cleanup.get("box_configuration_removed") is True
        and cleanup.get("preexisting_configuration_restored") is True
    )
    if not cleanup_passed:
        shutil.rmtree(execution_root, ignore_errors=True)
        raise RuntimeError(
            "Sandboxie 清理证明未通过，拒绝生成 Run Attestation："
            + json.dumps(cleanup, ensure_ascii=False)
        )
    if execution_error is not None:
        shutil.rmtree(execution_root, ignore_errors=True)
        raise RuntimeError(f"Sandboxie 执行阶段失败：{execution_error}") from execution_error
    if result is None or result.returncode != 0:
        shutil.rmtree(execution_root, ignore_errors=True)
        raise RuntimeError(f"Sandboxie Run 执行失败，exit_code={None if result is None else result.returncode}")
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    if not stdout_path.is_file() or not stderr_path.is_file():
        shutil.rmtree(execution_root, ignore_errors=True)
        raise RuntimeError("Sandbox 内未生成真实子进程 stdout/stderr")

    after = _snapshot(execution_root)
    immutable_before = {key: value for key, value in before.items() if not key.startswith(("output/", "tmp/"))}
    immutable_after = {key: value for key, value in after.items() if not key.startswith(("output/", "tmp/"))}
    undeclared = sorted(
        key for key in after if key not in before and not key.startswith(("output/", "tmp/"))
    )
    expected_outputs = {
        PurePosixPath(item["path"]).relative_to(f"{spec['declared_workspace']}/output").as_posix()
        for item in task["required_outputs"]
    } | {"execution_challenge.json"}
    actual_outputs = {
        path.relative_to(execution_root / "output").as_posix()
        for path in (execution_root / "output").rglob("*")
        if path.is_file() and path.name not in {"stdout.log", "stderr.log"}
    }
    if immutable_before != immutable_after or undeclared or actual_outputs != expected_outputs:
        shutil.rmtree(execution_root, ignore_errors=True)
        raise RuntimeError("执行现场检查失败：代码/输入漂移、未声明写入或输出集合不精确")
    challenge_echo = _load(execution_root / "output" / "execution_challenge.json")
    if challenge_echo != {
        "challenge_nonce": challenge,
        "run_id": spec["run_id"],
        "execution_id": execution_id,
    }:
        shutil.rmtree(execution_root, ignore_errors=True)
        raise RuntimeError("候选进程未正确回显本次 Execution Challenge")
    acceptance_results = []
    for check in compiled["acceptance_checks"]:
        accepted = (execution_root / str(check["expectation"])).is_file()
        acceptance_results.append(
            {"check_id": check["check_id"], "status": "passed" if accepted else "failed"}
        )
    if any(item["status"] != "passed" for item in acceptance_results):
        shutil.rmtree(execution_root, ignore_errors=True)
        raise RuntimeError("Execution Spec acceptance check 未通过")
    shutil.copytree(
        execution_root,
        archived_execution_root,
        ignore=lambda directory, _names: ["runtime"] if Path(directory) == execution_root else [],
    )
    shutil.copyfile(runtime_manifest_path, run_dir / RUNTIME_MANIFEST_FILENAME)

    run_output = run_dir / "workspace" / "output"
    run_output.mkdir(parents=True, exist_ok=True)
    for relative in sorted(actual_outputs):
        destination = run_output.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(execution_root / "output" / relative, destination)
    output_manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "run_output_manifest",
        "run_id": spec["run_id"],
        "formal_result_id": formal_result_id,
        "execution_id": execution_id,
        "files": [
            {"path": relative, "sha256": file_sha256(run_output / relative)}
            for relative in sorted(actual_outputs)
        ],
    }
    _write(run_dir / OUTPUT_MANIFEST_FILENAME, output_manifest)
    completed_at = _now()
    derivation = _derive_formal_result(
        run_dir,
        formal_result_id,
        execution_id,
        completed_at,
        collector_source_commit,
        collector_script_sha,
    )
    record = {
        "schema_version": "1.0.0", "artifact_type": "sandboxie_run_execution_record",
        "run_id": spec["run_id"], "formal_result_id": formal_result_id,
        "execution_id": execution_id, "sandboxie_box_name": box,
        "sandbox_policy_sha256": policy_sha, "sandbox_policy_settings": normalized_policy,
        "read_isolation_mode": READ_ISOLATION_MODE,
        "runtime_manifest_sha256": runtime_manifest_sha,
        "denied_host_roots": denied_host_roots,
        "system_runtime_read_roots": SYSTEM_RUNTIME_READ_ROOTS,
        "allowed_read_roots": ALLOWED_READ_ROOTS,
        "allowed_write_roots": ALLOWED_WRITE_ROOTS,
        "resolved_argv": compiled["resolved_argv"],
        "resolved_working_directory": compiled["resolved_working_directory"],
        "seed": compiled["seed"],
        "environment_overrides": compiled["environment_overrides"],
        "acceptance_results": acceptance_results,
        "read_negative_controls": negative_controls,
        "candidate_attempt_exit_codes": candidate_attempt_exit_codes,
        "cleanup": cleanup,
        "launch_command_sha256": command_sha, "started_at": started_at,
        "completed_at": completed_at, "challenge_nonce": challenge,
        "exit_code": result.returncode, "stdout_sha256": file_sha256(stdout_path),
        "stderr_sha256": file_sha256(stderr_path), "start_exe_sha256": file_sha256(start),
        "execution_challenge_sha256": file_sha256(
            run_dir / "workspace" / "output" / "execution_challenge.json"
        ),
        "sandboxie_marker_detected": True, "undeclared_write_count": 0,
        "code_unchanged": True, "input_unchanged": True, "output_set_exact": True,
        "python_sha256": python_sha, "python_version": sys.version,
        "requirements_lock_sha256": file_sha256(ROOT / "requirements.lock"),
    }
    _write(run_dir / EXECUTION_RECORD_FILENAME, record)

    registry = _load(TRUST_REGISTRY_PATH)
    key = next(item for item in registry["keys"] if item["machine_key_id"] == environment["machine_key_id"])
    unsigned = {
        "attestation_version": "1.0.0", "artifact_type": "sandboxie_run_execution_attestation",
        "run_id": spec["run_id"], "formal_result_id": formal_result_id,
        "execution_id": execution_id, "execution_spec_sha256": file_sha256(spec_path),
        "run_manifest_sha256": file_sha256(run_dir / "run_manifest.json"),
        "code_manifest_sha256": file_sha256(formal / "code_manifest.json"),
        "input_manifest_sha256": file_sha256(formal / "input_manifest.json"),
        "output_manifest_sha256": file_sha256(run_dir / OUTPUT_MANIFEST_FILENAME),
        "execution_record_sha256": file_sha256(run_dir / EXECUTION_RECORD_FILENAME),
        "runtime_manifest_sha256": runtime_manifest_sha,
        "formal_result_payload_manifest_sha256": derivation[
            "payload_manifest_sha256"
        ],
        "collector_derivation_attestation_sha256": derivation[
            "collector_derivation_attestation_sha256"
        ],
        "formal_result_core_digest": derivation["formal_result_core_digest"],
        "environment_report_sha256": environment["report_file_sha256"],
        "environment_attestation_sha256": environment["attestation_file_sha256"],
        "trusted_registry_sha256": environment["trusted_registry_sha256"],
        "trusted_key_entry_semantic_sha256": environment["trusted_key_entry_semantic_sha256"],
        "environment_fingerprint": environment["environment_fingerprint"],
        "start_exe_sha256": file_sha256(start), "sandboxie_box_name": box,
        "sandbox_policy_sha256": policy_sha,
        "launch_command_sha256": command_sha, "started_at": started_at,
        "completed_at": completed_at, "challenge_nonce": challenge,
        "exit_code": result.returncode, "stdout_sha256": file_sha256(stdout_path),
        "stderr_sha256": file_sha256(stderr_path), "machine_key_id": environment["machine_key_id"],
        "signature_algorithm": key["signature_algorithm"],
    }
    attestation = {**unsigned, "signature": _sign(unsigned, key["certificate_thumbprint"])}
    _write(run_dir / ATTESTATION_FILENAME, attestation)
    try:
        run_summary = verify_run_execution_attestation(run_dir, formal_result_id)
        _rebind_formal_bundle(run_dir, formal_result_id, run_summary)
        return verify_formal_result_bundle(run_dir, envelope)
    finally:
        shutil.rmtree(execution_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="在已验证 Sandboxie 中执行 Run")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--formal-result-id", required=True)
    args = parser.parse_args()
    summary = execute_in_verified_sandbox(args.run_dir, args.formal_result_id)
    print(json.dumps({"run_id": summary["identity"]["run_id"], "formal_result_eligible": summary["formal_result_eligible"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
