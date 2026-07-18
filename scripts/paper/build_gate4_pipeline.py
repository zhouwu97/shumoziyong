"""从唯一 eligible Formal Result 编排两阶段 Gate 4 论文生产链。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from atomic_io import atomic_write_bytes  # noqa: E402
from formal_result.verifier import verify_formal_result_bundle  # noqa: E402
from run_workflow import (  # noqa: E402
    PAPER_CANDIDATE_STATUS,
    PAPER_PIPELINE_CONTRACT_VERSION,
    replay_transition_log,
    verify_gate_artifacts,
    write_gate_artifact_manifest,
)

try:
    from .check_claim_bindings import check_bindings
    from .check_humanization_diff import check_humanization_diff
    from .check_narrative import build_narrative_report
    from .external_precheck import run_external_precheck
    from .gate4_candidate import build_candidate_manifest, sha256_file
    from .gate_f_status import build_gate_f_status
    from .paper_content_quality import (
        build_content_delta_report,
        build_substantive_completeness_report,
        CONTRACT_RESOLUTION_VERSION,
        contract_source_hashes,
        contract_sha256,
        load_contract,
    )
    from .paper_production_manifest import build_paper_production_manifest
    from .rasterize_pdf import rasterize_pdf
    from .render_submission import build_file_manifest, render_submission
    from .verify_submission import verify_submission
except ImportError:  # pragma: no cover - 允许直接执行脚本。
    from check_claim_bindings import check_bindings
    from check_humanization_diff import check_humanization_diff
    from check_narrative import build_narrative_report
    from external_precheck import run_external_precheck
    from gate4_candidate import build_candidate_manifest, sha256_file
    from gate_f_status import build_gate_f_status
    from paper_content_quality import (
        build_content_delta_report,
        build_substantive_completeness_report,
        CONTRACT_RESOLUTION_VERSION,
        contract_source_hashes,
        contract_sha256,
        load_contract,
    )
    from paper_production_manifest import build_paper_production_manifest
    from rasterize_pdf import rasterize_pdf
    from render_submission import build_file_manifest, render_submission
    from verify_submission import verify_submission


STATE_FILENAME = "paper_gate4_pipeline_state.json"
STATE_SCHEMA = "paper_gate4_pipeline_state.schema.json"
DEFAULT_PROFILE_PATH = ROOT / "paper_profiles" / "cumcm_academic_v1.json"
DEFAULT_TEMPLATE_DIR = ROOT / "paper_templates" / "cumcm_typst"
DEFAULT_RENDERER_FALLBACK = Path.home() / "AppData/Local/Microsoft/WinGet/Links/typst.exe"
MODEL_ROUTE_FILES = {"model_route.json", "model_route_v2_1.json", "model_route_v3.json"}


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少 {label}：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} 无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = (json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload)


def validate_schema(value: dict[str, Any], schema_name: str, label: str) -> None:
    schema = load_json_object(ROOT / "schemas" / schema_name, f"Schema {schema_name}")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError(f"{label} 不符合 Schema：{details}")


def _run_relative(run_dir: Path, path: Path, label: str) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(run_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} 必须位于当前 Run 内：{resolved}") from exc


def _recorded_path(run_dir: Path, relative: str, label: str) -> Path:
    path = (run_dir / Path(relative)).resolve()
    try:
        path.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} 越出当前 Run") from exc
    return path


def _binding(run_dir: Path) -> dict[str, str]:
    run = load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    runtime = load_json_object(
        run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json"
    )
    binding = {
        "run_id": str(run["run_id"]),
        "problem_id": str(run["problem_id"]),
        "profile": str(run["profile"]),
        "runtime_version": str(run["runtime_version"]),
        "runtime_pack_sha256": str(runtime["runtime_pack_sha256"]),
    }
    if run.get("runtime_pack_sha256") != binding["runtime_pack_sha256"]:
        raise ValueError("Run Manifest 与 Runtime Pack 的 SHA-256 绑定不一致")
    if run.get("paper_pipeline_contract_version") != PAPER_PIPELINE_CONTRACT_VERSION:
        raise ValueError("当前 Run 未启用 paper pipeline contract 1.0.0")
    return binding


def _require_gate_4_state(run_dir: Path) -> None:
    if (run_dir / "gate_artifacts" / "gate_4.manifest.json").exists():
        raise ValueError("Gate 4 已生成哈希清单，禁止原地重建论文证据")
    state = replay_transition_log(run_dir)
    if state.get("lifecycle_status") != "active":
        raise ValueError("只有 active Run 可以构建 Gate 4 论文候选")
    if state.get("current_gate") != 4 or 3 not in state.get("completed_gates", []):
        raise ValueError("编排器要求 Gate 3 已通过且当前位于 Gate 4")


def require_active_formal_result(run_dir: Path) -> dict[str, Any]:
    run = load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if run.get("formal_result_policy") != "required_v1":
        raise ValueError("Gate 4 论文编排只接受 required_v1 Formal Result Run")
    envelopes = sorted(run_dir.glob("formal_results/*/formal_result_envelope.json"))
    if len(envelopes) != 1:
        raise ValueError(f"当前 Run 必须且只能有一个 Formal Result，实际 {len(envelopes)}")
    summary = verify_formal_result_bundle(run_dir, envelopes[0])
    if summary.get("formal_result_activation_status") != "run_execution_verified":
        raise ValueError("Formal Result 尚未达到 run_execution_verified")
    if summary.get("formal_result_eligible") is not True:
        raise ValueError("Formal Result 不具备论文生产资格")
    return summary


def _require_claims_from_formal_result(
    run_dir: Path,
    claim_map: Mapping[str, Any],
    formal_summary: Mapping[str, Any],
) -> None:
    domain_path = Path(str(formal_summary["domain_manifest_path"]))
    domain = load_json_object(domain_path, "Formal Result Domain Manifest")
    output_files = domain.get("output_file_set")
    if not isinstance(output_files, list) or not output_files:
        raise ValueError("Formal Result Domain Manifest 缺少 output_file_set")
    formal_root = Path(str(formal_summary["envelope_path"])).parent
    primary_result = formal_root / str(output_files[0])
    expected_source = _run_relative(run_dir, primary_result, "Formal Result 主结果")
    claims = claim_map.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("paper_claim_map 缺少 Claim")
    for claim in claims:
        claim_id = str(claim.get("claim_id", "<unknown>")) if isinstance(claim, dict) else "<invalid>"
        if not isinstance(claim, dict) or claim.get("source_file") != expected_source:
            raise ValueError(f"{claim_id} 未直接绑定 eligible Formal Result 主结果")
        required = {"json_pointer", "raw_value", "display_value", "rounding_rule"}
        if not required.issubset(claim):
            raise ValueError(f"{claim_id} 缺少可复算的 Formal Result Claim 字段")


def _validate_model_consistency(
    run_dir: Path,
    report_path: Path,
    source_entry: Path,
) -> dict[str, Any]:
    report = load_json_object(report_path, "模型—正文一致性报告")
    validate_schema(
        report,
        "model_text_consistency_report.schema.json",
        "模型—正文一致性报告",
    )
    if report.get("status") != "passed":
        raise ValueError("模型—正文一致性报告未通过")
    if report.get("paper_source_sha256") != sha256_file(source_entry):
        raise ValueError("模型—正文一致性报告未绑定当前论文入口")
    model_route = str(report.get("model_route", ""))
    if model_route not in MODEL_ROUTE_FILES:
        raise ValueError("模型—正文一致性报告绑定了不受支持的模型路线文件")
    for filename, hash_field in (
        (model_route, "model_route_sha256"),
        ("result_report.json", "result_report_sha256"),
    ):
        target = run_dir / filename
        if not target.is_file() or report.get(hash_field) != sha256_file(target):
            raise ValueError(f"模型—正文一致性报告的 {hash_field} 与当前 Run 不一致")
    target = run_dir / "model_text_consistency_report.json"
    if report_path.resolve() != target.resolve():
        atomic_write_bytes(target, report_path.read_bytes())
    return report


def _template_selection(
    profile_path: Path,
    template_dir: Path,
    renderer_id: str,
) -> dict[str, Any]:
    profile = load_json_object(profile_path, "论文 Profile")
    template = load_json_object(template_dir / "template.json", "论文模板 Manifest")
    validate_schema(profile, "paper_profile.schema.json", "论文 Profile")
    template_id = str(template.get("template_id", ""))
    approved = {
        (str(item.get("id")), str(item.get("template_id")))
        for item in profile.get("approved_renderers", [])
        if isinstance(item, dict)
    }
    if (renderer_id, template_id) not in approved:
        raise ValueError("论文 Profile 未批准当前 renderer/template 组合")
    files = build_file_manifest(template_dir)
    tree_sha = hashlib.sha256(
        json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    selection = {
        "schema_version": "template_selection_v1",
        "logical_key": f"{profile['language']}/{profile['competition_family']}",
        "selection_source": "runtime_profile",
        "template_id": template_id,
        "engine": renderer_id,
        "renderer_id": renderer_id,
        "entry": str(template["entry"]),
        "source_dir": str(template_dir.resolve()),
        "source_tree_sha256": tree_sha,
        "fallback_used": False,
        "overlay_id": "windows_template_overlay_v1",
        "upstream_default_overridden": True,
    }
    validate_schema(selection, "template_selection.schema.json", "模板选择")
    return selection


def _renderer_executable(explicit: str | None, renderer_id: str) -> str:
    if explicit:
        return explicit
    detected = shutil.which(renderer_id)
    if detected:
        return detected
    if renderer_id == "typst" and DEFAULT_RENDERER_FALLBACK.is_file():
        return str(DEFAULT_RENDERER_FALLBACK)
    raise FileNotFoundError(f"未找到 {renderer_id} renderer")


def prepare_pipeline(
    *,
    run_dir: Path,
    source_dir: Path,
    source_entry: Path,
    narrative_input_path: Path,
    model_consistency_path: Path,
    humanization_source_path: Path | None = None,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    template_dir: Path = DEFAULT_TEMPLATE_DIR,
    renderer_id: str = "typst",
    renderer_executable: str | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    _require_gate_4_state(run_dir)
    binding = _binding(run_dir)
    formal = require_active_formal_result(run_dir)
    source_dir = source_dir.resolve()
    _run_relative(run_dir, source_dir, "论文源稿目录")
    entry = (source_dir / source_entry).resolve()
    _run_relative(run_dir, entry, "论文入口")
    if not entry.is_file():
        raise FileNotFoundError(f"论文入口不存在：{entry}")
    narrative_input_path = narrative_input_path.resolve()
    model_consistency_path = model_consistency_path.resolve()
    _run_relative(run_dir, narrative_input_path, "论文叙事输入")
    _run_relative(run_dir, model_consistency_path, "模型—正文一致性报告")
    human_source = (humanization_source_path or entry).resolve()
    _run_relative(run_dir, human_source, "Humanizer 原稿")

    claim_map_path = run_dir / "paper_claim_map.json"
    claim_map = load_json_object(claim_map_path, "paper_claim_map.json")
    _require_claims_from_formal_result(run_dir, claim_map, formal)

    precheck = run_external_precheck(
        paper_root=source_dir,
        report_path=run_dir / "paper_external_precheck_report.json",
        suggestions_path=run_dir / "suggested_repairs.json",
    )
    if precheck.get("status") != "passed":
        raise ValueError(f"论文外部兼容预检未通过：{precheck.get('status')}")

    narrative_input = load_json_object(narrative_input_path, "论文叙事输入")
    narrative = build_narrative_report(
        paper_root=source_dir,
        narrative_input=narrative_input,
        claim_map=claim_map,
        claim_map_path=claim_map_path,
        binding=binding,
    )
    write_json(run_dir / "paper_narrative_report.json", narrative)
    if narrative.get("status") != "passed":
        raise ValueError("论文叙事合同检查未通过")

    humanization = check_humanization_diff(human_source, entry)
    write_json(run_dir / "paper_humanization_report.json", humanization)
    if humanization.get("status") != "passed":
        raise ValueError("Humanizer 保护字段发生漂移")

    claim_report = check_bindings(claim_map_path, entry, run_dir)
    if claim_report.get("passed") is not True:
        issues = claim_report.get("issues", [])
        raise ValueError(f"论文 Claim 与 Formal Result 数字绑定失败：{len(issues)} 项")
    _validate_model_consistency(run_dir, model_consistency_path, entry)

    selection = _template_selection(profile_path.resolve(), template_dir.resolve(), renderer_id)
    write_json(run_dir / "template_selection.json", selection)
    attestation = render_submission(
        profile_path=profile_path.resolve(),
        template_dir=template_dir.resolve(),
        source_dir=source_dir,
        source_entry=source_entry,
        output_pdf=run_dir / "submission.pdf",
        attestation_path=run_dir / "paper_render_attestation.json",
        renderer_id=renderer_id,
        renderer_executable=_renderer_executable(renderer_executable, renderer_id),
    )
    raster = rasterize_pdf(run_dir / "submission.pdf", run_dir / "paper_pages", dpi=160)
    write_json(run_dir / "paper_raster_report.json", raster)

    envelope_path = Path(str(formal["envelope_path"]))
    state = {
        "schema_version": "1.0.0",
        "status": "awaiting_visual_review",
        "binding": binding,
        "formal_result": {
            "formal_result_id": str(formal["formal_result_id"]),
            "domain": str(formal["formal_result_domain"]),
            "envelope_path": _run_relative(run_dir, envelope_path, "Formal Result Envelope"),
            "envelope_sha256": str(formal["envelope_file_sha256"]),
        },
        "source": {
            "directory": _run_relative(run_dir, source_dir, "论文源稿目录"),
            "entry": source_entry.as_posix(),
            "entry_sha256": sha256_file(entry),
        },
        "inputs": {
            "narrative_input_path": _run_relative(
                run_dir, narrative_input_path, "论文叙事输入"
            ),
            "narrative_input_sha256": sha256_file(narrative_input_path),
            "humanization_source_path": _run_relative(
                run_dir, human_source, "Humanizer 原稿"
            ),
            "humanization_source_sha256": sha256_file(human_source),
            "model_consistency_sha256": sha256_file(
                run_dir / "model_text_consistency_report.json"
            ),
        },
        "paper_profile": {
            "path": str(profile_path.resolve()),
            "sha256": sha256_file(profile_path.resolve()),
        },
        "template": {
            "directory": str(template_dir.resolve()),
            "selection_sha256": sha256_file(run_dir / "template_selection.json"),
            "tree_sha256": str(selection["source_tree_sha256"]),
        },
        "render": {
            "pdf_path": "submission.pdf",
            "pdf_sha256": str(attestation["output_pdf_sha256"]),
            "attestation_sha256": sha256_file(run_dir / "paper_render_attestation.json"),
            "raster_report_path": "paper_raster_report.json",
            "raster_report_sha256": sha256_file(run_dir / "paper_raster_report.json"),
            "pages_directory": "paper_pages",
            "page_count": int(raster["page_count"]),
        },
    }
    validate_schema(state, STATE_SCHEMA, STATE_FILENAME)
    write_json(run_dir / STATE_FILENAME, state)
    return state


def _verify_prepared_state(run_dir: Path, state: Mapping[str, Any]) -> dict[str, Path]:
    formal = require_active_formal_result(run_dir)
    if formal.get("formal_result_id") != state["formal_result"]["formal_result_id"]:
        raise ValueError("prepare 后 active Formal Result 已变化")
    envelope = _recorded_path(
        run_dir, str(state["formal_result"]["envelope_path"]), "Formal Result Envelope"
    )
    if sha256_file(envelope) != state["formal_result"]["envelope_sha256"]:
        raise ValueError("prepare 后 Formal Result Envelope 已漂移")
    source_dir = _recorded_path(run_dir, str(state["source"]["directory"]), "论文源稿目录")
    entry = (source_dir / str(state["source"]["entry"])).resolve()
    if sha256_file(entry) != state["source"]["entry_sha256"]:
        raise ValueError("prepare 后论文入口已漂移")
    pdf = _recorded_path(run_dir, str(state["render"]["pdf_path"]), "submission.pdf")
    raster_path = _recorded_path(
        run_dir, str(state["render"]["raster_report_path"]), "栅格报告"
    )
    if sha256_file(pdf) != state["render"]["pdf_sha256"]:
        raise ValueError("prepare 后 submission.pdf 已漂移")
    if sha256_file(raster_path) != state["render"]["raster_report_sha256"]:
        raise ValueError("prepare 后栅格报告已漂移")
    raster = load_json_object(raster_path, "论文栅格报告")
    if raster.get("pdf_sha256") != state["render"]["pdf_sha256"]:
        raise ValueError("栅格报告未绑定当前 submission.pdf")
    pages_dir = _recorded_path(
        run_dir, str(state["render"]["pages_directory"]), "论文逐页图片目录"
    )
    expected_pages = int(state["render"]["page_count"])
    records = raster.get("pages")
    if not isinstance(records, list) or len(records) != expected_pages:
        raise ValueError("栅格报告页数与 prepare 状态不一致")
    for record in records:
        page = Path(str(record.get("file", ""))).resolve()
        if not page.is_file() or page.parent != pages_dir or sha256_file(page) != record.get("sha256"):
            raise ValueError("逐页栅格图缺失或哈希漂移")
    profile = Path(str(state["paper_profile"]["path"])).resolve()
    template = Path(str(state["template"]["directory"])).resolve()
    if sha256_file(profile) != state["paper_profile"]["sha256"]:
        raise ValueError("论文 Profile 已漂移")
    if sha256_file(run_dir / "template_selection.json") != state["template"]["selection_sha256"]:
        raise ValueError("模板选择记录已漂移")
    if sha256_file(run_dir / "model_text_consistency_report.json") != state["inputs"]["model_consistency_sha256"]:
        raise ValueError("模型—正文一致性报告已漂移")
    return {
        "source_dir": source_dir,
        "entry": entry,
        "pdf": pdf,
        "profile": profile,
        "template": template,
    }


def _validate_visual_review(path: Path, *, pdf_sha256: str, page_count: int) -> dict[str, Any]:
    review = load_json_object(path, "逐页视觉审核记录")
    validate_schema(review, "paper_visual_review.schema.json", "逐页视觉审核记录")
    if review.get("pdf_sha256") != pdf_sha256:
        raise ValueError("逐页视觉审核未绑定 prepare 阶段 PDF")
    if review.get("page_count") != page_count:
        raise ValueError("逐页视觉审核页数与 prepare 阶段不一致")
    if set(review.get("reviewed_pages", [])) != set(range(1, page_count + 1)):
        raise ValueError("逐页视觉审核未覆盖全部页面")
    if review.get("status") != "passed":
        raise ValueError("逐页视觉审核未通过")
    if any(
        item.get("severity") in {"P0", "P1"} and item.get("status") == "open"
        for item in review.get("issues", [])
    ):
        raise ValueError("逐页视觉审核仍有未关闭的 P0/P1 问题")
    return review


def _run_content_quality_if_bound(run_dir: Path, binding: Mapping[str, str]) -> dict[str, Any] | None:
    """对新 Run 强制执行 Gate F2；历史兼容必须由显式政策声明。"""
    contract_path = run_dir / "paper_content_contract.yaml"
    run_manifest = (
        load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
        if (run_dir / "run_manifest.json").is_file()
        else {}
    )
    legacy_policy = bool(run_manifest.get("legacy_paper_content_policy", False)) and run_manifest.get(
        "paper_pipeline_contract_version"
    ) is None
    if not contract_path.is_file():
        if legacy_policy:
            return None
        raise ValueError("新 Run 缺少 paper_content_contract.yaml；只有显式 legacy_paper_content_policy=true 才可跳过 Gate F2")
    contract = load_contract(contract_path)
    declared_id = run_manifest.get("paper_content_contract_id")
    declared_sha = run_manifest.get("paper_content_contract_sha256")
    actual_sha = contract_sha256(contract)
    actual_source_hashes = contract_source_hashes(contract_path)
    if declared_id is not None and declared_id != contract.get("contract_id"):
        raise ValueError("run_manifest.paper_content_contract_id 与合同不一致")
    if declared_sha is not None and declared_sha != actual_sha:
        raise ValueError("run_manifest.paper_content_contract_sha256 与合同不一致")
    if run_manifest.get("paper_content_contract_resolution_version") not in (None, CONTRACT_RESOLUTION_VERSION):
        raise ValueError("合同解析版本不受支持")
    if run_manifest.get("paper_content_contract_merged_sha256") not in (None, actual_sha):
        raise ValueError("run_manifest.paper_content_contract_merged_sha256 与合并合同不一致")
    if run_manifest.get("paper_content_contract_source_hashes") not in (None, actual_source_hashes):
        raise ValueError("run_manifest.paper_content_contract_source_hashes 与合同继承链不一致")
    registry_path = run_dir / "paper_evidence_role_registry.json"
    if not registry_path.is_file():
        raise ValueError("已绑定 paper_content_contract.yaml，但缺少 paper_evidence_role_registry.json")
    registry = load_json_object(registry_path, "paper_evidence_role_registry.json")
    if registry.get("run_id") != binding["run_id"] or registry.get("problem_id") != binding["problem_id"]:
        raise ValueError("Evidence Role Registry 与当前 Run 身份不一致")
    claim_map = load_json_object(run_dir / "paper_claim_map.json", "paper_claim_map.json")
    claim_ids = {
        str(item.get("claim_id"))
        for item in claim_map.get("claims", [])
        if isinstance(item, Mapping) and item.get("claim_id")
    }
    report = build_substantive_completeness_report(
        contract_path,
        registry_path,
        base_dir=run_dir,
        claim_ids=claim_ids,
        claim_map=claim_map,
    )
    write_json(run_dir / "paper_substantive_completeness_report.json", report)
    before_registry = run_dir / "before_paper_evidence_role_registry.json"
    delta = build_content_delta_report(
        registry_path,
        before_registry_path=before_registry if before_registry.is_file() else None,
        after_completeness_report_path=run_dir / "paper_substantive_completeness_report.json",
    )
    write_json(run_dir / "paper_content_delta_report.json", delta)
    gate_f = build_gate_f_status(
        f1_passed=True,
        completeness_report=report,
        f3_status="pending",
        completeness_report_path=run_dir / "paper_substantive_completeness_report.json",
    )
    write_json(run_dir / "paper_gate_f_status.json", gate_f)
    return gate_f


def _write_internal_content_repair_candidate(run_dir: Path, state: Mapping[str, Any]) -> None:
    """保留 F1 产物的不可变内部索引，但不生成可交接的 Gate 4 Candidate。"""
    source_sha = str(state["source"]["entry_sha256"])
    report_path = run_dir / "paper_substantive_completeness_report.json"
    manifest = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_internal_content_repair_candidate",
        "candidate_id": f"ICR-{source_sha[:16]}",
        "run_id": str(state["binding"]["run_id"]),
        "source_entry": str(state["source"]["entry"]),
        "source_entry_sha256": source_sha,
        "f1_status": "passed",
        "f2_status": "content_repair_required",
        "completeness_report": {"path": report_path.name, "sha256": sha256_file(report_path)},
        "final_handoff_allowed": False,
    }
    validate_schema(
        manifest,
        "paper_internal_content_repair_candidate.schema.json",
        "paper_internal_content_repair_candidate.json",
    )
    write_json(run_dir / "paper_internal_content_repair_candidate.json", manifest)


def finalize_pipeline(*, run_dir: Path, visual_review_path: Path | None = None) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    _require_gate_4_state(run_dir)
    binding = _binding(run_dir)
    state_path = run_dir / STATE_FILENAME
    state = load_json_object(state_path, STATE_FILENAME)
    validate_schema(state, STATE_SCHEMA, STATE_FILENAME)
    if state.get("status") != "awaiting_visual_review":
        raise ValueError("论文编排状态不是 awaiting_visual_review")
    if state.get("binding") != binding:
        raise ValueError("论文编排状态与当前 Run 身份不一致")
    prepared = _verify_prepared_state(run_dir, state)

    visual_source = (visual_review_path or run_dir / "paper_visual_review.json").resolve()
    _run_relative(run_dir, visual_source, "逐页视觉审核记录")
    visual = _validate_visual_review(
        visual_source,
        pdf_sha256=str(state["render"]["pdf_sha256"]),
        page_count=int(state["render"]["page_count"]),
    )
    visual_target = run_dir / "paper_visual_review.json"
    if visual_source != visual_target.resolve():
        write_json(visual_target, visual)

    verify = verify_submission(
        main_path=prepared["entry"],
        profile_path=prepared["profile"],
        template_dir=prepared["template"],
        render_attestation_path=run_dir / "paper_render_attestation.json",
        humanization_report_path=run_dir / "paper_humanization_report.json",
        claim_bindings_path=run_dir / "paper_claim_map.json",
        claims_project_root=run_dir,
        model_consistency_path=run_dir / "model_text_consistency_report.json",
        visual_review_path=visual_target,
        reports_dir=run_dir,
    )
    if verify.get("status") != "passed":
        failed = [
            name
            for name, result in verify.get("checks", {}).items()
            if result.get("status") == "failed"
        ]
        raise ValueError("Submission Verity 未通过：" + ", ".join(failed))
    production = build_paper_production_manifest(run_dir, binding)
    write_json(run_dir / "paper_production_manifest_v2.json", production)
    content_quality = _run_content_quality_if_bound(run_dir, binding)
    if content_quality is not None:
        state["content_quality"] = {
            "status_path": "paper_gate_f_status.json",
            "completeness_report_path": "paper_substantive_completeness_report.json",
            "delta_report_path": "paper_content_delta_report.json",
        }
    if content_quality is not None and content_quality["f2_status"] != "passed":
        state["status"] = "content_repair_required"
        _write_internal_content_repair_candidate(run_dir, state)
        validate_schema(state, STATE_SCHEMA, STATE_FILENAME)
        write_json(state_path, state)
        return state
    candidate = build_candidate_manifest(run_dir, binding)
    write_json(run_dir / "paper_candidate_manifest.json", candidate)
    gate_manifest_path = write_gate_artifact_manifest(run_dir, 4)
    verify_gate_artifacts(run_dir, 4)

    state["status"] = PAPER_CANDIDATE_STATUS
    state["candidate"] = {
        "manifest_sha256": sha256_file(run_dir / "paper_candidate_manifest.json"),
        "gate_manifest_path": _run_relative(run_dir, gate_manifest_path, "Gate 4 Manifest"),
        "gate_manifest_sha256": sha256_file(gate_manifest_path),
    }
    validate_schema(state, STATE_SCHEMA, STATE_FILENAME)
    write_json(state_path, state)
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="stage", required=True)
    prepare = subparsers.add_parser("prepare", help="验证、渲染并停在逐页视觉审核前")
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--source-dir", type=Path, required=True)
    prepare.add_argument("--source-entry", type=Path, default=Path("main.typ"))
    prepare.add_argument("--narrative-input", type=Path, required=True)
    prepare.add_argument("--model-consistency", type=Path, required=True)
    prepare.add_argument("--humanization-source", type=Path)
    prepare.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    prepare.add_argument("--template-dir", type=Path, default=DEFAULT_TEMPLATE_DIR)
    prepare.add_argument("--renderer-id", default="typst")
    prepare.add_argument("--renderer-executable")
    finalize = subparsers.add_parser(
        "finalize", help="消费现有逐页视觉审核并生成 Gate 4 候选"
    )
    finalize.add_argument("--run-dir", type=Path, required=True)
    finalize.add_argument("--visual-review", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.stage == "prepare":
            result = prepare_pipeline(
                run_dir=args.run_dir,
                source_dir=args.source_dir,
                source_entry=args.source_entry,
                narrative_input_path=args.narrative_input,
                model_consistency_path=args.model_consistency,
                humanization_source_path=args.humanization_source,
                profile_path=args.profile,
                template_dir=args.template_dir,
                renderer_id=args.renderer_id,
                renderer_executable=args.renderer_executable,
            )
        else:
            result = finalize_pipeline(
                run_dir=args.run_dir,
                visual_review_path=args.visual_review,
            )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(json.dumps({"stage": args.stage, "status": result["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
