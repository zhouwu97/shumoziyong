from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iter_file_records(manifest: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for key in ("runtime_profile_state", "patch_index", "base"):
        if manifest.get(key):
            records.append(manifest[key])
    for key in ("plugins", "patches", "checklists", "other_files"):
        records.extend(manifest.get(key, []))
    return records


def check_manifest(manifest_path: Path, pack_path: Path) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for record in iter_file_records(manifest):
        relative_path = record["path"]
        path = ROOT / relative_path
        if not path.is_file():
            errors.append(f"manifest 文件不存在：{relative_path}")
        elif sha256(path) != record["sha256"]:
            errors.append(f"manifest 哈希不一致：{relative_path}")

    if not pack_path.is_file():
        errors.append(f"运行包不存在：{pack_path.relative_to(ROOT)}")
    elif sha256(pack_path) != manifest.get("runtime_pack_sha256"):
        errors.append("运行包哈希与 manifest 不一致")

    export_flags = manifest.get("export_flags", {})
    intended_candidate_ids = set(export_flags.get("candidate_patches", []))
    # 默认运行包（无显式 --candidate-patch）不得包含任何 candidate patch。
    if not intended_candidate_ids:
        candidates = [patch["patch_id"] for patch in manifest.get("patches", []) if patch["status"] == "review_ready"]
        if candidates:
            errors.append(f"默认运行包错误包含 candidate patch：{', '.join(candidates)}")
    else:
        # 显式实验：出现的 candidate 必须都在声明的 candidate_experiment.patch_ids 中。
        declared = set(manifest.get("candidate_experiment", {}).get("patch_ids", []))
        if declared != intended_candidate_ids:
            errors.append("export_flags.candidate_patches 与 candidate_experiment.patch_ids 不一致")
        actual_candidates = {patch["patch_id"] for patch in manifest.get("patches", []) if patch["status"] == "review_ready"}
        if not actual_candidates.issubset(intended_candidate_ids):
            errors.append(f"运行包出现未声明的 candidate patch：{', '.join(sorted(actual_candidates - intended_candidate_ids))}")
    # candidate_experiment.patch_ids 必须真的出现在 patches 中（否则声明了却没导入）
    if manifest.get("candidate_experiment", {}).get("enabled"):
        actual_ids = {patch["patch_id"] for patch in manifest.get("patches", [])}
        missing = set(manifest["candidate_experiment"]["patch_ids"]) - actual_ids
        if missing:
            errors.append(f"声明导入但运行包缺失的 candidate patch：{', '.join(sorted(missing))}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 runtime manifest 路径、哈希和 candidate 边界。")
    parser.add_argument("--manifest", default="export/cumcm_runtime_pack.manifest.json")
    parser.add_argument("--pack", default="export/cumcm_runtime_pack.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors = check_manifest(ROOT / args.manifest, ROOT / args.pack)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        raise SystemExit(1)
    print("[PASS] runtime manifest 路径、哈希和 patch 状态边界")


if __name__ == "__main__":
    main()
