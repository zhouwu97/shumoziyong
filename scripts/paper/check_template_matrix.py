from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from .template_registry import (
        DEFAULT_MANIFEST_PATH,
        DEFAULT_OVERLAY_PATH,
        DEFAULT_VENDOR_ROOT,
        load_json_object,
        materialize_template,
        validate_registry,
    )
except ImportError:  # 允许直接执行脚本。
    from template_registry import (
        DEFAULT_MANIFEST_PATH,
        DEFAULT_OVERLAY_PATH,
        DEFAULT_VENDOR_ROOT,
        load_json_object,
        materialize_template,
        validate_registry,
    )


REPRESENTATIVE_XELATEX_KEYS = {
    "en/mcm",
    "zh/cumcm",
    "zh/huaweibei",
    "zh/shuweibei",
    "zh/stats",
}


class TemplateMatrixError(RuntimeError):
    """模板编译矩阵无法完成。"""


def plan_matrix(
    manifest: dict[str, Any],
    *,
    mode: str,
    only_engine: str | None = None,
) -> list[dict[str, Any]]:
    if mode not in {"ordinary", "full"}:
        raise ValueError(f"未知模板矩阵模式：{mode}")
    planned = []
    for template in manifest["templates"]:
        engine = str(template["engine"])
        if only_engine is not None and engine != only_engine:
            continue
        if mode == "ordinary" and engine == "xelatex":
            if template["logical_key"] not in REPRESENTATIVE_XELATEX_KEYS:
                continue
        planned.append(template)
    return sorted(planned, key=lambda item: str(item["template_id"]))


def _resolve_executable(overlay: dict[str, Any], engine: str) -> str:
    for candidate in overlay["engines"][engine]["executable_candidates"]:
        executable = shutil.which(str(candidate))
        if executable:
            return executable
    raise TemplateMatrixError(f"缺少模板编译引擎：{engine}")


def _renderer_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    value = (completed.stdout or completed.stderr).splitlines()
    if completed.returncode != 0 or not value:
        raise TemplateMatrixError(f"无法读取编译引擎版本：{executable}")
    return value[0].strip()


def _compile_one(
    template: dict[str, Any],
    *,
    manifest: dict[str, Any],
    vendor_root: Path,
    executable: str,
    passes: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="paper-template-matrix-") as temporary:
        stage = Path(temporary) / "paper"
        applied_overlays = materialize_template(
            manifest,
            {"template_id": template["template_id"]},
            target_dir=stage,
            vendor_root=vendor_root,
        )
        entry = stage / str(template["entry"])
        output = stage / "matrix-output.pdf"
        logs: list[str] = []
        return_code = 0
        for _index in range(passes):
            if template["engine"] == "typst":
                command = [
                    executable,
                    "compile",
                    "--root",
                    str(stage),
                    str(entry),
                    str(output),
                ]
            else:
                command = [
                    executable,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    entry.name,
                ]
            completed = subprocess.run(
                command,
                cwd=stage,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=180,
            )
            return_code = completed.returncode
            logs.append((completed.stdout or "") + (completed.stderr or ""))
            if return_code != 0:
                break
        expected_pdf = output if template["engine"] == "typst" else stage / "main.pdf"
        compiled = return_code == 0 and expected_pdf.is_file() and expected_pdf.stat().st_size > 0
        combined_log = "\n".join(logs)
        return {
            "template_id": template["template_id"],
            "logical_key": template["logical_key"],
            "engine": template["engine"],
            "status": "passed" if compiled else "failed",
            "passes_completed": len(logs),
            "warning_count": combined_log.lower().count("warning"),
            "applied_overlays": applied_overlays,
            "diagnostic_tail": combined_log[-2000:] if not compiled else "",
        }


def run_matrix(
    *,
    mode: str,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    overlay_path: Path = DEFAULT_OVERLAY_PATH,
    vendor_root: Path = DEFAULT_VENDOR_ROOT,
    only_engine: str | None = None,
) -> dict[str, Any]:
    manifest = load_json_object(manifest_path, "模板来源清单")
    overlay = load_json_object(overlay_path, "模板覆盖层")
    validate_registry(manifest, verify_source=True, vendor_root=vendor_root)
    planned = plan_matrix(manifest, mode=mode, only_engine=only_engine)
    engines = sorted({str(item["engine"]) for item in planned})
    executables = {engine: _resolve_executable(overlay, engine) for engine in engines}
    versions = {engine: _renderer_version(executable) for engine, executable in executables.items()}
    results = [
        _compile_one(
            template,
            manifest=manifest,
            vendor_root=vendor_root,
            executable=executables[str(template["engine"])],
            passes=int(overlay["engines"][str(template["engine"])]["passes"]),
        )
        for template in planned
    ]
    failed = sum(result["status"] == "failed" for result in results)
    return {
        "schema_version": "template_matrix_report_v1",
        "mode": mode,
        "source_commit": manifest["source"]["commit"],
        "renderer_versions": versions,
        "planned": len(planned),
        "passed": len(planned) - failed,
        "failed": failed,
        "status": "passed" if failed == 0 else "failed",
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="编译已注册论文模板矩阵")
    parser.add_argument("--mode", choices=("ordinary", "full"), default="ordinary")
    parser.add_argument("--only-engine", choices=("typst", "xelatex"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY_PATH)
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR_ROOT)
    parser.add_argument("--report", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_matrix(
        mode=args.mode,
        manifest_path=args.manifest,
        overlay_path=args.overlay,
        vendor_root=args.vendor_root,
        only_engine=args.only_engine,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "mode": report["mode"],
                "planned": report["planned"],
                "passed": report["passed"],
                "failed": report["failed"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
