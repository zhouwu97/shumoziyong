from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from paper_compiler_common import ROOT, load_json, relative_posix, sha256_file, validate_schema, write_json


PILOT_ID = "paper_compiler_v1_1_1"
PACKAGES_ROOT = ROOT / "capability_evidence/paper_compiler_v1_1_1/ai_pre_review_packages"
ADMIN_ROOT = PACKAGES_ROOT / "admin_only"
DEFAULT_OUTPUT = ADMIN_ROOT / "AI_PRE_REVIEW_VALIDATION_REPORT.json"
REVIEW_DIRS = {
    "reviewer_1": PACKAGES_ROOT / "reviewer_1_ai_pre_review",
    "reviewer_2": PACKAGES_ROOT / "reviewer_2_ai_pre_review",
}
EXPECTED_ZIP_HASHES = {
    "reviewer_1_ai_pre_review.zip": "26a22fb7b16dd7f0b2032be0b39cd61359d6a0c6e934f0d02d1e7f6555501dde",
    "reviewer_2_ai_pre_review.zip": "f4f5b20b47b0b367d3e0c98cf8ace35dbca7adfeee2d1855e5d01c74570d99f7",
}
ZIP_PACKAGE_DIRS = {
    "reviewer_1_ai_pre_review.zip": PACKAGES_ROOT / "reviewer_1",
    "reviewer_2_ai_pre_review.zip": PACKAGES_ROOT / "reviewer_2",
}
FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("date-time", raises=(ValueError, TypeError))
def _is_rfc3339_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ):
        return False
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.tzinfo is not None


def validate_ai_review_schema(payload: dict[str, Any]) -> None:
    schema_name = "paper_compiler_ai_pre_review.schema.json"
    schema = load_json(ROOT / "schemas" / schema_name)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        rendered = []
        for error in errors[:20]:
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            rendered.append(f"{location}: {error.message}")
        raise ValueError(f"{schema_name} 校验失败：" + "；".join(rendered))


def evidence(role: str, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "role": role,
        "path": relative_posix(path, ROOT),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def assert_completed_review(payload: dict[str, Any], reviewer_id: str) -> None:
    validate_ai_review_schema(payload)
    if payload["reviewer_id"] != reviewer_id or payload["status"] != "completed":
        raise ValueError(f"{reviewer_id} 不是完成态 AI 预评审")
    for label, version in payload["versions"].items():
        if any(value is None for value in version["hard_errors"].values()):
            raise ValueError(f"{reviewer_id}/{label} 存在未填写硬错误项")
        if any(value is None for value in version["scores"].values()):
            raise ValueError(f"{reviewer_id}/{label} 存在未填写评分项")
        if any(value is None for value in version["timing"].values()):
            raise ValueError(f"{reviewer_id}/{label} 存在未填写时间项")
    if any(value is None for value in payload["forced_comparison"].values()):
        raise ValueError(f"{reviewer_id} 强制比较未填写完整")
    if payload["source_reuse_status"] is None or payload["ai_conclusion"] is None:
        raise ValueError(f"{reviewer_id} 结论字段未填写")


def protocol_declares_order(protocol_path: Path, order: list[str]) -> bool:
    protocol = protocol_path.read_text(encoding="utf-8")
    rendered = ", ".join(order)
    return f"`{rendered}`" in protocol


def verify_returned_materials(
    reviewer_id: str,
    review_dir: Path,
    order: list[str],
    integrity: dict[str, Any],
) -> None:
    expected = integrity["material_hashes"][reviewer_id]
    for index, label in enumerate(order, start=1):
        path = review_dir / f"materials/{index:02d}_{label}.md"
        if sha256_file(path) != expected[label]:
            raise ValueError(f"{reviewer_id} 匿名材料 {label} 与管理员哈希不一致")


def verify_protected_sources(integrity: dict[str, Any]) -> None:
    protected = integrity["protected_sources_after"]
    pilot_path = ROOT / "capability_evidence/paper_compiler_v1_1_1/current/pilot_manifest.json"
    if sha256_file(pilot_path) != protected["pilot_manifest"]:
        raise ValueError("pilot_manifest 在原构建后发生变化")
    for group in ("human_reviews", "original_materials"):
        for relative, expected_hash in protected[group].items():
            path = ROOT / relative
            if not path.is_file() or sha256_file(path) != expected_hash:
                raise ValueError(f"受保护源文件发生变化：{relative}")


def derive_ai_pre_review_conclusion(reviews: dict[str, dict[str, Any]]) -> str:
    """从结构化评审字段派生保守结论，Markdown 文本不参与状态判断。"""
    priority = {
        "ai_pre_review_continue": 0,
        "ai_pre_review_inconclusive": 1,
        "ai_pre_review_revise": 2,
        "ai_pre_review_stop": 3,
    }
    conclusions = [review.get("ai_conclusion") for review in reviews.values()]
    if not conclusions or any(item not in priority for item in conclusions):
        raise ValueError("AI 预评审结构化结论缺失或非法")
    return str(max(conclusions, key=lambda item: priority[str(item)]))


def _expected_zip_members(package_dir: Path) -> dict[str, dict[str, Any]]:
    manifest_path = package_dir / "package_manifest.json"
    manifest = load_json(manifest_path)
    if manifest.get("mapping_included") is not False:
        raise ValueError(f"{package_dir.name} 包清单未声明 mapping_included=false")
    expected = {item["path"]: item for item in manifest["files"]}
    expected["package_manifest.json"] = {
        "sha256": sha256_file(manifest_path),
        "size_bytes": manifest_path.stat().st_size,
    }
    return expected


def verify_recovered_zip(
    zip_path: Path,
    expected_sha256: str,
    package_dir: Path,
) -> dict[str, Any]:
    """只读校验恢复的原始 ZIP；任何容器或成员异常均标记为 invalid。"""
    try:
        display_path = relative_posix(zip_path, ROOT)
    except ValueError:
        display_path = zip_path.resolve().as_posix()
    record: dict[str, Any] = {
        "path": display_path,
        "expected_sha256": expected_sha256,
        "actual_sha256": None,
        "exists": zip_path.is_file(),
        "status": "missing",
        "member_count": 0,
        "issues": [],
    }
    if not zip_path.is_file():
        return record

    issues: list[str] = []
    actual_sha256 = sha256_file(zip_path)
    record["actual_sha256"] = actual_sha256
    if actual_sha256 != expected_sha256:
        issues.append("ZIP SHA-256 与原构建报告不一致")
    if not zipfile.is_zipfile(zip_path):
        issues.append("文件不是合法 ZIP 容器")
        record.update({"status": "invalid", "issues": issues})
        return record

    expected = _expected_zip_members(package_dir)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            record["member_count"] = len(names)
            if len(names) != len(set(names)):
                issues.append("ZIP 包含重复成员名")
            unsafe = []
            for name in names:
                pure = PurePosixPath(name)
                if (
                    not name
                    or "\\" in name
                    or pure.is_absolute()
                    or ".." in pure.parts
                    or any(":" in part for part in pure.parts)
                ):
                    unsafe.append(name)
            if unsafe:
                issues.append("ZIP 包含路径穿越或非 POSIX 安全路径")
            if set(names) != set(expected):
                issues.append("ZIP 成员集合不符合包清单白名单")
            if archive.testzip() is not None:
                issues.append("ZIP CRC 完整性检查失败")
            forbidden_names = {
                "blind_mapping_admin.json",
                "review_keys.json",
                "deblind_mapping.json",
            }
            if any(
                forbidden_names.intersection(PurePosixPath(name).parts)
                or "admin_only" in PurePosixPath(name).parts
                for name in names
            ):
                issues.append("ZIP 包含泄盲或管理员专用文件")
            for name, expected_record in expected.items():
                if name not in names:
                    continue
                data = archive.read(name)
                if (
                    hashlib.sha256(data).hexdigest() != expected_record["sha256"]
                    or len(data) != expected_record["size_bytes"]
                ):
                    issues.append(f"ZIP 成员哈希或大小不一致：{name}")
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        issues.append(f"ZIP 读取失败：{exc}")

    record.update(
        {
            "status": "verified" if not issues else "invalid",
            "issues": issues,
        }
    )
    return record


def expected_zips_from_build_report(build_report_path: Path) -> list[dict[str, Any]]:
    text = build_report_path.read_text(encoding="utf-8")
    records = []
    for name, expected_hash in EXPECTED_ZIP_HASHES.items():
        if name not in text or expected_hash not in text:
            raise ValueError(f"原构建报告未绑定 ZIP：{name}")
        records.append(
            verify_recovered_zip(
                PACKAGES_ROOT / name,
                expected_hash,
                ZIP_PACKAGE_DIRS[name],
            )
        )
    return records


def validate_evidence(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    mapping_path = ADMIN_ROOT / "blind_mapping_admin.json"
    integrity_path = ADMIN_ROOT / "package_integrity_report.json"
    schema_path = ROOT / "schemas/paper_compiler_ai_pre_review.schema.json"
    build_report_path = PACKAGES_ROOT / "BUILD_REPORT.md"
    summary_path = ADMIN_ROOT / "AI_PRE_REVIEW_SUMMARY.md"
    pilot_path = ROOT / "capability_evidence/paper_compiler_v1_1_1/current/pilot_manifest.json"
    human_overlap_path = (
        ROOT
        / "capability_evidence/paper_compiler_v1_1_1/exploratory_ab/human_overlap_review.json"
    )

    mapping = load_json(mapping_path)
    integrity = load_json(integrity_path)
    pilot = load_json(pilot_path)
    reviews = {}
    review_paths = {}
    protocol_paths = {}
    schema_checks = []
    protocol_checks = []
    for reviewer_id, review_dir in REVIEW_DIRS.items():
        review_path = review_dir / f"{reviewer_id}_ai_pre_review.json"
        protocol_path = review_dir / "REVIEW_PROTOCOL.md"
        payload = load_json(review_path)
        assert_completed_review(payload, reviewer_id)
        reviews[reviewer_id] = payload
        review_paths[reviewer_id] = review_path
        protocol_paths[reviewer_id] = protocol_path
        schema_checks.append(f"{reviewer_id}: completed JSON 通过 AI 预评审 Schema 且无空评分项")

        order = mapping["review_orders"][reviewer_id]
        if payload["read_order"] != order or not protocol_declares_order(protocol_path, order):
            raise ValueError(f"{reviewer_id} 的 JSON、分包协议与管理员顺序不一致")
        source_protocol = PACKAGES_ROOT / reviewer_id / "REVIEW_PROTOCOL.md"
        if sha256_file(protocol_path) != sha256_file(source_protocol):
            raise ValueError(f"{reviewer_id} 回传协议与原分包协议不一致")
        verify_returned_materials(reviewer_id, review_dir, order, integrity)
        protocol_checks.append(f"{reviewer_id}: 阅读顺序和匿名材料哈希与管理员记录一致")

    if mapping["anonymous_mapping"] != {"X": "A", "Y": "C", "Z": "B"}:
        raise ValueError("解盲映射与冻结管理员记录不一致")
    if integrity["status"] != "passed" or not all(integrity["checks"].values()):
        raise ValueError("管理员原构建完整性报告不是通过状态")
    verify_protected_sources(integrity)
    if pilot["qualification_status"] != "awaiting_external_human_review":
        raise ValueError("qualification_status 被修改")
    if pilot["production_allowed"] is not False:
        raise ValueError("production_allowed 被修改")
    if load_json(human_overlap_path)["status"] != "pending":
        raise ValueError("人工原文复核状态不再是 pending")

    ai_pre_review_conclusion = derive_ai_pre_review_conclusion(reviews)
    expected_zips = expected_zips_from_build_report(build_report_path)
    zip_statuses = {item["status"] for item in expected_zips}
    if "invalid" in zip_statuses:
        zip_status = "invalid"
        overall_status = "evidence_invalid"
        zip_summary = "至少一个恢复的原始 Reviewer ZIP 未通过完整性或安全校验"
    elif zip_statuses == {"verified"}:
        zip_status = "verified"
        overall_status = "existing_evidence_and_original_zips_verified"
        zip_summary = "两个原始 Reviewer ZIP 的哈希、成员白名单和内容完整性均已复验"
    else:
        zip_status = "missing"
        overall_status = "existing_evidence_validated_zip_recheck_incomplete"
        zip_summary = "至少一个原始 Reviewer ZIP 缺失，因此容器复验尚未完成"

    indexed_paths = [
        ("reviewer_1_completed_json", review_paths["reviewer_1"]),
        ("reviewer_2_completed_json", review_paths["reviewer_2"]),
        ("reviewer_1_protocol", protocol_paths["reviewer_1"]),
        ("reviewer_2_protocol", protocol_paths["reviewer_2"]),
        ("deblinding_mapping", mapping_path),
        ("admin_integrity_report", integrity_path),
        ("ai_review_schema", schema_path),
        ("original_build_report", build_report_path),
        ("ai_pre_review_summary", summary_path),
        ("pilot_manifest", pilot_path),
        ("human_overlap_review", human_overlap_path),
    ]
    report = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_ai_pre_review_validation",
        "pilot_id": PILOT_ID,
        "overall_status": overall_status,
        "validation_command": (
            "python scripts/paper/validate_ai_pre_review_evidence.py "
            "--output capability_evidence/paper_compiler_v1_1_1/"
            "ai_pre_review_packages/admin_only/AI_PRE_REVIEW_VALIDATION_REPORT.json"
        ),
        "observed_state": {
            "qualification_status": pilot["qualification_status"],
            "production_allowed": pilot["production_allowed"],
            "ai_pre_review_conclusion": ai_pre_review_conclusion,
        },
        "components": {
            "review_schema_validation": {
                "status": "passed",
                "summary": "两份回传 JSON 通过本地 Schema，并完成字段级非空检查",
                "checks": schema_checks,
            },
            "protocol_and_mapping_validation": {
                "status": "passed",
                "summary": "两份分包协议、JSON 阅读顺序、匿名材料和解盲映射互相一致",
                "checks": [
                    *protocol_checks,
                    "解盲映射为 X=A、Y=C、Z=B",
                ],
            },
            "admin_integrity_and_source_protection": {
                "status": "passed",
                "summary": "管理员历史完整性报告有效，受保护源文件和资格状态未改变",
                "checks": [
                    "原始 A/B/C 与匿名材料哈希未改变",
                    "正式真人 reviewer JSON 哈希未改变",
                    "pilot_manifest 哈希和资格状态未改变",
                    "human_overlap_review 仍为 pending",
                ],
            },
            "original_zip_reverification": {
                "status": zip_status,
                "summary": zip_summary,
                "expected_zips": expected_zips,
            },
        },
        "evidence_index": [evidence(role, path) for role, path in indexed_paths],
        "limitations": [
            (
                "与现有文件相关的三项校验通过；原 ZIP 容器状态为 "
                f"{zip_status}"
            ),
            "AI 预评审不能替代两名外部真人评审",
            "人工原文复核仍为 pending",
            "本报告不改变 awaiting_external_human_review 或 production_allowed=false",
        ],
    }
    validate_schema(report, "paper_compiler_ai_pre_review_validation.schema.json")
    write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 AI 预评审回传结果与解盲证据链")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = validate_evidence(args.output)
    result = {
        "existing_checks_passed": 3,
        "zip_reverification": report["components"]["original_zip_reverification"]["status"],
        "overall_status": report["overall_status"],
    }
    print(json.dumps(result, ensure_ascii=False))
    return 1 if report["overall_status"] == "evidence_invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
