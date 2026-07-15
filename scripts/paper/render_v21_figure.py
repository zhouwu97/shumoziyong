"""按 nature-figure 合同使用 Python 生成正式图表并执行最小视觉 QA。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(run_dir: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(run_dir).as_posix(), "sha256": sha256_file(path)}


def _validate_source_attestation(
    run_dir: Path,
    source_ref: dict[str, str],
    attestation_ref: dict[str, str] | None,
) -> dict[str, str] | None:
    """验证非 Formal Result 图表数据的独立来源证明。"""
    if source_ref["path"].replace("\\", "/").startswith("formal_results/"):
        return None
    if not attestation_ref:
        raise ValueError("非 active Formal Result 图表数据必须提供 source_data_attestation_ref")
    attestation_path = (run_dir / attestation_ref["path"]).resolve()
    if not attestation_path.is_relative_to(run_dir) or not attestation_path.is_file():
        raise ValueError("source_data_attestation_ref 不在当前 Run 内或不存在")
    if sha256_file(attestation_path) != attestation_ref["sha256"]:
        raise ValueError("source_data_attestation_ref SHA-256 不匹配")
    try:
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("source_data_attestation_ref 不是合法 JSON") from exc
    if attestation.get("status") != "verified":
        raise ValueError("图表数据 attestation.status 必须为 verified")
    attested_source = attestation.get("source_data_ref")
    if not isinstance(attested_source, dict):
        raise ValueError("图表数据 attestation 缺少 source_data_ref")
    if attested_source.get("path") != source_ref["path"] or attested_source.get("sha256") != source_ref["sha256"]:
        raise ValueError("图表数据 attestation 与 source_data_ref 不一致")
    return attestation_ref


def render(run_dir: Path, contract_path: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    source_ref = contract["source_data_ref"]
    source = (run_dir / source_ref["path"]).resolve()
    if not source.is_relative_to(run_dir) or not source.is_file():
        raise ValueError("图表 source_data 不在当前 Run 内或不存在")
    if sha256_file(source) != source_ref["sha256"]:
        raise ValueError("图表 source_data SHA-256 不匹配")
    attestation_ref = _validate_source_attestation(
        run_dir,
        source_ref,
        contract.get("source_data_attestation_ref"),
    )
    rows = list(csv.DictReader(source.read_text(encoding="utf-8-sig").splitlines()))
    if not rows:
        raise ValueError("图表 source_data 为空")
    x_name, y_name = contract["x"], contract["y"]
    x = np.array([float(row[x_name]) for row in rows], dtype=float)
    y = np.array([float(row[y_name]) for row in rows], dtype=float)

    output_dir = run_dir / contract.get("output_dir", "figures")
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_id = contract["figure_id"]
    fig, ax = plt.subplots(figsize=(6.5, 4.2), constrained_layout=True)
    chart_type = contract["chart_type"]
    if chart_type == "line":
        ax.plot(x, y, color="#1f4e79", linewidth=2.0, marker="o", markersize=4)
    elif chart_type == "bar":
        ax.bar(x, y, color="#2f7f5f", edgecolor="#173f2d", linewidth=0.6)
    else:
        ax.scatter(x, y, color="#b04a3a", edgecolor="white", linewidth=0.6, s=36)
    ax.set_title(contract.get("title", ""), fontsize=11, pad=8)
    ax.set_xlabel(contract.get("xlabel", x_name))
    ax.set_ylabel(contract.get("ylabel", y_name))
    ax.grid(True, color="#d9dee5", linewidth=0.6, alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for fmt in ("svg", "pdf", "tiff"):
        fig.savefig(output_dir / f"{figure_id}.{fmt}", dpi=400, bbox_inches="tight")
    plt.close(fig)

    script_copy = run_dir / "paper" / "scripts" / "render_v21_figure.py"
    script_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), script_copy)
    qa: dict[str, Any] = {"figure_id": figure_id, "status": "passed", "checks": []}
    for fmt in ("svg", "pdf", "tiff"):
        path = output_dir / f"{figure_id}.{fmt}"
        if not path.is_file() or path.stat().st_size == 0:
            qa["status"] = "failed"
            qa["checks"].append({"file": fmt, "passed": False, "reason": "empty_export"})
            continue
        check: dict[str, Any] = {"file": fmt, "passed": True, "size_bytes": path.stat().st_size}
        if fmt == "tiff":
            with Image.open(path) as image:
                pixels = np.asarray(image.convert("L"), dtype=float)
                check.update({"width": image.width, "height": image.height, "pixel_std": float(pixels.std())})
            check["passed"] = bool(image.width >= 1000 and image.height >= 600 and pixels.std() > 1.0)
        qa["checks"].append(check)
        if not check["passed"]:
            qa["status"] = "failed"
    qa_path = output_dir / f"{figure_id}.qa.json"
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if qa["status"] != "passed":
        raise ValueError(f"图表视觉 QA 未通过：{qa_path}")
    fragment = {
        "figure_id": figure_id,
        "core_conclusion": contract["core_conclusion"],
        "evidence_chain": contract["evidence_chain"],
        "archetype": contract["archetype"],
        "source_data_ref": ref(run_dir, source),
        "script_ref": ref(run_dir, script_copy),
        "exports": {fmt: ref(run_dir, output_dir / f"{figure_id}.{fmt}") for fmt in ("svg", "pdf", "tiff")},
        "qa_ref": ref(run_dir, qa_path),
    }
    if attestation_ref is not None:
        fragment["source_data_attestation_ref"] = attestation_ref
    return fragment


def main() -> None:
    parser = argparse.ArgumentParser(description="Python 主图表生成与视觉 QA")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    try:
        result = render(Path(args.run_dir), Path(args.contract))
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
