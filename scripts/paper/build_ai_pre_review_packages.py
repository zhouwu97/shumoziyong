from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from build_review_freeze import validate_existing_freeze
from paper_compiler_common import ROOT, load_json, relative_posix, sha256_file, validate_schema, write_json


PILOT_ID = "paper_compiler_v1_1_1"
SOURCE_ROOT = ROOT / "capability_evidence/paper_compiler_v1_1_1"
REVIEW_ROOT = SOURCE_ROOT / "exploratory_ab"
DEFAULT_OUTPUT = SOURCE_ROOT / "ai_pre_review_packages"
SOURCE_TEXT = ROOT / "tmp/pdfs/A127_clean_extract.txt"
CANONICAL_REVIEWER = "reviewer_1"
LABELS = ("X", "Y", "Z")
READ_ORDERS = {
    "reviewer_1": ("X", "Y", "Z"),
    "reviewer_2": ("Z", "X", "Y"),
}
LEAKAGE_PATTERNS = {
    "english_variant_label": r"\b[ABC]\s+version\b",
    "chinese_variant_label": r"版本\s*[ABC]\b",
    "baseline_version": r"baseline\s+version",
    "fixed_template": r"fixed\s+template",
    "argument_graph": r"argument\s+graph",
    "paragraph_plan": r"paragraph\s+plan",
    "rhetoric_card": r"rhetoric\s+card",
    "card_bundle": r"card\s+bundle",
    "template_variant": r"template\s+variant",
    "compiler_variant": r"compiler\s+variant",
    "with_cards": r"with\s+cards",
    "without_cards": r"without\s+cards",
    "abc_mapping": r"A/B/C\s+mapping",
    "anonymous_mapping": r"anonymous_mapping",
    "blind_mapping": r"blind_mapping",
    "variant_definitions": r"variant_definitions",
    "private_directory": r"(?:^|[/\\])private(?:[/\\]|$)",
    "source_variant_path": r"(?:baseline|current)[/\\]version_[abc]",
}


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")


def file_record(path: Path, base: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(base).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def source_record(role: str, path: Path) -> dict[str, Any]:
    return {
        "role": role,
        "path": relative_posix(path, ROOT),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def normalized_text_sha256(path: Path) -> str:
    normalized = path.read_text(encoding="utf-8").rstrip() + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def ensure_output_path(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    expected_parent = SOURCE_ROOT.resolve()
    if resolved.parent != expected_parent or resolved.name != "ai_pre_review_packages":
        raise ValueError(f"输出目录必须是 {DEFAULT_OUTPUT}")
    return resolved


def reset_output(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "reviewer_1",
        "reviewer_2",
        "admin_only",
        "reviewer_1_ai_pre_review.zip",
        "reviewer_2_ai_pre_review.zip",
        "BUILD_REPORT.md",
    ):
        target = (output_dir / name).resolve()
        if target.parent != output_dir.resolve():
            raise ValueError(f"拒绝清理输出目录外路径：{target}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def validate_pilot_state(pilot: dict[str, Any]) -> None:
    expected = {
        "automated_status": "passed",
        "qualification_status": "awaiting_external_human_review",
        "production_allowed": False,
    }
    actual = {key: pilot.get(key) for key in expected}
    if actual != expected:
        raise ValueError(f"试点状态不允许构建 AI 预评审包：{actual}")


def resolve_canonical_mapping() -> tuple[dict[str, str], Path, dict[str, Path]]:
    key_path = REVIEW_ROOT / "private/review_keys.json"
    keys = load_json(key_path)
    mapping = keys.get("mappings", {}).get(CANONICAL_REVIEWER)
    if not isinstance(mapping, dict) or set(mapping) != set(LABELS):
        raise ValueError("可信映射没有唯一给出 X、Y、Z")
    if set(mapping.values()) != {"A", "B", "C"}:
        raise ValueError("可信映射没有一一覆盖三个冻结版本")

    original_versions = {
        "A": SOURCE_ROOT / "baseline/version_a.md",
        "B": SOURCE_ROOT / "current/version_b.md",
        "C": SOURCE_ROOT / "current/version_c.md",
    }
    canonical_dir = REVIEW_ROOT / f"reviewer_packages/{CANONICAL_REVIEWER}"
    anonymous = {label: canonical_dir / f"version_{label}.md" for label in LABELS}
    for label, variant in mapping.items():
        if normalized_text_sha256(anonymous[label]) != normalized_text_sha256(
            original_versions[variant]
        ):
            raise ValueError(f"匿名材料 {label} 与可信映射不一致")
    return mapping, key_path, anonymous


def build_review_facts() -> dict[str, Any]:
    projection = load_json(SOURCE_ROOT / "current/paper_fact_projection.json")
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in projection["fact_bindings"]:
        by_type.setdefault(item["ref_type"], []).append(item)

    metrics = by_type["metric"]
    comparison = by_type["comparison"][0]
    formula = by_type["formula"][0]
    boundaries = by_type["boundary"]
    return {
        "schema_version": "1.0.0",
        "artifact_type": "anonymous_review_fact_view",
        "problem_scope": {
            "problem_id": projection["problem_id"],
            "subproblem_id": projection["subproblem_id"],
        },
        "metrics": [
            {
                "fact_id": f"RF-METRIC-{index:02d}",
                "description": projection["claims"][index - 1]["semantic_claim"],
                "numeric_value": item["resolved_value"],
                "source_unit": item["source_unit"],
                "display_text": item["rendered_text"],
                "display_unit": item["display"]["unit"],
                "decimal_places": item["display"]["decimal_places"],
            }
            for index, item in enumerate(metrics, start=1)
        ],
        "comparison": {
            "fact_id": "RF-COMPARISON-01",
            "reference": "超产滞销情形",
            "target": "超产折价销售情形",
            "direction": "increase",
            "numeric_value": comparison["resolved_value"],
            "display_text": comparison["rendered_text"],
            "display_unit": comparison["display"]["unit"],
            "decimal_places": comparison["display"]["decimal_places"],
        },
        "formula": {
            "fact_id": "RF-FORMULA-01",
            "expression": formula["resolved_value"],
            "display_text": formula["rendered_text"],
        },
        "boundaries": [
            {
                "fact_id": f"RF-BOUNDARY-{index:02d}",
                "text": item["rendered_text"],
            }
            for index, item in enumerate(boundaries, start=1)
        ],
        "inference_policy": {
            "strength": "bounded_inference",
            "allowed_interpretation": "只描述冻结材料、价格口径、销售规则和时限内可行方案",
            "forbidden_expansions": [
                "不得宣称全局最优",
                "不得把销售规则变化解释为求解算法改进",
                "不得把描述性对应关系扩大为因果关系",
                "不得外推到当前材料和求解条件之外",
            ],
        },
    }


def line_excerpt(path: Path, center: int, radius: int = 2) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = max(1, center - radius)
    end = min(len(lines), center + radius)
    return [(number, lines[number - 1]) for number in range(start, end + 1)]


def build_overlap_view(mapping: dict[str, str]) -> tuple[dict[str, Any], str]:
    overlap = load_json(SOURCE_ROOT / "current/rhetoric_overlap_report.json")
    generated_label = next(label for label, variant in mapping.items() if variant == "C")
    generated = overlap["generated_text"]
    source_line = generated["highest_match"]["source_line"]
    anonymous_line = generated["highest_match"]["generated_line"]
    anonymous_path = REVIEW_ROOT / f"reviewer_packages/{CANONICAL_REVIEWER}/version_{generated_label}.md"
    view = {
        "schema_version": "1.0.0",
        "artifact_type": "anonymous_overlap_review_view",
        "anonymous_version": generated_label,
        "source_id": "S1",
        "source_sha256": overlap["source"]["sha256"],
        "protocol": overlap["protocol"],
        "metrics": {
            "longest_contiguous_match": generated["longest_contiguous_match"],
            "char_ngram_overlap": generated["char_ngram_overlap"],
            "highest_match_normalized_text": generated["highest_match"]["normalized_text"],
            "source_line": source_line,
            "anonymous_line": anonymous_line,
        },
        "automatic_status": generated["automatic_status"],
        "human_review_status": overlap["human_review_status"],
        "notice": "自动结果只用于筛查，仍需独立判断是否存在原文复用风险。",
    }

    source_excerpt = line_excerpt(SOURCE_TEXT, source_line)
    anonymous_excerpt = line_excerpt(anonymous_path, anonymous_line)
    source_lines = "\n".join(f"{number}: {text}" for number, text in source_excerpt)
    anonymous_lines = "\n".join(f"{number}: {text}" for number, text in anonymous_excerpt)
    comparison = f"""# 来源对照片段

仅使用自动检查命中的最小上下文，不提供整篇来源文档。

## 来源 S1

- SHA-256：`{overlap['source']['sha256']}`
- 命中中心行：{source_line}

```text
{source_lines}
```

## 匿名文本 {generated_label}

- SHA-256：`{sha256_file(anonymous_path)}`
- 命中中心行：{anonymous_line}

```text
{anonymous_lines}
```

最高归一化连续匹配为“{generated['highest_match']['normalized_text']}”。请结合上下文从规定枚举中选择原文复核状态，不要仅凭自动通过结论作判断。
"""
    return view, comparison


def ai_review_template(reviewer_id: str, read_order: tuple[str, ...], freeze_id: str) -> dict[str, Any]:
    hard_errors = (
        "number_drift",
        "unit_drift",
        "precision_drift",
        "comparison_direction_error",
        "comparison_reference_error",
        "optimality_overclaim",
        "causal_overreach",
        "boundary_removed",
        "unsupported_conclusion",
        "cross_problem_contamination",
        "suspected_source_reuse",
    )
    score_names = (
        "result_location",
        "comparison_clarity",
        "attribution_quality",
        "boundary_awareness",
        "paragraph_coherence",
        "low_template_feel",
        "edit_readiness",
    )
    payload = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_compiler_ai_pre_review",
        "freeze_id": freeze_id,
        "pilot_id": PILOT_ID,
        "reviewer_id": reviewer_id,
        "reviewer_type": "ai_pre_review",
        "independent_review": True,
        "formal_human_review": False,
        "status": "pending",
        "read_order": list(read_order),
        "versions": {
            label: {
                "hard_errors": {name: None for name in hard_errors},
                "scores": {name: None for name in score_names},
                "timing": {
                    "time_to_find_main_result_seconds": None,
                    "time_to_understand_argument_seconds": None,
                    "estimated_edit_minutes": None,
                },
                "comments": [],
            }
            for label in LABELS
        },
        "forced_comparison": {
            "overall_ranking": None,
            "easiest_result_location": None,
            "best_attribution": None,
            "most_accurate_boundary": None,
            "closest_to_submission": None,
            "strongest_template_feel": None,
            "ranking_reason": None,
        },
        "source_reuse_status": None,
        "ai_conclusion": None,
        "completed_at": None,
        "attestation": {
            "mapping_not_inferred": None,
            "human_identity_not_claimed": None,
            "qualification_status_not_modified": None,
            "production_status_not_modified": None,
        },
    }
    validate_schema(payload, "paper_compiler_ai_pre_review.schema.json")
    return payload


def build_start_here(reviewer_id: str, file_order: list[str]) -> str:
    target = f"{reviewer_id}_ai_pre_review.json"
    sequence = " → ".join(file_order)
    return f"""# AI 预评审入口

1. 先阅读 `REVIEW_PROTOCOL.md`。
2. 再阅读 `AI_REVIEW_PROMPT.md`。
3. 严格按 `{sequence}` 顺序阅读匿名材料。
4. 同时使用 `facts/REVIEW_FACTS.json` 核对事实。
5. 使用 `source_reuse/` 内材料完成独立原文复核。
6. 最终只填写 `{target}`。

不要猜测匿名版本来源，不要读取管理员材料，不要修改匿名材料，也不要输出真人评审结论。
"""


def build_protocol(read_order: tuple[str, ...]) -> str:
    return f"""# AI 独立预评审协议

本包只用于 AI 预评审，不能替代外部真人评审。匿名材料的固定阅读顺序为 `{', '.join(read_order)}`。

每份文本必须先核对硬错误，再独立评分并记录计时。硬错误不能被语言评分抵消。三份文本全部完成后才能强制排序；不得讨论、读取其他评阅人的材料、猜测匿名来源或改写待评文本。

事实核对只能使用本包的只读事实视图。原文复核只能使用本包提供的最小对照片段与自动指标。发现问题只记录到 AI 预评审 JSON，不修改材料，也不修改项目资格状态。
"""


def build_prompt(reviewer_id: str, read_order: tuple[str, ...]) -> str:
    order = " → ".join(read_order)
    focus = (
        "更关注阅读效率、论证完整性和预计修改成本。"
        if reviewer_id == "reviewer_2"
        else "保持事实核对、论证质量与可编辑性三者同等权重。"
    )
    output_name = f"{reviewer_id}_ai_pre_review.json"
    return f"""# AI 预评审提示词

你是独立 AI 预评阅者。严格按 `{order}` 阅读，{focus}不要猜测匿名标签背后的版本来源，不要声称自己是真人。

## 执行顺序

1. 对每个版本先检查硬错误。
2. 再完成七项 1—5 分评分和三个时间字段。
3. 三份文本均完成后给出强制比较与综合排序。
4. 使用原文复核材料选择复核状态。
5. 最终只填写 `{output_name}`，不要改动其他文件。

## 硬错误检查

- 数字漂移
- 单位漂移
- 精度漂移
- 比较方向错误
- 比较参照错误
- 最优性扩大
- 因果越界
- 边界删除
- 无证据结论
- 串题
- 疑似原文复用

## 七项评分

每项只能填写 1—5 分：`result_location`、`comparison_clarity`、`attribution_quality`、`boundary_awareness`、`paragraph_coherence`、`low_template_feel`、`edit_readiness`。

## 时间字段

填写非负数：`time_to_find_main_result_seconds`、`time_to_understand_argument_seconds`、`estimated_edit_minutes`。

## 强制比较

必须填写综合排序、最容易找结果、归因解释最好、边界最准确、最接近可提交、模板感最强以及排序理由。

## 原文复核状态

只能选择：`no_concern`、`generic_academic_overlap`、`requires_revision`、`probable_source_reuse`。

## AI 结论

只能选择：`ai_pre_review_continue`、`ai_pre_review_revise`、`ai_pre_review_stop`、`ai_pre_review_inconclusive`。

AI 预评审不能替代两名外部真人评审。AI 预评审不能改变 `awaiting_external_human_review`。AI 预评审不能使 `production_allowed` 变为 `true`，也不得声称 `production_ready`。
"""


def copy_materials(package_dir: Path, anonymous: dict[str, Path], read_order: tuple[str, ...]) -> list[str]:
    names = []
    for index, label in enumerate(read_order, start=1):
        name = f"{index:02d}_{label}.md"
        target = package_dir / "materials" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(anonymous[label], target)
        names.append(name)
    return names


def create_package_manifest(package_dir: Path, reviewer_id: str, read_order: tuple[str, ...]) -> dict[str, Any]:
    files = [
        file_record(path, package_dir)
        for path in sorted(package_dir.rglob("*"))
        if path.is_file() and path.name != "package_manifest.json"
    ]
    manifest = {
        "schema_version": "1.0.0",
        "package_id": f"{reviewer_id}_ai_pre_review",
        "pilot_id": PILOT_ID,
        "reviewer_type": "ai_pre_review",
        "read_order": list(read_order),
        "files": files,
        "manifest_scope_excludes": ["package_manifest.json"],
        "mapping_included": False,
        "other_reviewer_material_included": False,
        "formal_human_review_file_modified": False,
        "status": "ready",
    }
    write_json(package_dir / "package_manifest.json", manifest)
    return manifest


def scan_package(package_dir: Path) -> dict[str, Any]:
    findings = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(package_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append({"path": relative, "pattern": "non_text_payload", "match": None})
            continue
        searchable = relative + "\n" + text
        for name, pattern in LEAKAGE_PATTERNS.items():
            match = re.search(pattern, searchable, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                findings.append({"path": relative, "pattern": name, "match": match.group(0)})
    return {"status": "passed" if not findings else "failed", "findings": findings}


def package_contains_token(package_dir: Path, token: str) -> bool:
    lowered = token.lower()
    for path in package_dir.rglob("*"):
        if not path.is_file():
            continue
        if lowered in path.relative_to(package_dir).as_posix().lower():
            return True
        try:
            if lowered in path.read_text(encoding="utf-8").lower():
                return True
        except UnicodeDecodeError:
            return True
    return False


def create_deterministic_zip(package_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(package_dir).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.flag_bits |= 0x800
            archive.writestr(info, path.read_bytes())


def verify_zip(package_dir: Path, zip_path: Path) -> dict[str, Any]:
    manifest = load_json(package_dir / "package_manifest.json")
    expected = {item["path"]: item for item in manifest["files"]}
    expected["package_manifest.json"] = file_record(package_dir / "package_manifest.json", package_dir)
    issues = []
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = set(archive.namelist())
        if names != set(expected):
            issues.append("ZIP 文件集合与包清单不一致")
        for name, record in expected.items():
            if name not in names:
                continue
            data = archive.read(name)
            digest = hashlib.sha256(data).hexdigest()
            if digest != record["sha256"] or len(data) != record["size_bytes"]:
                issues.append(f"ZIP 条目哈希或大小不一致：{name}")
        forbidden_prefixes = ("admin_only/", "reviewer_1/", "reviewer_2/")
        if any(name.startswith(forbidden_prefixes) for name in names):
            issues.append("ZIP 包含禁止的外层目录")
    return {"status": "passed" if not issues else "failed", "issues": issues}


def compare_material_hashes(output_dir: Path) -> dict[str, Any]:
    hashes: dict[str, dict[str, str]] = {}
    for reviewer_id, order in READ_ORDERS.items():
        hashes[reviewer_id] = {}
        for index, label in enumerate(order, start=1):
            path = output_dir / reviewer_id / "materials" / f"{index:02d}_{label}.md"
            hashes[reviewer_id][label] = sha256_file(path)
    checks = {
        f"anonymous_{label}_identical": hashes["reviewer_1"][label] == hashes["reviewer_2"][label]
        for label in LABELS
    }
    checks["only_read_order_differs"] = all(checks.values())
    return {"hashes": hashes, "checks": checks}


def build_admin_readme() -> str:
    return """# 管理员专用材料

本目录包含真实映射、源文件哈希与完整性报告，不得交给任何评阅者，也不得加入 Reviewer ZIP。只有在独立预评审文件锁定后，管理员才可按后续流程解盲。
"""


def build_report_text(
    pilot: dict[str, Any],
    mapping_source: Path,
    zip_records: dict[str, dict[str, Any]],
    leakage: dict[str, Any],
    integrity: dict[str, Any],
    output_dir: Path,
) -> str:
    return f"""# AI 预评审材料包构建报告

## 当前试点状态

```text
automated_status: {pilot['automated_status']}
qualification_status: {pilot['qualification_status']}
production_allowed: {str(pilot['production_allowed']).lower()}
```

## 发现的源文件

- 匿名材料：冻结的 X、Y、Z Markdown 文件
- 映射来源：`{relative_posix(mapping_source, ROOT)}`
- 事实材料：去标识的只读事实视图
- 重合材料：自动指标与最小来源对照片段
- 评审模板：独立 AI 预评审 JSON，不覆盖真人文件

## 打包结果

- Reviewer 1：`{zip_records['reviewer_1']['path']}`，SHA-256 `{zip_records['reviewer_1']['sha256']}`
- Reviewer 2：`{zip_records['reviewer_2']['path']}`，SHA-256 `{zip_records['reviewer_2']['sha256']}`
- Admin：`{relative_posix(output_dir / 'admin_only', ROOT)}`
- 泄盲扫描：Reviewer 1 `{leakage['reviewer_1']['status']}`；Reviewer 2 `{leakage['reviewer_2']['status']}`
- 完整性检查：`{integrity['status']}`

## 未解决事项

- 人工原文复核仍为 pending。
- 正式真人评审仍未完成。
- AI 结果不得写入真人 Reviewer 文件。
- `qualification_status` 必须保持 `awaiting_external_human_review`。
- `production_allowed` 必须保持 `false`。

## 最终结论

packages_ready_for_ai_pre_review
"""


def build_packages(output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output_dir = ensure_output_path(output_dir)
    pilot_path = SOURCE_ROOT / "current/pilot_manifest.json"
    human_paths = [REVIEW_ROOT / "reviewer_1.json", REVIEW_ROOT / "reviewer_2.json"]
    original_paths = [
        SOURCE_ROOT / "baseline/version_a.md",
        SOURCE_ROOT / "current/version_b.md",
        SOURCE_ROOT / "current/version_c.md",
        *[REVIEW_ROOT / f"reviewer_packages/{CANONICAL_REVIEWER}/version_{label}.md" for label in LABELS],
    ]
    protected_before = {
        "pilot_manifest": sha256_file(pilot_path),
        "human_reviews": {relative_posix(path, ROOT): sha256_file(path) for path in human_paths},
        "original_materials": {relative_posix(path, ROOT): sha256_file(path) for path in original_paths},
    }

    pilot = load_json(pilot_path)
    validate_pilot_state(pilot)
    freeze = validate_existing_freeze(REVIEW_ROOT / "review_freeze_manifest.json")
    mapping, mapping_source, anonymous = resolve_canonical_mapping()
    if pilot["review_freeze"]["sha256"] != sha256_file(REVIEW_ROOT / "review_freeze_manifest.json"):
        raise ValueError("pilot_manifest 引用的冻结清单哈希不一致")
    if freeze["review_started_at"] is not None:
        raise ValueError("冻结清单显示正式评审已经开始，拒绝创建预评审包")
    if not SOURCE_TEXT.is_file():
        raise ValueError("原文复核来源文本缺失")

    reset_output(output_dir)
    admin_dir = output_dir / "admin_only"
    admin_dir.mkdir(parents=True, exist_ok=True)
    write_text(admin_dir / "README_ADMIN.md", build_admin_readme())

    mapping_admin = {
        "schema_version": "1.0.0",
        "pilot_id": PILOT_ID,
        "mapping_source": {
            "path": relative_posix(mapping_source, ROOT),
            "sha256": sha256_file(mapping_source),
            "mapping_key": CANONICAL_REVIEWER,
        },
        "anonymous_mapping": mapping,
        "variant_definitions": {
            "A": "现有固定模板",
            "B": "argument graph + paragraph plan，不加载表达卡片",
            "C": "argument graph + paragraph plan + 表达卡片",
        },
        "review_orders": {key: list(value) for key, value in READ_ORDERS.items()},
        "reviewer_packages_must_not_contain_mapping": True,
    }
    write_json(admin_dir / "blind_mapping_admin.json", mapping_admin)

    source_paths = {
        "version_a": SOURCE_ROOT / "baseline/version_a.md",
        "version_b": SOURCE_ROOT / "current/version_b.md",
        "version_c": SOURCE_ROOT / "current/version_c.md",
        "canonical_x": anonymous["X"],
        "canonical_y": anonymous["Y"],
        "canonical_z": anonymous["Z"],
        "mapping_source": mapping_source,
        "fact_projection": SOURCE_ROOT / "current/paper_fact_projection.json",
        "automatic_overlap": SOURCE_ROOT / "current/rhetoric_overlap_report.json",
        "overlap_source": SOURCE_TEXT,
        "version_source_lock": SOURCE_ROOT / "baseline/baseline_lock.json",
        "version_b_record": SOURCE_ROOT / "baseline/plan_b.json",
        "version_c_record": SOURCE_ROOT / "baseline/plan_c.json",
        "generation_bundle_record": SOURCE_ROOT / "current/rhetoric_bundle.json",
        "human_reviewer_1": human_paths[0],
        "human_reviewer_2": human_paths[1],
        "pilot_manifest": pilot_path,
    }
    source_manifest = {
        "schema_version": "1.0.0",
        "pilot_id": PILOT_ID,
        "mapping_resolved": True,
        "mapping_resolution": "从冻结私有映射的 reviewer_1 键唯一解析，并用原始版本哈希复核",
        "files": [source_record(role, path) for role, path in source_paths.items()],
    }
    write_json(admin_dir / "source_file_manifest.json", source_manifest)

    facts = build_review_facts()
    overlap_view, source_comparison = build_overlap_view(mapping)
    package_manifests = {}
    for reviewer_id, read_order in READ_ORDERS.items():
        package_dir = output_dir / reviewer_id
        material_names = copy_materials(package_dir, anonymous, read_order)
        write_text(package_dir / "START_HERE.md", build_start_here(reviewer_id, material_names))
        write_text(package_dir / "AI_REVIEW_PROMPT.md", build_prompt(reviewer_id, read_order))
        write_text(package_dir / "REVIEW_PROTOCOL.md", build_protocol(read_order))
        write_json(
            package_dir / f"{reviewer_id}_ai_pre_review.json",
            ai_review_template(reviewer_id, read_order, freeze["freeze_id"]),
        )
        write_json(package_dir / "facts/REVIEW_FACTS.json", facts)
        write_json(package_dir / "source_reuse/AUTOMATED_OVERLAP_REPORT.json", overlap_view)
        write_text(package_dir / "source_reuse/SOURCE_COMPARISON_EXCERPTS.md", source_comparison)
        package_manifests[reviewer_id] = create_package_manifest(
            package_dir, reviewer_id, read_order
        )

    leakage = {reviewer_id: scan_package(output_dir / reviewer_id) for reviewer_id in READ_ORDERS}
    write_json(admin_dir / "leakage_scan_report.json", leakage)
    if any(result["status"] != "passed" for result in leakage.values()):
        raise ValueError("泄盲扫描失败，未生成 ZIP")

    comparison = compare_material_hashes(output_dir)
    protected_after = {
        "pilot_manifest": sha256_file(pilot_path),
        "human_reviews": {relative_posix(path, ROOT): sha256_file(path) for path in human_paths},
        "original_materials": {relative_posix(path, ROOT): sha256_file(path) for path in original_paths},
    }
    checks = {
        **comparison["checks"],
        "reviewer_1_mapping_absent": package_manifests["reviewer_1"]["mapping_included"] is False,
        "reviewer_2_mapping_absent": package_manifests["reviewer_2"]["mapping_included"] is False,
        "reviewer_1_other_material_absent": not package_contains_token(
            output_dir / "reviewer_1", "reviewer_2"
        ),
        "reviewer_2_other_material_absent": not package_contains_token(
            output_dir / "reviewer_2", "reviewer_1"
        ),
        "human_review_files_unchanged": protected_before["human_reviews"]
        == protected_after["human_reviews"],
        "source_files_unchanged": protected_before["original_materials"]
        == protected_after["original_materials"],
        "pilot_status_unchanged": protected_before["pilot_manifest"]
        == protected_after["pilot_manifest"],
    }
    if not all(checks.values()):
        integrity = {"status": "failed", "checks": checks, "material_hashes": comparison["hashes"]}
        write_json(admin_dir / "package_integrity_report.json", integrity)
        raise ValueError("包完整性检查失败，未生成 ZIP")

    zip_records: dict[str, dict[str, Any]] = {}
    zip_checks = {}
    for reviewer_id in READ_ORDERS:
        zip_path = output_dir / f"{reviewer_id}_ai_pre_review.zip"
        create_deterministic_zip(output_dir / reviewer_id, zip_path)
        verification = verify_zip(output_dir / reviewer_id, zip_path)
        zip_checks[reviewer_id] = verification
        zip_records[reviewer_id] = {
            "path": relative_posix(zip_path, ROOT),
            "sha256": sha256_file(zip_path),
            "size_bytes": zip_path.stat().st_size,
        }
    checks["reviewer_1_zip_verified"] = zip_checks["reviewer_1"]["status"] == "passed"
    checks["reviewer_2_zip_verified"] = zip_checks["reviewer_2"]["status"] == "passed"
    integrity = {
        "schema_version": "1.0.0",
        "pilot_id": PILOT_ID,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "material_hashes": comparison["hashes"],
        "zip_verification": zip_checks,
        "protected_sources_before": protected_before,
        "protected_sources_after": protected_after,
    }
    write_json(admin_dir / "package_integrity_report.json", integrity)
    if integrity["status"] != "passed":
        for record in zip_records.values():
            (ROOT / record["path"]).unlink(missing_ok=True)
        raise ValueError("ZIP 完整性检查失败")

    write_text(
        output_dir / "BUILD_REPORT.md",
        build_report_text(pilot, mapping_source, zip_records, leakage, integrity, output_dir),
    )
    return {
        "status": "packages_ready_for_ai_pre_review",
        "mapping_resolved": True,
        "zip_records": zip_records,
        "leakage": leakage,
        "integrity": integrity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建两套隔离的 AI 预评审材料包")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_packages(args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
