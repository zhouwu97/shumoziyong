from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atomic_io import atomic_write_bytes, atomic_write_text
from export_runtime_pack import RUNTIME_CONTRACTS, build_manifest, build_pack
from formal_result.identity import (
    CONTRACT_VERSION as FORMAL_CONTRACT_VERSION,
    FORMAL_RESULT_POLICY_LEGACY,
    FORMAL_RESULT_POLICY_REHEARSAL,
    FORMAL_RESULT_POLICY_REQUIRED,
    IMMUTABLE_IDENTITY_FIELDS,
)
from formal_result.verifier import verify_formal_result_bundle
from formal_result.trusted_local import trusted_local_eligibility_scope
from gate3_evidence import collect_gate_3_math_validation, derive_implementation_status
from model_validation import validate_model_and_execution
try:
    from paper.gate4_candidate import (
        PAPER_CANDIDATE_STATUS,
        PAPER_PIPELINE_CONTRACT_VERSION,
        verify_candidate_manifest,
    )
except ModuleNotFoundError:  # pragma: no cover - 允许 pytest 以 scripts.run_workflow 导入。
    from scripts.paper.gate4_candidate import (
        PAPER_CANDIDATE_STATUS,
        PAPER_PIPELINE_CONTRACT_VERSION,
        verify_candidate_manifest,
    )
from communication_contracts import validate_gate_communication
from review_pipeline import (
    approved_supporting_review,
    create_paper_reader_workspace,
    current_candidate,
    record_paper_reader_review,
    record_reasonableness_review,
    record_technical_review,
    register_paper_candidate,
    review_pipeline_evidence_artifacts,
    require_approved_reasonableness_review,
)
from review_ledger import (
    acquire_run_write_lock,
    append_immutable_review,
    reconcile_orphan_reviews,
    verify_history as verify_review_history,
)
from v21_contracts import (
    V21_GATE_CONTRACT_VERSION,
    V21_RUNTIME_MANIFEST_VERSION,
    classify_benchmark,
    compute_score_v2,
    evaluate_paper_admission,
    validate_matlab_recomputation,
    validate_model_validity_contract,
    validate_model_validity_report,
    validate_reviewer_report,
    validate_reviewer_pair,
    validate_competition_value_assessment,
    validate_formal_result_run_binding,
    validate_paper_production_manifest,
    validate_validator_independence,
)
from v21_assertions import validate_assertion_refs
from verify_materials import MaterialVerificationResult, verify_materials

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover - 依赖缺失时由命令行明确报告
    raise SystemExit("缺少 jsonschema，请先执行：python -m pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parents[1]

FORMAL_IDENTITY_DEFAULTS = {
    "formal_result_policy": FORMAL_RESULT_POLICY_REQUIRED,
    "execution_contract_version": FORMAL_CONTRACT_VERSION,
    "formal_result_contract_version": FORMAL_CONTRACT_VERSION,
    "canonicalization_version": FORMAL_CONTRACT_VERSION,
    "gate_artifact_contract_version": FORMAL_CONTRACT_VERSION,
}


class UnresolvedDomainContractError(ValueError):
    """入口 Profile 尚未解析为可封存的正式结果领域合同。"""


def _formal_identity_defaults(policy: str) -> dict[str, str]:
    if policy not in {FORMAL_RESULT_POLICY_REQUIRED, FORMAL_RESULT_POLICY_REHEARSAL}:
        raise ValueError(f"新 Run 不支持 formal_result_policy={policy!r}")
    return {**FORMAL_IDENTITY_DEFAULTS, "formal_result_policy": policy}
GATE_3_EVIDENCE_CONTRACT_VERSION = "1.0.0"
GATE_5_REVIEW_V2_CONTRACT_VERSION = "2.0.0"
GATE_5_RECORDING_POLICY = "recording_only_v1"
GATE_5_DEFAULT_POLICY = "human_final_technical_required_v1"
GATE_5_HUMAN_FINAL_TECHNICAL_POLICY = "human_final_technical_required_v1"
GATE_5_REVIEW_HISTORY_FILENAME = "gate_5_review_history.jsonl"
GATE_5_REVIEW_DIRECTORY = "reviews/gate5"
HUMAN_FINAL_REVIEW_HANDOFF_VERSION = "1.0.0"
HUMAN_FINAL_REVIEW_HANDOFF_DIRECTORY = "human_final_review_handoffs"
GATE_EXECUTION_POLICY_AI_HUMAN_FINAL = "ai_gates_human_final_v1"
COMMUNICATION_CONTRACT_VERSION = "1.0.0"
REASONABLENESS_CONTRACT_VERSION = "1.0.0"
GATE_4_SEMANTIC_CONTRACT_VERSION = "1.0.0"
PROFILE_EXECUTABLE_EVIDENCE_CONTRACTS = {
    "engineering_optimization": GATE_3_EVIDENCE_CONTRACT_VERSION,
}


def _profile_requires_executable_evidence(run_manifest: Mapping[str, Any]) -> bool:
    """仅对显式绑定当前 Gate 3 合同的 Profile 强制执行证据。"""
    required_version = PROFILE_EXECUTABLE_EVIDENCE_CONTRACTS.get(
        str(run_manifest.get("profile"))
    )
    return (
        required_version is not None
        and run_manifest.get("gate_3_evidence_contract_version") == required_version
    )


def formal_result_state_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """构造所有下游摘要共享的 Formal Result 状态与资格范围。"""
    state = {
        "formal_result_activation_status": summary["formal_result_activation_status"],
        "sandboxie_environment_observed": summary["sandboxie_environment_observed"],
        "sandboxie_environment_verified": summary["sandboxie_environment_verified"],
        "formal_result_executed_in_verified_environment": summary[
            "formal_result_executed_in_verified_environment"
        ],
        "formal_result_eligible": summary["formal_result_eligible"],
    }
    state.update(trusted_local_eligibility_scope(dict(summary)))
    return state


def normalize_problem_dir(problem: str) -> str:
    """将题号规范为 official_materials 下使用的目录名。"""
    return re.sub(r"[^A-Za-z0-9]+", "_", problem).strip("_")


def write_json(path: Path, data: object) -> None:
    """以临时文件、fsync 和 os.replace 原子写入 JSON，并回读确认。"""
    content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, content)


def sha256_bytes(content: bytes) -> str:
    """计算内容哈希。"""
    return hashlib.sha256(content).hexdigest()


def chain_transition_event(
    event: Mapping[str, Any], previous_event_sha256: str | None
) -> dict[str, Any]:
    """为转换事件绑定前序哈希并计算自身哈希。"""
    chained = dict(event)
    chained["previous_event_sha256"] = previous_event_sha256
    chained.pop("event_sha256", None)
    canonical = json.dumps(
        chained, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    chained["event_sha256"] = sha256_bytes(canonical)
    return chained


def _validate_transition_hash_chain(entries: list[dict[str, Any]]) -> None:
    previous: str | None = None
    for index, entry in enumerate(entries, start=1):
        expected = chain_transition_event(entry, previous)
        if entry.get("previous_event_sha256") != previous:
            raise ValueError(f"第 {index} 条转换记录 previous_event_sha256 不匹配")
        if entry.get("event_sha256") != expected["event_sha256"]:
            raise ValueError(f"第 {index} 条转换记录 event_sha256 不匹配")
        previous = str(entry["event_sha256"])


def _append_transition_event(path: Path, event: Mapping[str, Any]) -> None:
    entries = _read_transition_entries(path) if path.is_file() else []
    previous = entries[-1].get("event_sha256") if entries else None
    if previous is not None and not isinstance(previous, str):
        raise ValueError("上一条转换记录缺少合法 event_sha256")
    chained = chain_transition_event(event, previous)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    atomic_write_text(
        path,
        existing + json.dumps(chained, ensure_ascii=False) + "\n",
    )


COMMON_EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("run_manifest.json", "run_manifest", "application/json"),
    ("material_review.json", "material_review", "application/json"),
    ("request.json", "request", "application/json"),
    ("response.json", "model_response", "application/json"),
    ("runtime_pack.md", "runtime_pack", "text/markdown"),
    ("runtime_pack.manifest.json", "runtime_pack_manifest", "application/json"),
    ("runtime_profile.snapshot.json", "runtime_profile_snapshot", "application/json"),
    ("patch_selection.snapshot.json", "patch_selection_snapshot", "application/json"),
    ("problem_manifest.json", "problem_manifest", "application/json"),
    ("automatic_evaluation.json", "automatic_evaluation", "application/json"),
    ("ai_run_metadata.json", "ai_run_metadata", "application/json"),
    ("human_review.md", "human_review", "text/markdown"),
    ("transitions.jsonl", "transitions", "application/jsonlines"),
    ("gate_5_review.json", "gate_5_review", "application/json"),
)

FULL_REPLAY_EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("score.json", "score", "application/json"),
    ("failure_labels.json", "failure_labels", "application/json"),
    ("patch_suggestions.md", "patch_suggestions", "text/markdown"),
)

NEW_PROBLEM_EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("competition_process_review.md", "competition_process_review", "text/markdown"),
)

LEGACY_1_1_FULL_REPLAY_EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("run_manifest.json", "run_manifest", "application/json"),
    ("request.json", "request", "application/json"),
    ("response.json", "model_response", "application/json"),
    ("runtime_pack.md", "runtime_pack", "text/markdown"),
    ("runtime_pack.manifest.json", "runtime_pack_manifest", "application/json"),
    ("problem_manifest.json", "problem_manifest", "application/json"),
    ("automatic_evaluation.json", "automatic_evaluation", "application/json"),
    ("ai_run_metadata.json", "ai_run_metadata", "application/json"),
    ("human_review.md", "human_review", "text/markdown"),
    ("transitions.jsonl", "transitions", "application/jsonlines"),
    ("gate_5_review.json", "gate_5_review", "application/json"),
    ("score.json", "score", "application/json"),
    ("failure_labels.json", "failure_labels", "application/json"),
)

WORKFLOW_EVIDENCE_PURPOSES = {
    "full_replay": "training_validation",
    "new_problem": "competition_execution",
}

OPTIONAL_GATE_EVIDENCE_SPECS: tuple[tuple[str, str], ...] = (
    ("diagnosis.json", "gate_0_diagnosis"),
    ("model_route.json", "gate_1_model_route"),
    ("code_plan.json", "gate_2_code_plan"),
    ("result_report.json", "gate_3_result_report"),
    ("result_manifest.json", "gate_3_result_manifest"),
    ("paper_claim_map.json", "gate_4_paper_claim_map"),
)

V21_EVIDENCE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("diagnosis.json", "gate_0_diagnosis", "application/json"),
    ("model_route_v2_1.json", "model_route_v2_1", "application/json"),
    ("model_validity_contract.json", "model_validity_contract", "application/json"),
    ("execution_spec.json", "formal_execution_spec", "application/json"),
    ("validator_independence_manifest.json", "validator_independence_manifest", "application/json"),
    ("model_validity_report.json", "model_validity_report", "application/json"),
    ("matlab_level_a_report.json", "matlab_level_a_report", "application/json"),
    ("matlab_level_b_report.json", "matlab_level_b_report", "application/json"),
    ("formal_result_run_binding.json", "formal_result_run_binding", "application/json"),
    ("competition_value_assessment.json", "competition_value_assessment", "application/json"),
    ("paper_admission_report.json", "paper_admission_report", "application/json"),
    ("paper_claim_map.json", "paper_claim_map_v2", "application/json"),
    ("paper_production_manifest.json", "paper_production_manifest", "application/json"),
    ("score_v2.json", "score_v2", "application/json"),
)


def evidence_artifact_specs_for_workflow(workflow: str) -> tuple[tuple[str, str, str], ...]:
    """返回某个 Gate workflow 的固定基础证据集合。"""
    if workflow == "full_replay":
        return COMMON_EVIDENCE_ARTIFACT_SPECS + FULL_REPLAY_EVIDENCE_ARTIFACT_SPECS
    if workflow == "new_problem":
        return COMMON_EVIDENCE_ARTIFACT_SPECS + NEW_PROBLEM_EVIDENCE_ARTIFACT_SPECS
    raise ValueError(f"Gate 运行不支持的 workflow：{workflow!r}")


def evidence_required_artifacts_for_workflow(
    workflow: str,
    *,
    completed: bool,
    runtime_manifest_version: str = "1.2.0",
    gate_5_review_contract_version: str | None = None,
) -> dict[str, str]:
    """从 workflow 派生不可手填的证据角色合同；完成态额外要求 Gate 0-5。"""
    if runtime_manifest_version == "1.1.0":
        if workflow != "full_replay":
            raise ValueError("runtime pack manifest 1.1.0 只支持历史 full_replay Evidence")
        specs = LEGACY_1_1_FULL_REPLAY_EVIDENCE_ARTIFACT_SPECS
    elif runtime_manifest_version in {"1.2.0", "1.3.0"}:
        specs = evidence_artifact_specs_for_workflow(workflow)
    else:
        raise ValueError(f"runtime pack manifest_version 不支持：{runtime_manifest_version!r}")
    required = {role: filename for filename, role, _media_type in specs}
    gate_5_v2 = gate_5_review_contract_version == GATE_5_REVIEW_V2_CONTRACT_VERSION
    if gate_5_v2:
        # 完成事件会引用最终 Evidence；Evidence 不能再哈希包含该事件的 transitions.jsonl，避免循环依赖。
        required.pop("gate_5_review", None)
        required.pop("transitions", None)
    if runtime_manifest_version == V21_RUNTIME_MANIFEST_VERSION:
        required.update({role: filename for filename, role, _media_type in V21_EVIDENCE_ARTIFACT_SPECS})
    if completed:
        if runtime_manifest_version == V21_RUNTIME_MANIFEST_VERSION:
            required.update({
                "gate_0_diagnosis": "diagnosis.json",
                "gate_0_artifact_manifest": "gate_artifacts/gate_0.manifest.json",
            })
            if gate_5_v2:
                required["gate_5_review_history"] = GATE_5_REVIEW_HISTORY_FILENAME
            else:
                required["gate_5_review"] = "gate_5_review.json"
        else:
            required.update({role: filename for filename, role in OPTIONAL_GATE_EVIDENCE_SPECS})
        required.update(
            {
                f"gate_{gate}_artifact_manifest": f"gate_artifacts/gate_{gate}.manifest.json"
                for gate in range(6)
            }
        )
    return required


def validate_workflow_evidence_purpose(
    manifest: Mapping[str, Any],
    runtime_manifest: Mapping[str, Any] | None = None,
) -> str | None:
    """验证 workflow 与证据用途的一对一绑定，防止通过手改字段改变证据资格。"""
    workflow = manifest.get("workflow")
    if not isinstance(workflow, str):
        return f"run_manifest.workflow 非法：{workflow!r}"
    expected = WORKFLOW_EVIDENCE_PURPOSES.get(workflow)
    if expected is None:
        return f"run_manifest.workflow 非法：{workflow!r}"
    if (
        manifest.get("evidence_purpose") is None
        and runtime_manifest is not None
        and runtime_manifest.get("manifest_version") == "1.1.0"
        and workflow == "full_replay"
    ):
        return None
    if manifest.get("evidence_purpose") != expected:
        return (
            "run_manifest.evidence_purpose 与 workflow 不一致："
            f"{workflow} 必须为 {expected!r}"
        )
    return None


def build_run_evidence_manifest(
    run_dir: Path,
    run_id: str,
    content_overrides: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """为运行目录中的晋级证据生成可验证的路径、大小和内容哈希清单。"""
    run_manifest_path = run_dir / "run_manifest.json"
    try:
        workflow = json.loads(run_manifest_path.read_text(encoding="utf-8")).get("workflow")
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法确定运行工作流：{run_manifest_path}（{exc}）") from exc
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    runtime_version = str(run_manifest.get("runtime_manifest_version", "1.2.0"))
    artifact_specs = evidence_artifact_specs_for_workflow(workflow)
    if runtime_version == V21_RUNTIME_MANIFEST_VERSION:
        artifact_specs = artifact_specs + V21_EVIDENCE_ARTIFACT_SPECS
    gate_5_v2 = run_manifest.get("gate_5_review_contract_version") == GATE_5_REVIEW_V2_CONTRACT_VERSION
    if gate_5_v2:
        artifact_specs = tuple(
            spec for spec in artifact_specs if spec[0] not in {"gate_5_review.json", "transitions.jsonl"}
        )

    artifacts: list[dict[str, Any]] = []
    formal_summary: dict[str, Any] | None = None
    for filename, role, media_type in artifact_specs:
        path = run_dir / filename
        if content_overrides and filename in content_overrides:
            content = content_overrides[filename]
        else:
            if gate_5_v2 and not path.is_file():
                # 未封存 Run 的可变 Evidence 允许不完整；最终封存仍由 required_artifacts 严格拒绝。
                continue
            content = path.read_bytes()
        artifacts.append(
            {
                "path": filename,
                "sha256": sha256_bytes(content),
                "media_type": media_type,
                "size_bytes": len(content),
                "role": role,
            }
        )
    gate_artifacts_dir = run_dir / "gate_artifacts"
    if runtime_version != V21_RUNTIME_MANIFEST_VERSION:
        for filename, role in OPTIONAL_GATE_EVIDENCE_SPECS:
            path = run_dir / filename
            if not path.is_file():
                continue
            content = path.read_bytes()
            artifacts.append(
                {
                    "path": filename,
                    "sha256": sha256_bytes(content),
                    "media_type": "application/json",
                    "size_bytes": len(content),
                    "role": role,
                }
            )
    if gate_artifacts_dir.is_dir():
        for path in sorted(gate_artifacts_dir.glob("gate_*.manifest.json")):
            content = path.read_bytes()
            gate_name = path.name.removeprefix("gate_").removesuffix(".manifest.json")
            artifacts.append(
                {
                    "path": path.relative_to(run_dir).as_posix(),
                    "sha256": sha256_bytes(content),
                    "media_type": "application/json",
                    "size_bytes": len(content),
                    "role": f"gate_{gate_name}_artifact_manifest",
                }
            )
    if gate_5_v2:
        history_path = run_dir / GATE_5_REVIEW_HISTORY_FILENAME
        if history_path.is_file():
            history_content = history_path.read_bytes()
            artifacts.append(
                {
                    "path": GATE_5_REVIEW_HISTORY_FILENAME,
                    "sha256": sha256_bytes(history_content),
                    "media_type": "application/jsonlines",
                    "size_bytes": len(history_content),
                    "role": "gate_5_review_history",
                }
            )
        for review_path in sorted((run_dir / GATE_5_REVIEW_DIRECTORY).glob("*.json")):
            content = review_path.read_bytes()
            review_id = review_path.stem
            artifacts.append(
                {
                    "path": review_path.relative_to(run_dir).as_posix(),
                    "sha256": sha256_bytes(content),
                    "media_type": "application/json",
                    "size_bytes": len(content),
                    "role": f"gate_5_review_record:{review_id}",
                }
            )
    for filename, role, media_type in review_pipeline_evidence_artifacts(run_dir):
        content = (run_dir / filename).read_bytes()
        artifacts.append(
            {
                "path": filename,
                "sha256": sha256_bytes(content),
                "media_type": media_type,
                "size_bytes": len(content),
                "role": role,
            }
        )
    if workflow in {"full_replay", "new_problem"}:
        manifest = run_manifest
        if (
            manifest.get("formal_result_policy") == FORMAL_RESULT_POLICY_REQUIRED
            and any(run_dir.glob("formal_results/*/formal_result_envelope.json"))
        ):
            summary = _verify_required_formal_result(run_dir)
            formal_summary = summary
            formal_specs = [
                (
                    "execution_spec.json",
                    "formal_execution_spec",
                    "application/json",
                    summary["execution_spec_semantic_sha256"],
                ),
                (
                    summary["envelope_path"],
                    "formal_result_envelope",
                    "application/json",
                    summary["envelope_semantic_sha256"],
                ),
                (
                    summary["domain_manifest_path"],
                    "formal_result_domain_manifest",
                    "application/json",
                    summary["domain_manifest_semantic_sha256"],
                ),
            ]
            for relative, item in summary["artifacts"].items():
                formal_specs.append(
                    (
                        item["path"],
                        f"formal_result_{relative.replace('/', '_').removesuffix('.json').removesuffix('.log')}",
                        "application/json" if relative.endswith(".json") else "text/plain",
                        item.get("semantic_sha256"),
                    )
                )
            environment = summary["sandboxie_environment"]
            if environment["sandboxie_environment_verified"]:
                formal_specs.extend(
                    [
                        (
                            environment["report_path"],
                            "sandboxie_environment_report",
                            "application/json",
                            environment["report_semantic_sha256"],
                        ),
                        (
                            environment["attestation_path"],
                            "sandboxie_environment_attestation",
                            "application/json",
                            environment["attestation_semantic_sha256"],
                        ),
                        (
                            environment["configuration_backup_path"],
                            "sandboxie_configuration_backup",
                            "text/plain",
                            None,
                        ),
                    ]
                )
                if environment.get("formal_result_executed_in_verified_environment"):
                    formal_specs.extend(
                        [
                            (environment["run_attestation_path"], "sandboxie_run_execution_attestation", "application/json", environment["run_attestation_semantic_sha256"]),
                            ("sandboxie_run_execution_record.json", "sandboxie_run_execution_record", "application/json", None),
                            ("run_output_manifest.json", "formal_result_output_manifest", "application/json", None),
                            ("formal_result_payload_manifest.json", "formal_result_payload_manifest", "application/json", None),
                            ("collector_derivation_attestation.json", "collector_derivation_attestation", "application/json", None),
                        ]
                    )
            for filename, role, media_type, semantic_hash in formal_specs:
                path = run_dir / filename
                content = path.read_bytes()
                existing = next(
                    (item for item in artifacts if item.get("path") == filename),
                    None,
                )
                if existing is not None:
                    if existing.get("role") != role:
                        raise ValueError(
                            f"Formal Result 证据路径角色冲突：{filename} / "
                            f"{existing.get('role')} != {role}"
                        )
                    if semantic_hash is not None:
                        existing["semantic_sha256"] = semantic_hash
                    continue
                reference = {
                    "path": filename,
                    "sha256": sha256_bytes(content),
                    "media_type": media_type,
                    "size_bytes": len(content),
                    "role": role,
                }
                if semantic_hash is not None:
                    reference["semantic_sha256"] = semantic_hash
                artifacts.append(reference)
    evidence_manifest: dict[str, Any] = {
        "evidence_manifest_version": "2.0.0",
        "run_id": run_id,
        "artifacts": artifacts,
    }
    if formal_summary is not None:
        evidence_manifest.update(formal_result_state_summary(formal_summary))
    return evidence_manifest


def extend_review_pipeline_evidence_requirements(
    run_dir: Path,
    required_artifacts: dict[str, str],
) -> None:
    """将已写入的 Candidate 与 Reviewer 账本提升为封存时的必需证据。"""
    for filename, role, _media_type in review_pipeline_evidence_artifacts(run_dir):
        required_artifacts[role] = filename


def repo_relative(path: Path) -> str:
    """优先记录仓库相对路径；外部材料目录保留绝对路径以确保可追溯。"""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_problem_manifest(
    problem_id: str,
    material_path: Path,
    verification: MaterialVerificationResult,
) -> dict[str, Any]:
    """从材料校验结果生成运行固定的题目快照。

    只记录机器清单中明确声明且哈希校验通过的文件；不再递归扫描目录并把“目录存在”误判为材料就绪。
    """
    files: list[dict[str, Any]] = []
    for item in verification.files:
        relative_file = item["path"]
        resolved = material_path / relative_file
        files.append(
            {
                "category": item["category"],
                "path": repo_relative(resolved),
                "size": item["size"],
                "sha256": item["sha256"],
            }
        )
    files.sort(key=lambda item: (item["category"], item["path"]))

    digest_input = "".join(
        f"{item['category']}:{item['path']}:{item['size']}:{item['sha256']}" for item in files
    )
    content_digest = sha256_bytes(digest_input.encode("utf-8")) if files else None
    return {
        "problem_id": problem_id,
        "material_root": repo_relative(material_path),
        "material_manifest": repo_relative(verification.manifest_path),
        "material_manifest_sha256": verification.manifest_sha256,
        "material_exists": material_path.is_dir(),
        "material_status": verification.status,
        "categories": {
            name: category.to_dict() for name, category in verification.categories.items()
        },
        "files": files,
        "content_digest": content_digest,
        "errors": verification.errors,
    }


def _paper_content_contract_binding(
    problem_id: str, profile: str
) -> tuple[str, str | None, str | None, str | None, dict[str, str] | None, Path | None]:
    """解析题目/Profile 对应的 Gate F 合同，供新 Run 冻结身份。"""
    contracts_dir = ROOT / "paper_content_contracts"
    prefix = str(problem_id).replace("-", "_") + "_" + str(profile) + "_"
    candidates = sorted(contracts_dir.glob(f"{prefix}*.yaml"))
    if len(candidates) != 1:
        return "1.0.0", None, None, None, None, None
    path = candidates[0]
    try:
        from paper.paper_content_quality import (
            CONTRACT_RESOLUTION_VERSION,
            contract_sha256,
            contract_source_hashes,
            load_contract,
        )
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.paper.paper_content_quality import (
            CONTRACT_RESOLUTION_VERSION,
            contract_sha256,
            contract_source_hashes,
            load_contract,
        )
    contract = load_contract(path)
    return (
        "1.0.0",
        str(contract["contract_id"]),
        contract_sha256(contract),
        CONTRACT_RESOLUTION_VERSION,
        contract_source_hashes(path),
        path,
    )


def _experiment_kind(candidate_patches: list[str], excluded_patches: list[str]) -> str:
    if excluded_patches and not candidate_patches:
        return "isolation"
    if candidate_patches:
        return "candidate_experiment"
    return "standard"


RUN_ID_MAX_ATTEMPTS = 8
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _run_id_clock() -> datetime:
    """提供可替换的时钟，确保 Run ID 的时间来源可测试。"""
    return datetime.now()


def _run_id_token() -> str:
    """提供可替换的安全随机尾缀，避免同秒初始化覆盖运行目录。"""
    return secrets.token_hex(3)


def _normalize_run_id_problem(problem: str) -> str:
    """生成只含安全字符的 Run ID 题号片段，同时保留常见题号连字符。"""
    return re.sub(r"[^A-Za-z0-9-]+", "_", problem).strip("_-")


def build_automatic_run_id(problem: str, workflow: str, profile: str) -> str:
    """生成秒级、可追溯且带随机尾缀的自动 Run ID。"""
    token = _run_id_token()
    if not re.fullmatch(r"[A-Za-z0-9]{6,8}", token):
        raise ValueError("Run ID 随机尾缀必须为 6-8 位安全字母数字字符")
    return (
        f"{_run_id_clock().strftime('%Y%m%d_%H%M%S')}_"
        f"{_normalize_run_id_problem(problem)}_{workflow}_{profile}_{token}"
    )


def validate_explicit_run_id(run_id: str) -> str:
    """限制显式 Run ID 为跨平台安全的单段目录名。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}", run_id):
        raise ValueError("显式 Run ID 必须为 1-160 位安全字母数字、下划线或连字符")
    if run_id.upper() in WINDOWS_RESERVED_NAMES:
        raise ValueError("显式 Run ID 不能使用 Windows 保留设备名")
    return run_id


def resolve_profile_for_workflow(args: argparse.Namespace, workflow: str) -> str:
    """按 workflow 解析 Profile；只有比赛新题允许保守默认 general。"""
    raw_profile = getattr(args, "profile", None)
    profile = str(raw_profile).strip() if isinstance(raw_profile, str) else ""
    if workflow == "new_problem" and not profile:
        profile = "general"
    if workflow in {"full_replay", "prompt_regression"} and not profile:
        raise ValueError(f"{workflow} 必须显式提供 --profile")
    if not profile:
        raise ValueError("Profile 不能为空")
    _load_profile_state(profile)
    args.profile = profile
    return profile


def _resolve_run_directory(
    args: argparse.Namespace,
    *,
    workflow: str,
    profile: str,
) -> tuple[str, Path]:
    """解析当前阶段的运行目录；显式重复 ID 失败，自动 ID 有限重试。"""
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    explicit_run_id = getattr(args, "run_id", None)
    if explicit_run_id is not None:
        run_id = validate_explicit_run_id(str(explicit_run_id))
        run_dir = output_root / run_id
        if run_dir.exists():
            raise FileExistsError(f"运行目录已存在：{run_dir}")
        return run_id, run_dir
    for _attempt in range(RUN_ID_MAX_ATTEMPTS):
        run_id = build_automatic_run_id(args.problem, workflow, profile)
        run_dir = output_root / run_id
        if not run_dir.exists():
            return run_id, run_dir
    raise FileExistsError(f"自动 Run ID 连续 {RUN_ID_MAX_ATTEMPTS} 次冲突，已拒绝覆盖：{output_root}")


def _resolve_material_path(args: argparse.Namespace) -> Path:
    """解析材料根目录，保持旧题默认材料目录与新题显式材料目录兼容。"""
    material_path = (
        Path(args.materials)
        if args.materials
        else ROOT / "official_materials" / normalize_problem_dir(args.problem)
    )
    if not material_path.is_absolute():
        material_path = ROOT / material_path
    return material_path.resolve()


def _load_profile_state(profile: str) -> dict[str, Any]:
    """读取已注册 Runtime Profile，避免目录初始化后才发现 Profile 不存在。"""
    profile_state_path = ROOT / "runtime_profiles" / f"{profile}.json"
    if not profile_state_path.is_file():
        raise FileNotFoundError(f"runtime profile 状态不存在：{profile_state_path}")
    profile_state = json.loads(profile_state_path.read_text(encoding="utf-8"))
    if not isinstance(profile_state, dict):
        raise ValueError(f"runtime profile 必须是 JSON 对象：{profile_state_path}")
    return profile_state


def _initialize_common_gate_artifacts(
    run_dir: Path, profile_state: Mapping[str, Any], *, v21_enabled: bool = False
) -> None:
    """创建两个 Gate 工作流共享的业务产物和 AI 运行证据脚手架。"""
    atomic_write_text(run_dir / "diagnosis.md", "# Gate 0：题目与材料诊断\n\n待执行。\n")
    write_json(
        run_dir / "diagnosis.json",
        {"stage": "diagnosis", "_note": "待执行；完成后须符合 schemas/diagnosis.schema.json"},
    )
    for filename, artifact_type in (
        ("model_route.json", "model_route"),
        ("code_plan.json", "code_plan"),
        ("result_report.json", "result_report"),
        ("result_manifest.json", "result_manifest"),
        ("paper_claim_map.json", "paper_claim_map"),
        ("paper_candidate_manifest.json", "paper_production_candidate_manifest"),
    ):
        write_json(
            run_dir / filename,
            {
                "artifact_type": artifact_type,
                "_note": "待执行；离开对应 Gate 前必须替换为符合业务 Schema 的真实产物。",
            },
        )
    for filename, artifact_type in (
        ("model_route_v2_1.json", "model_route_v2_1"),
        ("model_validity_contract.json", "model_validity_contract"),
        ("execution_spec.json", "execution_spec"),
        ("validator_independence_manifest.json", "validator_independence_manifest"),
        ("model_validity_report.json", "model_validity_report"),
        ("paper_admission_report.json", "paper_admission_report"),
        ("paper_production_manifest.json", "paper_production_manifest"),
        ("score_v2.json", "score_v2"),
        ("matlab_level_a_report.json", "matlab_recomputation"),
        ("matlab_level_b_report.json", "matlab_recomputation"),
        ("formal_result_run_binding.json", "formal_result_run_binding"),
        ("competition_value_assessment.json", "competition_value_assessment"),
    ) if v21_enabled else ():
        write_json(
            run_dir / filename,
            {
                "artifact_type": artifact_type,
                "_note": "Runtime 1.3 / Gate Contract 2.1 工件；离开对应 Gate 前必须替换。",
            },
        )
    (run_dir / "gate_artifacts").mkdir()
    if v21_enabled:
        (run_dir / GATE_5_REVIEW_DIRECTORY).mkdir(parents=True, exist_ok=True)
        atomic_write_text(run_dir / GATE_5_REVIEW_HISTORY_FILENAME, "")
        (run_dir / "reviews" / "reasonableness").mkdir(parents=True, exist_ok=True)
        atomic_write_text(run_dir / "reasonableness_review_history.jsonl", "")
        (run_dir / "reviews" / "technical").mkdir(parents=True, exist_ok=True)
        atomic_write_text(run_dir / "technical_review_history.jsonl", "")
        (run_dir / "reviews" / "paper_reader").mkdir(parents=True, exist_ok=True)
        atomic_write_text(run_dir / "paper_reader_review_history.jsonl", "")
        (run_dir / "paper_candidates").mkdir(parents=True, exist_ok=True)
        atomic_write_text(run_dir / "paper_candidate_history.jsonl", "")
    else:
        write_json(
            run_dir / "gate_5_review.json",
            {"_note": "待 Gate 5 通过后填写；完成记录必须符合 schemas/gate_5_review.schema.json。"},
        )
    write_json(
        run_dir / "request.json",
        {
            "_note": "待填写：发送给 AI 的提示词",
            "prompt": "",
            "model": "",
            "runtime_version": profile_state["version"],
            "source": "pending",
            "response_reference": None,
        },
    )
    atomic_write_text(run_dir / "response.md", "# AI 输出（Markdown）\n\n待填写。\n")
    write_json(
        run_dir / "response.json",
        {"_note": "待填写：AI 结构化 JSON 输出，须符合 diagnosis.schema.json"},
    )
    write_json(
        run_dir / "automatic_evaluation.json",
        {"_note": "待生成：由 evaluate_prompt_response.py 产出", "case_id": "", "errors": []},
    )
    atomic_write_text(
        run_dir / "human_review.md",
        "# 人工审核\n\n待填写。至少写明：\n"
        "- 是否出现 patch 特有机制\n"
        "- 是否改变正确题型\n"
        "- 是否相比 baseline 发生跑偏\n"
        "- 最终判定 pass/fail\n"
        "- 判断理由\n",
    )
    write_json(
        run_dir / "ai_run_metadata.json",
        {
            "metadata_version": "1.0.0",
            "status": "pending",
            "note": "待填写真实运行数据；pending 元数据不能作为晋级证据。",
            "provider": None,
            "model": None,
            "model_snapshot": None,
            "client": None,
            "client_version": None,
            "reasoning_effort": None,
            "temperature": None,
            "seed": None,
            "started_at": None,
            "completed_at": None,
            "prompt_sha256": None,
            "runtime_pack_sha256": None,
            "problem_material_digest": None,
            "tool_permissions": None,
            "working_directory_mode": None,
        },
    )


def create_gate_run_core(
    args: argparse.Namespace,
    *,
    workflow: str,
    evidence_purpose: str,
) -> tuple[Path, MaterialVerificationResult, dict[str, Any], dict[str, Any], Path]:
    """初始化 full_replay 与 new_problem 共用的材料、运行包和 Gate 基础现场。"""
    if getattr(args, "material_file", []):
        raise ValueError("不再支持 --material-file：旧题运行必须校验完整材料清单，不能用子集绕过附件或模板检查")
    if workflow not in {"full_replay", "new_problem"}:
        raise ValueError(f"不支持的 Gate workflow：{workflow!r}")
    profile = resolve_profile_for_workflow(args, workflow)
    run_id, run_dir = _resolve_run_directory(args, workflow=workflow, profile=profile)
    material_path = _resolve_material_path(args)
    material_verification = verify_materials(
        material_path,
        expected_problem_id=args.problem,
    )
    profile_state = _load_profile_state(profile)
    v21_enabled = bool(getattr(args, "v21", False))
    candidate_patches = list(getattr(args, "candidate_patch", []))
    excluded_patches = list(getattr(args, "exclude_patch", []))
    pack_content = build_pack(
        profile, workflow, candidate_patches, excluded_patches
    )
    benchmark_classification = classify_benchmark(
        str(args.problem), materials_previously_read=(workflow == "full_replay")
    )
    if v21_enabled:
        pack_manifest = build_manifest(
            profile,
            workflow,
            pack_content,
            candidate_patches,
            excluded_patches,
            manifest_version=V21_RUNTIME_MANIFEST_VERSION,
            gate_contract_version=V21_GATE_CONTRACT_VERSION,
            benchmark_classification=benchmark_classification,
        )
    else:
        pack_manifest = build_manifest(
            profile, workflow, pack_content, candidate_patches, excluded_patches
        )

    run_dir.mkdir(parents=True)
    atomic_write_text(run_dir / "runtime_pack.md", pack_content)
    write_json(run_dir / "runtime_pack.manifest.json", pack_manifest)
    write_json(run_dir / "runtime_profile.snapshot.json", profile_state)
    patch_selection_snapshot = {
        "selected_patches": [item["patch_id"] for item in pack_manifest.get("patches", [])],
        "candidate_patches": candidate_patches,
        "excluded_patches": excluded_patches,
    }
    write_json(run_dir / "patch_selection.snapshot.json", patch_selection_snapshot)

    problem_manifest = build_problem_manifest(args.problem, material_path, material_verification)
    write_json(run_dir / "problem_manifest.json", problem_manifest)
    (
        paper_contract_version,
        paper_contract_id,
        paper_contract_sha,
        paper_contract_resolution_version,
        paper_contract_source_hashes,
        paper_contract_source,
    ) = _paper_content_contract_binding(
        args.problem, profile
    )
    if paper_contract_source is not None:
        shutil.copyfile(paper_contract_source, run_dir / "paper_content_contract.yaml")

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    initial_state = "initialized" if material_verification.ready else "blocked"
    mode = getattr(args, "mode", "standard")
    # 模型、代码和论文修订均由 AI/Agent 留下可审计证据；只有 Gate 5 是人工最终决策。
    confirmation_gates = {"strict": [5], "standard": [5], "emergency": [5]}[mode]
    manifest_data: dict[str, Any] = {
        "manifest_version": "2.0.0",
        "run_id": run_id,
        "workflow": workflow,
        "mode": mode,
        "human_confirmation_gates": confirmation_gates,
        "gate_execution_policy": GATE_EXECUTION_POLICY_AI_HUMAN_FINAL,
        "created_at": created_at,
        "problem_id": args.problem,
        "profile": profile,
        "runtime_version": profile_state["version"],
        "runtime_pack_sha256": pack_manifest["runtime_pack_sha256"],
        "runtime_manifest_version": pack_manifest["manifest_version"],
        "gates": args.gates,
        "materials": repo_relative(material_path),
        "material_manifest": repo_relative(material_verification.manifest_path),
        "material_manifest_sha256": material_verification.manifest_sha256,
        "material_status": material_verification.status,
        "material_error_count": len(material_verification.errors)
        + sum(len(category.errors) for category in material_verification.categories.values()),
        "candidate_patches": candidate_patches,
        "excluded_patches": excluded_patches,
        "evidence_purpose": evidence_purpose,
        "initial_state": initial_state,
        "gate_3_evidence_contract_version": GATE_3_EVIDENCE_CONTRACT_VERSION,
        "paper_pipeline_contract_version": PAPER_PIPELINE_CONTRACT_VERSION,
        "paper_content_quality_contract_version": paper_contract_version,
        "paper_content_contract_id": paper_contract_id,
        "paper_content_contract_sha256": paper_contract_sha,
        "paper_content_contract_resolution_version": paper_contract_resolution_version,
        "paper_content_contract_merged_sha256": paper_contract_sha,
        "paper_content_contract_source_hashes": paper_contract_source_hashes,
        "legacy_paper_content_policy": False,
        **_formal_identity_defaults(
            str(getattr(args, "formal_result_policy", FORMAL_RESULT_POLICY_REQUIRED))
        ),
        "runtime_profile_snapshot_sha256": sha256_bytes(
            (run_dir / "runtime_profile.snapshot.json").read_bytes()
        ),
        "patch_selection_snapshot_sha256": sha256_bytes(
            (run_dir / "patch_selection.snapshot.json").read_bytes()
        ),
    }
    if v21_enabled:
        manifest_data.update(
            {
                "gate_contract_version": V21_GATE_CONTRACT_VERSION,
                "communication_contract_version": COMMUNICATION_CONTRACT_VERSION,
                "reasonableness_contract_version": REASONABLENESS_CONTRACT_VERSION,
                "gate_4_semantic_contract_version": GATE_4_SEMANTIC_CONTRACT_VERSION,
                "gate_5_review_contract_version": GATE_5_REVIEW_V2_CONTRACT_VERSION,
                "gate_5_policy_version": GATE_5_DEFAULT_POLICY,
                **benchmark_classification,
            }
        )

    write_json(run_dir / "run_manifest.json", manifest_data)
    material_report = material_verification.to_dict()
    material_report["material_path"] = repo_relative(material_path)
    material_report["manual_review_required"] = True
    write_json(run_dir / "material_review.json", material_report)

    _initialize_common_gate_artifacts(run_dir, profile_state, v21_enabled=v21_enabled)
    _init_transitions(run_dir, args.gates, material_verification.ready)
    return run_dir, material_verification, profile_state, pack_manifest, material_path


def create_full_replay_run(args: argparse.Namespace) -> tuple[Path, bool]:
    """初始化旧题训练运行，并写入训练与 Patch 晋级专属产物。"""
    run_dir, material_verification, profile_state, _pack_manifest, material_path = create_gate_run_core(
        args,
        workflow="full_replay",
        evidence_purpose="training_validation",
    )
    manifest_path = run_dir / "run_manifest.json"
    manifest_data = _load_json_object(manifest_path, "run_manifest.json")
    candidate_patches = list(getattr(args, "candidate_patch", []))
    excluded_patches = list(getattr(args, "exclude_patch", []))
    manifest_data.update(
        {
            "experiment_kind": _experiment_kind(candidate_patches, excluded_patches),
            "promotion_evidence": bool(getattr(args, "promotion_evidence", False)),
        }
    )
    if getattr(args, "promotion_evidence", False):
        if not getattr(args, "experiment_group_id", None):
            raise ValueError("--promotion-evidence 必须提供 --experiment-group-id")
        if not getattr(args, "experiment_role", None):
            raise ValueError("--promotion-evidence 必须提供 --experiment-role")
        if not getattr(args, "target_patch", None):
            raise ValueError("--promotion-evidence 必须提供 --target-patch")
        manifest_data.update(
            {
                "experiment_kind": "negative_control",
                "experiment_group_id": args.experiment_group_id,
                "experiment_role": args.experiment_role,
                "target_patch": args.target_patch,
            }
        )
        if args.experiment_role == "baseline" and args.target_patch not in excluded_patches:
            raise ValueError("baseline 必须在 excluded_patches 中排除 target_patch")
        if args.experiment_role == "patch_only" and args.target_patch in excluded_patches:
            raise ValueError("patch_only 不能排除 target_patch")
    write_json(manifest_path, manifest_data)

    material_review = _load_json_object(run_dir / "material_review.json", "material_review.json")
    material_review["material_level"] = None
    material_review["risk_labels"] = []
    write_json(run_dir / "material_review.json", material_review)
    material_status_text = "材料校验通过" if material_verification.ready else "材料校验失败，已阻塞"
    atomic_write_text(
        run_dir / "execution_plan.md",
        f"# 旧题闭环执行计划\n\n"
        f"- 题目：`{args.problem}`\n"
        f"- profile：`{args.profile}`（{profile_state['version']} / {profile_state['maturity']}）\n"
        f"- 闸门范围：Gate {args.gates}\n"
        f"- 材料：`{repo_relative(material_path)}`\n"
        f"- 材料清单：`{repo_relative(material_verification.manifest_path)}`\n"
        f"- review_ready 实验 patch：{candidate_patches or '无'}\n"
        f"- 排除 patch：{excluded_patches or '无'}\n"
        f"- 实验类型：{_experiment_kind(candidate_patches, excluded_patches)}\n"
        f"- 状态：{material_status_text}\n\n"
        "## Gate 0-5 定义\n\n"
        "- Gate 0：题目与材料诊断\n"
        "- Gate 1：模型路线\n"
        "- Gate 2：代码计划\n"
        "- Gate 3：结果确认\n"
        "- Gate 4：论文确认\n"
        "- Gate 5：最终验收\n\n"
        "## 执行顺序\n\n"
        "1. 先检查 `material_review.json`：只有 `status=ready` 才能进入 Gate 0。\n"
        "2. 人工确认材料等级 T0-T4 与风险 M1-M5。\n"
        "3. 读取 `runtime_pack.md`，只执行指定 Gate。\n"
        "4. 把发送给 AI 的提示词存入 `request.json`。\n"
        "5. 将诊断写入 `diagnosis.md`（人看）与 `diagnosis.json`（机器检查，符合 `schemas/diagnosis.schema.json`）。\n"
        "6. 把 AI 原始输出存入 `response.md` 和 `response.json`。\n"
        "7. 运行 `evaluate_prompt_response.py` 生成 `automatic_evaluation.json`。\n"
        "8. 人工填写 `human_review.md`、`score.json` 与 `failure_labels.json`。\n"
        "9. 只把升级建议写入 `patch_suggestions.md`，不得自动修改 patch 状态。\n",
    )
    write_json(run_dir / "score.json", {"total": None, "items": {}, "passed": None})
    write_json(run_dir / "failure_labels.json", {"labels": [], "evidence": {}, "reviewed": False})
    atomic_write_text(
        run_dir / "patch_suggestions.md",
        "# Patch 建议\n\n待复盘后填写；不得自动升级状态。\n",
    )
    write_json(
        run_dir / "run_evidence_manifest.json",
        build_run_evidence_manifest(run_dir, str(manifest_data["run_id"])),
    )
    return run_dir, material_verification.ready


def create_new_problem_run(args: argparse.Namespace) -> tuple[Path, bool]:
    """初始化比赛运行；不得携带旧题训练或 Patch 晋级语义。"""
    if getattr(args, "candidate_patch", []) or getattr(args, "exclude_patch", []):
        raise ValueError("new_problem 不支持 candidate/exclude Patch；正式比赛包只能使用已验证 Patch")
    if getattr(args, "promotion_evidence", False):
        raise ValueError("new_problem 不能声明为 Patch 晋级证据")
    run_dir, material_verification, profile_state, _pack_manifest, material_path = create_gate_run_core(
        args,
        workflow="new_problem",
        evidence_purpose="competition_execution",
    )
    material_status_text = "材料校验通过" if material_verification.ready else "材料校验失败，已阻塞"
    atomic_write_text(
        run_dir / "execution_plan.md",
        f"# 比赛执行计划\n\n"
        f"- 题目：`{args.problem}`\n"
        f"- profile：`{args.profile}`（{profile_state['version']}）\n"
        f"- 闸门范围：Gate {args.gates}\n"
        f"- 材料：`{repo_relative(material_path)}`\n"
        f"- 材料清单：`{repo_relative(material_verification.manifest_path)}`\n"
        f"- 状态：{material_status_text}\n\n"
        "## 比赛 Gate 0-5\n\n"
        "- Gate 0：题目与材料诊断；本轮只完成读题、题型判断、风险和人工确认项。\n"
        "- Gate 1：模型路线；经人工确认后明确变量、约束、基线和验证方式。\n"
        "- Gate 2：实现计划；确认模块、输入输出、验证和降级策略。\n"
        "- Gate 3：结果确认；验证结果、约束、基线比较和稳健性。\n"
        "- Gate 4：论文确认；仅映射已有证据，不把候选内容写成结论。\n"
        "- Gate 5：最终验收；复核可复现性、风险闭环和交付完整性。\n\n"
        "## 执行约束\n\n"
        "1. 仅在材料状态为 ready 时进入 Gate 0。\n"
        "2. 第一轮只执行 Gate 0；未经人工确认不得进入下一阶段。\n"
        "3. 每个 Gate 的 JSON 业务产物和 Gate Manifest 必须绑定当前 Run 身份。\n"
        "4. 记录真实 AI 运行元数据、请求、响应和人工审核。\n"
        "5. 本比赛 Run 的 evidence_purpose 为 competition_execution，不具备 Patch 首级晋级资格。\n",
    )
    atomic_write_text(
        run_dir / "competition_process_review.md",
        "# 比赛过程审核\n\n待填写每次人工确认、风险决策和阶段推进理由。\n",
    )
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    write_json(
        run_dir / "run_evidence_manifest.json",
        build_run_evidence_manifest(run_dir, str(manifest["run_id"])),
    )
    return run_dir, material_verification.ready


def create_old_problem_run(args: argparse.Namespace) -> tuple[Path, bool]:
    """兼容旧调用名称，并按调用方声明的 workflow 分派初始化语义。"""
    if getattr(args, "workflow", "full_replay") == "new_problem":
        return create_new_problem_run(args)
    return create_full_replay_run(args)


GATE_NAMES: dict[int, str] = {
    0: "题目与材料诊断",
    1: "模型路线",
    2: "代码计划",
    3: "结果确认",
    4: "论文确认",
    5: "最终验收",
}

GATE_5_CHECKLIST_KEYS: tuple[str, ...] = (
    "materials",
    "diagnosis",
    "model_route",
    "code_reproduction",
    "results",
    "claim_evidence",
    "risk_closure",
    "final_acceptance",
)

GATE_ARTIFACT_SPECS: dict[int, tuple[tuple[str, str, str, str], ...]] = {
    0: (("diagnosis.json", "diagnosis", "schemas/gate_business_artifact.schema.json", "1.0.0"),),
    1: (("model_route.json", "model_route", "schemas/gate_business_artifact.schema.json", "1.0.0"),),
    2: (("code_plan.json", "code_plan", "schemas/gate_business_artifact.schema.json", "1.0.0"),),
    3: (
        ("result_report.json", "result_report", "schemas/gate_business_artifact.schema.json", "1.0.0"),
        ("result_manifest.json", "result_manifest", "schemas/gate_business_artifact.schema.json", "1.0.0"),
    ),
    4: (("paper_claim_map.json", "paper_claim_map", "schemas/gate_business_artifact.schema.json", "1.0.0"),),
    5: (("gate_5_review.json", "gate_5_review", "schemas/gate_5_review.schema.json", "1.0.0"),),
}

PAPER_GATE_4_ARTIFACT_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "paper_candidate_manifest.json",
        "paper_production_candidate_manifest",
        "schemas/paper_production_candidate_manifest.schema.json",
        "1.0.0",
    ),
)

V21_GATE_ARTIFACT_SPECS: dict[int, tuple[tuple[str, str, str, str], ...]] = {
    0: GATE_ARTIFACT_SPECS[0],
    1: (
        ("model_route_v2_1.json", "model_route_v2_1", "schemas/model_route_v2_1.schema.json", "2.1.0"),
        ("model_validity_contract.json", "model_validity_contract", "schemas/model_validity_contract.schema.json", "1.0.0"),
    ),
    2: (
        ("code_plan.json", "code_plan", "schemas/gate_business_artifact.schema.json", "1.0.0"),
        ("execution_spec.json", "execution_spec", "schemas/execution_spec.schema.json", "1.0.0"),
        ("validator_independence_manifest.json", "validator_independence_manifest", "schemas/validator_independence_manifest.schema.json", "1.0.0"),
    ),
    3: (
        ("result_report.json", "result_report", "schemas/gate_business_artifact.schema.json", "1.0.0"),
        ("result_manifest.json", "result_manifest", "schemas/gate_business_artifact.schema.json", "1.0.0"),
        ("model_validity_report.json", "model_validity_report", "schemas/model_validity_report.schema.json", "1.0.0"),
        ("matlab_level_a_report.json", "matlab_recomputation", "schemas/matlab_recomputation_report.schema.json", "1.0.0"),
        ("matlab_level_b_report.json", "matlab_recomputation", "schemas/matlab_recomputation_report.schema.json", "1.0.0"),
        ("formal_result_run_binding.json", "formal_result_run_binding", "schemas/formal_result_run_binding.schema.json", "1.0.0"),
        ("competition_value_assessment.json", "competition_value_assessment", "schemas/competition_value_assessment.schema.json", "1.0.0"),
        ("paper_admission_report.json", "paper_admission_report", "schemas/paper_admission_report.schema.json", "1.0.0"),
    ),
    4: (
        ("paper_claim_map.json", "paper_claim_map_v2", "schemas/paper_claim_map_v2.schema.json", "2.0.0"),
        ("paper_production_manifest.json", "paper_production_manifest", "schemas/paper_production_manifest.schema.json", "1.0.0"),
    ),
    5: (
        ("gate_5_review.json", "gate_5_review", "schemas/gate_5_review.schema.json", "1.0.0"),
        ("score_v2.json", "score_v2", "schemas/score_v2.schema.json", "2.0.0"),
    ),
}

V21_ARTIFACT_ROLES = {
    "model_route_v2_1", "model_validity_contract", "validator_independence_manifest",
    "execution_spec", "model_validity_report", "matlab_recomputation", "paper_admission_report",
    "paper_production_manifest", "reviewer_report", "score_v2", "paper_claim_map_v2",
    "formal_result_run_binding", "competition_value_assessment", "reviewer_a_round1",
    "reviewer_b_round1", "reviewer_a_round2", "reviewer_b_round2",
}


def _is_v21_run(run_dir: Path) -> bool:
    try:
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        runtime = json.loads((run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return manifest.get("runtime_manifest_version") == V21_RUNTIME_MANIFEST_VERSION or runtime.get("manifest_version") == V21_RUNTIME_MANIFEST_VERSION


def _paper_pipeline_is_required(run_manifest: Mapping[str, Any]) -> bool:
    """仅对显式绑定当前论文闭环合同的新 Run 强制执行严格 Gate 4。"""
    version = run_manifest.get("paper_pipeline_contract_version")
    if version is None:
        return False
    if version != PAPER_PIPELINE_CONTRACT_VERSION:
        raise ValueError(f"paper_pipeline_contract_version 非法：{version!r}")
    return True


def _gate_artifact_specs_for_run(run_dir: Path, gate: int) -> tuple[tuple[str, str, str, str], ...]:
    if gate not in GATE_ARTIFACT_SPECS:
        raise ValueError(f"未知 Gate：{gate}（允许 0-5）")
    if gate == 4:
        run_manifest = _load_json_object(
            run_dir / "run_manifest.json", "run_manifest.json"
        )
        if _paper_pipeline_is_required(run_manifest):
            return PAPER_GATE_4_ARTIFACT_SPECS
    return (V21_GATE_ARTIFACT_SPECS if _is_v21_run(run_dir) else GATE_ARTIFACT_SPECS)[gate]


def _completed_gate_state(run_manifest: Mapping[str, Any], gate: int) -> str:
    if gate == 4 and _paper_pipeline_is_required(run_manifest):
        return PAPER_CANDIDATE_STATUS
    return f"completed_gate_{gate}"


def _formal_result_policy(run_manifest: Mapping[str, Any]) -> str:
    """读取显式政策；旧封存运行缺字段时仅按 Legacy 读取。"""
    policy = run_manifest.get("formal_result_policy")
    if policy is None:
        return FORMAL_RESULT_POLICY_LEGACY
    if policy not in {
        FORMAL_RESULT_POLICY_REQUIRED,
        FORMAL_RESULT_POLICY_LEGACY,
        FORMAL_RESULT_POLICY_REHEARSAL,
    }:
        raise ValueError(f"formal_result_policy 非法：{policy!r}")
    return str(policy)


def _verify_required_formal_result(run_dir: Path) -> dict[str, Any]:
    envelopes = sorted(run_dir.glob("formal_results/*/formal_result_envelope.json"))
    if len(envelopes) != 1:
        raise ValueError(f"required_v1 Run 必须且只能包含一个 Formal Result Envelope，实际 {len(envelopes)}")
    return verify_formal_result_bundle(run_dir, envelopes[0])


def extend_formal_result_evidence_requirements(
    run_dir: Path, required: dict[str, str]
) -> dict[str, Any] | None:
    """对 required_v1 运行现场添加 Formal Result 核心证据角色。"""
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if _formal_result_policy(manifest) != FORMAL_RESULT_POLICY_REQUIRED:
        return None
    summary = _verify_required_formal_result(run_dir)
    required["formal_execution_spec"] = "execution_spec.json"
    required["formal_result_envelope"] = str(summary["envelope_path"])
    required["formal_result_domain_manifest"] = str(summary["domain_manifest_path"])
    for relative, item in summary["artifacts"].items():
        role = f"formal_result_{relative.replace('/', '_').removesuffix('.json').removesuffix('.log')}"
        required[role] = str(item["path"])
    environment = summary["sandboxie_environment"]
    if environment["sandboxie_environment_verified"]:
        required["sandboxie_environment_report"] = str(environment["report_path"])
        required["sandboxie_environment_attestation"] = str(
            environment["attestation_path"]
        )
        required["sandboxie_configuration_backup"] = str(
            environment["configuration_backup_path"]
        )
        if environment.get("formal_result_executed_in_verified_environment"):
            required["sandboxie_run_execution_attestation"] = str(
                environment["run_attestation_path"]
            )
            required["sandboxie_run_execution_record"] = "sandboxie_run_execution_record.json"
            required["formal_result_output_manifest"] = "run_output_manifest.json"
            required["formal_result_payload_manifest"] = "formal_result_payload_manifest.json"
            required["collector_derivation_attestation"] = "collector_derivation_attestation.json"
    return summary


def _assert_formal_result_mutable(run_dir: Path) -> None:
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    policy = _formal_result_policy(manifest)
    if policy == FORMAL_RESULT_POLICY_LEGACY:
        raise ValueError("legacy_read_only_v1 Run 只允许历史验证与导出，禁止继续推进、完成或重新封存")
    for field, expected in _formal_identity_defaults(policy).items():
        if manifest.get(field) != expected:
            raise ValueError(f"run_manifest.{field} 已漂移，禁止继续推进")


def _assert_resolved_domain_contract(run_manifest: Mapping[str, Any]) -> None:
    """正式资格运行不得把入口 Profile 当作领域合同封存。"""
    if (
        _formal_result_policy(run_manifest) == FORMAL_RESULT_POLICY_REQUIRED
        and run_manifest.get("profile") == "general"
    ):
        raise UnresolvedDomainContractError(
            "general 仅是入口 Profile；Gate 3 前必须使用 fork-profile 派生已注册专项 Profile"
        )

TRANSITION_VERSION = "2.0.0"

VALID_TRANSITIONS: dict[int | None, set[int]] = {
    # from_gate -> {valid to_gate}；None 表示只允许从初始状态进入
    None: {0},       # 只能从 initialized 进入 Gate 0
    0: {1},          # Gate 0 → Gate 1
    1: {2},          # Gate 1 → Gate 2
    2: {3},          # Gate 2 → Gate 3
    3: {4},          # Gate 3 → Gate 4
    4: {5},          # Gate 4 → Gate 5
    5: set(),        # Gate 5 是终点
}


def _init_transitions(run_dir: Path, gate_range: str, material_ready: bool) -> None:
    """初始化 transitions.jsonl 并记录 initialized 状态。"""
    max_gate = int(gate_range.split("-")[1])
    run_manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    immutable_identity = {field: run_manifest[field] for field in IMMUTABLE_IDENTITY_FIELDS}
    initialized = chain_transition_event(
        {
            "transition_version": TRANSITION_VERSION,
            "from": None,
            "to": None,
            "completed_gate": None,
            "next_gate": 0,
            "state": "initialized",
            "material_ready": material_ready,
            "max_gate": max_gate,
            "note": "运行目录已创建；材料校验通过后才允许进入 Gate 0",
            **immutable_identity,
        },
        None,
    )
    atomic_write_text(
        run_dir / "transitions.jsonl",
        json.dumps(initialized, ensure_ascii=False) + "\n",
    )


def _read_transition_entries(transitions_path: Path) -> list[dict[str, Any]]:
    """读取转换日志，逐行要求为 JSON 对象，避免半截或伪造记录被忽略。"""
    entries: list[dict[str, Any]] = []
    for line_no, line in enumerate(transitions_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"transitions.jsonl 第 {line_no} 行不是合法 JSON：{exc}") from exc
        if not isinstance(entry, dict):
            raise ValueError(f"transitions.jsonl 第 {line_no} 行必须是 JSON 对象")
        entries.append(entry)
    return entries


def _replay_v2_transition_log(
    run_dir: Path,
    entries: list[dict[str, Any]],
    *,
    verify_artifacts: bool = True,
) -> dict[str, Any]:
    """回放 v2 Gate 日志：事件表达已完成 Gate 和下一 Gate。"""
    _validate_transition_hash_chain(entries)
    init_data = entries[0]
    run_manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if any(field in init_data for field in IMMUTABLE_IDENTITY_FIELDS):
        for field in IMMUTABLE_IDENTITY_FIELDS:
            if init_data.get(field) != run_manifest.get(field):
                raise ValueError(f"v2 initialized 记录的 {field} 与 run_manifest 不一致")
    if init_data.get("completed_gate") is not None or init_data.get("next_gate") != 0:
        raise ValueError("v2 initialized 记录必须声明 completed_gate=null、next_gate=0")

    current: int | None = None
    completed_gates: list[int] = []
    completed = False
    completed_entry: dict[str, Any] | None = None
    lifecycle_status = "active"
    superseded_by_run_id: str | None = None
    fork_transaction_id: str | None = None
    revision_transaction_id: str | None = None
    for idx, entry in enumerate(entries[1:], start=2):
        if entry.get("transition_version") != TRANSITION_VERSION:
            raise ValueError(f"第 {idx} 条 Gate 记录 transition_version 不一致")
        if entry.get("state") == "profile_fork_rolled_back":
            if completed or lifecycle_status != "superseded":
                raise ValueError("profile_fork_rolled_back 只能补偿尚未提交的 profile_forked")
            if entry.get("event_type") != "profile_fork_rolled_back":
                raise ValueError("profile_fork_rolled_back 事件类型非法")
            if (
                current != 0
                or entry.get("completed_gate") is not None
                or entry.get("next_gate") != 0
                or entry.get("lifecycle_status") != "active"
            ):
                raise ValueError("profile_fork_rolled_back 必须恢复 Gate 0 active 状态")
            if entry.get("fork_transaction_id") != fork_transaction_id:
                raise ValueError("profile_fork_rolled_back 的事务身份不匹配")
            if entry.get("child_run_id") != superseded_by_run_id:
                raise ValueError("profile_fork_rolled_back 的子 Run 身份不匹配")
            if not all(
                isinstance(entry.get(field), str) and str(entry[field]).strip()
                for field in ("reviewer", "reason")
            ):
                raise ValueError("profile_fork_rolled_back 缺少审核身份或原因")
            lifecycle_status = "active"
            superseded_by_run_id = None
            fork_transaction_id = None
            continue
        if completed or lifecycle_status != "active":
            raise ValueError("completed 终态之后不得再追加转换记录")
        if entry.get("state") == "revision_forked":
            if entry.get("event_type") != "revision_forked" or current is None:
                raise ValueError("revision_forked 事件非法")
            scope = entry.get("revision_scope")
            if scope not in {"diagnosis", "model_route", "formal_result"}:
                raise ValueError("revision_forked 的 revision_scope 非法")
            if not all(isinstance(entry.get(field), str) and str(entry[field]).strip() for field in ("child_run_id", "reviewer", "reason", "revision_transaction_id")):
                raise ValueError("revision_forked 缺少子 Run、审核人或原因")
            if entry.get("lifecycle_status") != "superseded":
                raise ValueError("revision_forked 必须将父 Run 标为 superseded")
            lifecycle_status = "superseded"
            superseded_by_run_id = str(entry["child_run_id"])
            revision_transaction_id = str(entry["revision_transaction_id"])
            continue
        if entry.get("state") == "profile_forked":
            if entry.get("event_type") != "profile_forked":
                raise ValueError("profile_forked 事件类型非法")
            if (
                current != 0
                or entry.get("completed_gate") is not None
                or entry.get("next_gate") is not None
            ):
                raise ValueError("profile_forked 只能在 Gate 0 尚未推进时发生")
            child_run_id = entry.get("child_run_id")
            transaction_id = entry.get("fork_transaction_id")
            selected_profile = entry.get("selected_profile")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (
                    child_run_id,
                    transaction_id,
                    selected_profile,
                    entry.get("reviewer"),
                    entry.get("reason"),
                )
            ):
                raise ValueError("profile_forked 事件缺少必填身份字段")
            if entry.get("lifecycle_status") != "superseded":
                raise ValueError("profile_forked 事件必须将 lifecycle_status 设为 superseded")
            lifecycle_status = "superseded"
            superseded_by_run_id = child_run_id
            fork_transaction_id = transaction_id
            continue
        decision = entry.get("decision")
        if decision not in ("approved", "rejected"):
            raise ValueError(f"第 {idx} 条 Gate 记录 decision 非法：{decision!r}")
        if not str(entry.get("reviewer", "")).strip():
            raise ValueError(f"第 {idx} 条 Gate 记录 reviewer 不能为空")

        state = entry.get("state")
        completed_gate = entry.get("completed_gate")
        next_gate = entry.get("next_gate")
        if state == "started_gate_0":
            if current is not None or completed_gate is not None or next_gate != 0:
                raise ValueError("started_gate_0 只能从初始化状态进入 Gate 0")
            if decision != "approved":
                raise ValueError("started_gate_0 必须为 approved")
            current = 0
            continue

        if state == "completed":
            if current != 5 or completed_gate != 5 or next_gate is not None:
                raise ValueError("completed 记录必须表达 completed_gate=5、next_gate=null")
            if decision != "approved":
                raise ValueError("completed 记录必须为 approved")
            if _is_gate_5_v2_run(run_dir):
                _validate_v2_completed_entry(run_dir, entry)
                completed_gates.append(5)
                completed = True
                completed_entry = entry
                current = None
                continue
            review_record = entry.get("review_record")
            review_sha = entry.get("review_record_sha256")
            if review_record != "gate_5_review.json":
                raise ValueError("completed 记录必须绑定 gate_5_review.json")
            if not isinstance(review_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", review_sha):
                raise ValueError("completed 记录缺少合法 review_record_sha256")
            if verify_artifacts:
                verify_gate_artifacts(run_dir, 5)
            _, actual_review_sha = _load_and_validate_gate_5_review(
                run_dir, str(entry["reviewer"])
            )
            if actual_review_sha != review_sha:
                raise ValueError("completed 记录绑定的 gate_5_review.json SHA-256 不匹配")
            completed_gates.append(5)
            completed = True
            completed_entry = entry
            current = None
            continue

        if current is None:
            raise ValueError(f"第 {idx} 条记录前尚未开始 Gate 0")
        expected_next = current + 1
        if completed_gate != current or next_gate != expected_next:
            raise ValueError(
                f"第 {idx} 条记录必须表达 completed_gate={current}、next_gate={expected_next}"
            )
        if next_gate > init_data["max_gate"]:
            raise ValueError(f"第 {idx} 条 Gate 记录超过 initialized.max_gate")
        if decision == "rejected":
            if state != f"rejected_gate_{current}":
                raise ValueError(f"第 {idx} 条拒绝记录 state 非法")
            continue
        if state != _completed_gate_state(run_manifest, current):
            raise ValueError(f"第 {idx} 条完成记录 state 非法")
        if verify_artifacts:
            verify_gate_artifacts(run_dir, current)
        completed_gates.append(current)
        current = next_gate

    return {
        "transition_version": TRANSITION_VERSION,
        "initialized": init_data,
        "current_gate": current,
        "completed_gates": completed_gates,
        "completed": completed,
        "completed_entry": completed_entry,
        "max_gate": init_data.get("max_gate"),
        "material_ready": init_data.get("material_ready"),
        "entries": entries,
        "lifecycle_status": lifecycle_status,
        "superseded_by_run_id": superseded_by_run_id,
        "fork_transaction_id": fork_transaction_id,
        "revision_transaction_id": revision_transaction_id,
    }


def replay_transition_log(
    run_dir: Path,
    *,
    verify_artifacts: bool = True,
) -> dict[str, Any]:
    """严格回放 Gate 状态机，返回当前状态。

    该函数是 Gate 完成度和终态标记的唯一事实来源：必须恰好一次 initialized，
    初始化必须在首条有效记录，approved 只能按 VALID_TRANSITIONS 前进，completed
    只能从 Gate 5 产生且必须绑定 gate_5_review.json 的 SHA-256。
    """
    transitions_path = run_dir / "transitions.jsonl"
    if not transitions_path.is_file():
        raise FileNotFoundError(f"缺少 transitions.jsonl：{transitions_path}")

    entries = _read_transition_entries(transitions_path)
    if not entries:
        raise ValueError("transitions.jsonl 为空，缺少 initialized 记录")

    init_entries = [entry for entry in entries if entry.get("state") == "initialized"]
    if len(init_entries) != 1:
        raise ValueError(f"transitions.jsonl 必须且只能包含 1 条 initialized 记录，实际 {len(init_entries)} 条")
    if entries[0].get("state") != "initialized":
        raise ValueError("initialized 必须是 transitions.jsonl 的第一条有效记录")

    init_data = entries[0]
    if init_data.get("from") is not None or init_data.get("to") is not None:
        raise ValueError("initialized 记录的 from/to 必须为 null")
    max_gate = init_data.get("max_gate")
    if not isinstance(max_gate, int) or max_gate < 0 or max_gate > 5:
        raise ValueError("initialized.max_gate 必须是 0-5 的整数")
    if init_data.get("material_ready") is not True and len(entries) > 1:
        raise ValueError("initialized.material_ready 不为 true，日志中不得出现 Gate 转换")
    transition_version = init_data.get("transition_version")
    if transition_version is not None:
        if transition_version != TRANSITION_VERSION:
            raise ValueError(f"不支持的 transition_version：{transition_version!r}")
        return _replay_v2_transition_log(
            run_dir,
            entries,
            verify_artifacts=verify_artifacts,
        )

    current: int | None = None
    completed = False
    completed_entry: dict[str, Any] | None = None
    for idx, entry in enumerate(entries[1:], start=2):
        state = entry.get("state")
        if state == "initialized":
            raise ValueError("initialized 记录不得重复出现")
        if completed:
            raise ValueError("completed 终态之后不得再追加转换记录")

        if state == "completed":
            if entry.get("from") != 5 or entry.get("to") is not None:
                raise ValueError("completed 记录必须从 Gate 5 转入终态，且 to 为 null")
            if current != 5:
                raise ValueError(f"completed 记录出现前当前 Gate 不是 5（当前：{current}）")
            if not str(entry.get("reviewer", "")).strip():
                raise ValueError("completed 记录 reviewer 不能为空")
            review_record = entry.get("review_record")
            review_sha = entry.get("review_record_sha256")
            if review_record != "gate_5_review.json":
                raise ValueError("completed 记录必须绑定 gate_5_review.json")
            if not isinstance(review_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", review_sha):
                raise ValueError("completed 记录缺少合法 review_record_sha256")
            try:
                _, actual_review_sha = _load_and_validate_gate_5_review(
                    run_dir,
                    str(entry["reviewer"]),
                )
            except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"completed 记录绑定的 gate_5_review.json 无效：{exc}") from exc
            if actual_review_sha != review_sha:
                raise ValueError("completed 记录绑定的 gate_5_review.json SHA-256 不匹配")
            completed = True
            completed_entry = entry
            continue

        decision = entry.get("decision")
        if decision not in ("approved", "rejected"):
            raise ValueError(f"第 {idx} 条 Gate 记录 decision 非法：{decision!r}")
        if not str(entry.get("reviewer", "")).strip():
            raise ValueError(f"第 {idx} 条 Gate 记录 reviewer 不能为空")
        from_gate = entry.get("from")
        to_gate = entry.get("to")
        if from_gate != current:
            raise ValueError(f"第 {idx} 条 Gate 记录 from={from_gate!r} 与当前 Gate {current!r} 不一致")
        if to_gate not in GATE_NAMES:
            raise ValueError(f"第 {idx} 条 Gate 记录 to 非法：{to_gate!r}")
        if not isinstance(to_gate, int) or to_gate > max_gate:
            raise ValueError(f"第 {idx} 条 Gate 记录超过 initialized.max_gate")
        valid_next = VALID_TRANSITIONS.get(current, set())
        if to_gate not in valid_next:
            expected = f"{{{', '.join(str(g) for g in sorted(valid_next))}}}" if valid_next else "（终点）"
            raise ValueError(f"Gate 转换非法：不能从 {current} 进入 Gate {to_gate}。允许的下一 Gate：{expected}。")
        expected_state = f"entering_gate_{to_gate}" if decision == "approved" else f"rejected_gate_{to_gate}"
        if state != expected_state:
            raise ValueError(f"第 {idx} 条 Gate 记录 state 应为 {expected_state!r}，实际 {state!r}")
        if decision == "approved":
            current = to_gate

    return {
        "transition_version": "1.0.0",
        "initialized": init_data,
        "current_gate": current,
        "completed": completed,
        "completed_entry": completed_entry,
        "max_gate": init_data.get("max_gate"),
        "material_ready": init_data.get("material_ready"),
        "completed_gates": list(range(6)) if completed else (
            list(range(current)) if current is not None else []
        ),
        "entries": entries,
        "lifecycle_status": "active",
        "superseded_by_run_id": None,
        "fork_transaction_id": None,
    }


def record_transition(run_dir: Path, from_gate: int | None, to_gate: int, reviewer: str, decision: str) -> None:
    """记录一次闸门推进事件，所有前置状态均通过 replay_transition_log 严格回放。"""
    if to_gate not in GATE_NAMES:
        raise ValueError(f"未知 Gate：{to_gate}（允许 0-5）")
    if not str(reviewer).strip():
        raise ValueError("reviewer 不能为空")
    if decision not in ("approved", "rejected"):
        raise ValueError(f"decision 必须为 approved 或 rejected，实际为 {decision!r}")

    state = replay_transition_log(run_dir)
    _assert_run_can_progress(run_dir, state)
    if state["completed"]:
        raise ValueError("运行已 completed，不能再记录 Gate 转换。")
    if state["material_ready"] is not True:
        raise ValueError(
            f"材料校验未通过（material_ready={state['material_ready']}），"
            "禁止进入任何 Gate。请先修复材料问题。"
        )
    if to_gate > state["max_gate"]:
        raise ValueError(f"不能进入 Gate {to_gate}，初始化声明的最大 Gate 为 {state['max_gate']}。")

    real_current = state["current_gate"]
    if from_gate != real_current:
        raise ValueError(
            f"from_gate 不匹配：调用方声称当前为 {from_gate}，"
            f"但 transitions.jsonl 记录的实际当前 Gate 为 {real_current}。禁止伪造跳跃。"
        )

    valid_next = VALID_TRANSITIONS.get(real_current, set())
    if to_gate not in valid_next:
        expected = f"{{{', '.join(str(g) for g in sorted(valid_next))}}}" if valid_next else "（终点）"
        raise ValueError(f"Gate 转换非法：不能从 {real_current} 进入 Gate {to_gate}。允许的下一 Gate：{expected}。")

    if state.get("transition_version") == TRANSITION_VERSION:
        if real_current is None:
            if decision != "approved":
                raise ValueError("v2 工作流开始 Gate 0 时 decision 必须为 approved")
            entry = {
                "transition_version": TRANSITION_VERSION,
                "completed_gate": None,
                "next_gate": 0,
                "state": "started_gate_0",
                "gate_name": GATE_NAMES[0],
                "reviewer": str(reviewer).strip(),
                "decision": decision,
            }
        else:
            if decision == "approved":
                verify_gate_artifacts(run_dir, real_current)
            entry = {
                "transition_version": TRANSITION_VERSION,
                "completed_gate": real_current,
                "next_gate": to_gate,
                "state": (
                    _completed_gate_state(
                        _load_json_object(
                            run_dir / "run_manifest.json", "run_manifest.json"
                        ),
                        real_current,
                    )
                    if decision == "approved"
                    else f"rejected_gate_{real_current}"
                ),
                "gate_name": GATE_NAMES[real_current],
                "reviewer": str(reviewer).strip(),
                "decision": decision,
            }
        _append_transition_event(run_dir / "transitions.jsonl", entry)
        return

    entry = {
        "from": real_current,
        "to": to_gate,
        "state": f"entering_gate_{to_gate}" if decision == "approved" else f"rejected_gate_{to_gate}",
        "gate_name": GATE_NAMES[to_gate],
        "reviewer": str(reviewer).strip(),
        "decision": decision,
    }
    with open(run_dir / "transitions.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def is_gate_complete(run_dir: Path, gate: int) -> bool:
    """检查指定 Gate 是否已完成并通过；伪造或损坏日志一律视为未完成。"""
    try:
        state = replay_transition_log(run_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return False
    if state["completed"]:
        return gate <= 5
    current = state["current_gate"]
    return current is not None and current > gate


def get_current_gate(run_dir: Path) -> int | None:
    """从 transitions.jsonl 严格回放当前所在 Gate；缺少日志时返回 None。"""
    try:
        state = replay_transition_log(run_dir)
    except FileNotFoundError:
        return None
    if state["completed"]:
        return None
    return state["current_gate"]


def _parse_datetime(value: Any, field: str) -> None:
    """校验 ISO 8601 时间字段；允许 Z 后缀。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"gate_5_review.{field} 不能为空")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"gate_5_review.{field} 不是合法 ISO 8601 时间") from exc


def _validate_gate_5_review_schema(review: dict[str, Any]) -> None:
    """以唯一 Schema 契约校验 Gate 5 审核记录，避免手工规则漂移。"""
    schema_path = ROOT / "schemas" / "gate_5_review.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(review),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError(f"gate_5_review.json 不符合 Schema：{details}")


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    """读取运行现场 JSON 对象；缺失、损坏或非对象均按闭锁失败处理。"""
    if not path.is_file():
        raise FileNotFoundError(f"缺少{label}：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是 JSON 对象")
    return value


def _load_current_run_binding(run_dir: Path) -> dict[str, str]:
    """从不可由审核文件替代的运行现场读取 Gate 5 身份绑定。"""
    run_manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    runtime_manifest = _load_json_object(
        run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json"
    )
    _validate_runtime_context_binding(run_manifest, runtime_manifest)

    binding: dict[str, Any] = {
        "run_id": run_manifest.get("run_id"),
        "problem_id": run_manifest.get("problem_id"),
        "profile": run_manifest.get("profile"),
        "runtime_version": run_manifest.get("runtime_version"),
        "runtime_pack_sha256": runtime_manifest.get("runtime_pack_sha256"),
    }
    for field, value in binding.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"当前运行现场缺少合法 {field}")

    runtime_pack_sha = str(binding["runtime_pack_sha256"])
    if not re.fullmatch(r"[a-f0-9]{64}", runtime_pack_sha):
        raise ValueError("runtime_pack.manifest.json.runtime_pack_sha256 非法")
    runtime_pack_path = run_dir / "runtime_pack.md"
    if not runtime_pack_path.is_file():
        raise FileNotFoundError(f"缺少 runtime_pack.md：{runtime_pack_path}")
    actual_runtime_pack_sha = sha256_bytes(runtime_pack_path.read_bytes())
    if actual_runtime_pack_sha != runtime_pack_sha:
        raise ValueError("runtime_pack.md SHA-256 与 runtime_pack.manifest.json 不一致")

    for field in ("profile", "runtime_version"):
        declared = runtime_manifest.get(field)
        if declared is not None and declared != binding[field]:
            raise ValueError(
                f"run_manifest.json.{field} 与 runtime_pack.manifest.json.{field} 不一致"
            )
    return {field: str(value) for field, value in binding.items()}


def _is_gate_5_v2_run(run_dir: Path) -> bool:
    """仅由 Run 初始化时冻结的版本字段启用 Gate 5 v2。"""
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    return manifest.get("gate_5_review_contract_version") == GATE_5_REVIEW_V2_CONTRACT_VERSION


def _gate_5_policy_for_run(run_dir: Path) -> str:
    """读取冻结的 Gate 5 策略，拒绝运行中临时改变审核要求。"""
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if manifest.get("gate_5_review_contract_version") != GATE_5_REVIEW_V2_CONTRACT_VERSION:
        raise ValueError("当前 Run 未启用 Gate 5 Review v2")
    policy = manifest.get("gate_5_policy_version")
    if policy not in {
        GATE_5_RECORDING_POLICY,
        "technical_required_v1",
        GATE_5_HUMAN_FINAL_TECHNICAL_POLICY,
        "technical_and_reader_required_v1",
    }:
        raise ValueError(f"gate_5_policy_version 非法：{policy!r}")
    return str(policy)


def _validate_sha256_reference(run_dir: Path, reference: Mapping[str, Any], label: str) -> None:
    """验证审核引用位于当前 Run 内且与声明哈希精确一致。"""
    path_text = reference.get("path")
    digest = reference.get("sha256")
    if not isinstance(path_text, str) or not path_text or not isinstance(digest, str):
        raise ValueError(f"{label} 必须包含 path 和 sha256")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError(f"{label}.sha256 非法")
    path = (run_dir / path_text).resolve()
    if not path.is_relative_to(run_dir.resolve()) or not path.is_file():
        raise ValueError(f"{label}.path 不存在或越出当前 Run")
    if sha256_bytes(path.read_bytes()) != digest:
        raise ValueError(f"{label}.sha256 与现场文件不一致")


def _expected_fixed_gate4_candidate(run_dir: Path) -> tuple[str, str]:
    """以现有 Gate 4 manifest 的完整文件哈希生成确定性过渡候选身份。"""
    manifest_path = run_dir / "gate_artifacts" / "gate_4.manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("fixed_gate4_v1 需要已存在的 gate_artifacts/gate_4.manifest.json")
    digest = sha256_bytes(manifest_path.read_bytes())
    return f"LEGACY-PC-{digest}", digest


def _require_gate_f_ready_for_handoff(run_dir: Path) -> None:
    """题目专用 Gate F 已启用时，F2/F3 状态必须先通过。"""
    contract_path = run_dir / "paper_content_contract.yaml"
    status_path = run_dir / "paper_gate_f_status.json"
    manifest = (
        _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
        if (run_dir / "run_manifest.json").is_file()
        else {}
    )
    if not contract_path.is_file() and manifest.get("paper_pipeline_contract_version") is None:
        return
    if not contract_path.is_file():
        if (
            manifest.get("legacy_paper_content_policy") is True
            and manifest.get("paper_pipeline_contract_version") is None
        ):
            return
        raise ValueError("新 Run 缺少 paper_content_contract.yaml，禁止绕过 Gate F")
    if not status_path.is_file():
        raise ValueError("已绑定题目专用 Gate F 合同，但缺少 paper_gate_f_status.json")
    status = _load_json_object(status_path, "paper_gate_f_status.json")
    if status.get("status") != "independent_paper_review_passed" or status.get("eligible_for_gate_g") is not True:
        raise ValueError("Gate F 尚未通过 F1/F2/F3，禁止生成最终人工终审交接包或进入 Gate G")
    review = status.get("f3_review")
    if not isinstance(review, Mapping):
        raise ValueError("Gate F 通过状态缺少 F3 审核记录")
    try:
        from paper.gate_f_status import validate_f3_review_references
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.paper.gate_f_status import validate_f3_review_references
    validate_f3_review_references(run_dir, review)


def _validate_gate_5_v2_review(run_dir: Path, review: dict[str, Any]) -> None:
    """验证 v2 最终决策、候选绑定和 recording-only 策略语义。"""
    _validate_json_schema(review, "schemas/gate_5_review_v2.schema.json", "gate_5_review_v2")
    binding = _load_current_run_binding(run_dir)
    _require_gate_f_ready_for_handoff(run_dir)
    for field, expected in binding.items():
        if review.get(field) != expected:
            raise ValueError(f"gate_5_review_v2.{field} 与当前运行现场不一致")
    policy = _gate_5_policy_for_run(run_dir)
    if review.get("policy_version") != policy:
        raise ValueError("gate_5_review_v2.policy_version 与 Run 冻结策略不一致")
    _parse_datetime(review.get("reviewed_at"), "gate_5_review_v2.reviewed_at")

    binding_version = review.get("candidate_binding_version")
    if binding_version == "fixed_gate4_v1":
        expected_id, expected_sha = _expected_fixed_gate4_candidate(run_dir)
        if review.get("candidate_id") != expected_id or review.get("candidate_manifest_sha256") != expected_sha:
            raise ValueError("fixed_gate4_v1 的 candidate_id 或 candidate_manifest_sha256 与 Gate 4 manifest 不一致")
    elif binding_version == "versioned_candidate_v2":
        candidate = current_candidate(run_dir)
        if review.get("candidate_id") != candidate["candidate_id"] or review.get("candidate_manifest_sha256") != candidate["candidate_manifest_sha256"]:
            raise ValueError("versioned_candidate_v2 必须绑定当前 Candidate")
    else:  # Schema 已限制，这里保留防御性错误文本。
        raise ValueError("candidate_binding_version 非法")

    checklist = review["checklist"]
    failed_keys = [key for key in GATE_5_CHECKLIST_KEYS if checklist[key]["status"] == "failed"]
    not_applicable = [key for key in GATE_5_CHECKLIST_KEYS if checklist[key]["status"] == "not_applicable"]
    if policy == GATE_5_RECORDING_POLICY and not_applicable:
        raise ValueError("recording_only_v1 的必填 checklist 不得使用 not_applicable")
    blocking = [issue for issue in review["issues"] if issue["severity"] == "blocking"]
    decision = review["decision"]
    requested_scope = review["requested_revision_scope"]
    if decision == "approved":
        if failed_keys or not_applicable:
            raise ValueError("approved 的全部 checklist 必须为 passed")
        if blocking:
            raise ValueError("approved 不得包含 blocking issue")
        if review["required_actions"]:
            raise ValueError("approved.required_actions 必须为空")
        if requested_scope is not None:
            raise ValueError("approved.requested_revision_scope 必须为 null")
        restrictions = review["claim_restrictions"] + review["required_limitations"]
        if restrictions:
            # PR 2 只有 fixed_gate4_v1 过渡绑定，尚无可验证的候选版本与 Claim Map 闭合协议。
            # 在 PR 5 交付该协议前，禁止以“带限制通过”绕过最终证据闭合。
            raise ValueError("recording_only_v1 暂不允许 approved 携带未验证的限制")
    elif decision == "needs_revision":
        if not failed_keys and not blocking:
            raise ValueError("needs_revision 至少需要 failed checklist 或 blocking issue")
        if not review["required_actions"]:
            raise ValueError("needs_revision 必须提供 required_actions")
        if requested_scope not in {"paper_candidate", "model_route", "formal_result", "diagnosis"}:
            raise ValueError("needs_revision.requested_revision_scope 非法")
    elif decision == "rejected":
        if not blocking:
            raise ValueError("rejected 必须包含 blocking issue")
        if requested_scope != "terminal_rejection":
            raise ValueError("rejected.requested_revision_scope 必须为 terminal_rejection")
    else:  # Schema 已限制，这里保留防御性错误文本。
        raise ValueError("gate_5_review_v2.decision 非法")

    for index, reference in enumerate(review["restriction_closure_refs"], start=1):
        _validate_sha256_reference(run_dir, reference, f"restriction_closure_refs[{index}]")
    for item in checklist.values():
        for index, reference in enumerate(item["evidence_refs"], start=1):
            _validate_sha256_reference(run_dir, reference, f"checklist.evidence_refs[{index}]")
    supporting = review["supporting_reviews"]
    for index, reference in enumerate(supporting, start=1):
        _validate_sha256_reference(run_dir, reference, f"supporting_reviews[{index}]")
    candidate = {"candidate_id": str(review["candidate_id"]), "candidate_manifest_sha256": str(review["candidate_manifest_sha256"])}
    if decision == "approved" and policy in {"technical_required_v1", GATE_5_HUMAN_FINAL_TECHNICAL_POLICY}:
        if len(supporting) != 1:
            raise ValueError("技术审核策略必须且只能引用一个 Technical Review")
        approved_supporting_review(run_dir, supporting[0], kind="technical", candidate=candidate)
        if policy == GATE_5_HUMAN_FINAL_TECHNICAL_POLICY and review["reviewer"].get("type") != "human":
            raise ValueError("human_final_technical_required_v1 的 approved Gate 5 必须由人工决策")
    if decision == "approved" and policy == "technical_and_reader_required_v1":
        if len(supporting) != 2:
            raise ValueError("technical_and_reader_required_v1 必须引用 Technical Review 与 Paper Reader Review")
        technical = [item for item in supporting if str(item.get("path", "")).startswith("reviews/technical/")]
        reader = [item for item in supporting if str(item.get("path", "")).startswith("reviews/paper_reader/")]
        if len(technical) != 1 or len(reader) != 1:
            raise ValueError("Gate 5 supporting_reviews 角色不完整或重复")
        approved_supporting_review(run_dir, technical[0], kind="technical", candidate=candidate)
        approved_supporting_review(run_dir, reader[0], kind="paper_reader", candidate=candidate, require_enforced=True)


def _reconcile_gate_5_review_history(run_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    """恢复崩溃后已发布但尚未写入 history 的 Gate 5 审核文件。"""
    return reconcile_orphan_reviews(
        run_dir,
        review_directory=GATE_5_REVIEW_DIRECTORY,
        history_filename=GATE_5_REVIEW_HISTORY_FILENAME,
        validate_review=lambda review: _validate_gate_5_v2_review(run_dir, review),
    )


def _load_gate_5_v2_review(run_dir: Path, review_id: str) -> tuple[dict[str, Any], str, str]:
    """读取指定不可变 Gate 5 审核，返回内容、相对路径和文件哈希。"""
    if not re.fullmatch(r"G5R-[A-Za-z0-9_-]{8,120}", review_id):
        raise ValueError("approved_review_id 非法")
    path = run_dir / GATE_5_REVIEW_DIRECTORY / f"{review_id}.json"
    review = _load_json_object(path, f"Gate 5 Review {review_id}")
    _validate_gate_5_v2_review(run_dir, review)
    if review.get("review_id") != review_id:
        raise ValueError("Gate 5 Review 文件名与 review_id 不一致")
    raw = path.read_bytes()
    return review, path.relative_to(run_dir).as_posix(), sha256_bytes(raw)


def _rebuild_v2_gate_5_evidence(run_dir: Path) -> dict[str, Any]:
    """重建未封存阶段的 v2 Evidence，确保失败审核也被保留。"""
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    evidence = build_run_evidence_manifest(run_dir, str(manifest["run_id"]))
    write_json(run_dir / "run_evidence_manifest.json", evidence)
    return evidence


def _current_approved_technical_review(
    run_dir: Path, candidate: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, str], str | None]:
    """读取当前 Candidate 的最新 Technical Review，并拒绝旧候选或失败结论。"""
    entries, history_head = verify_review_history(run_dir, "technical_review_history.jsonl")
    if not entries:
        raise ValueError("缺少 Technical Review，不能生成人工终审交接包")
    entry = entries[-1]
    if (
        entry.get("candidate_id") != candidate["candidate_id"]
        or entry.get("candidate_manifest_sha256")
        != candidate["candidate_manifest_sha256"]
    ):
        raise ValueError("最新 Technical Review 未绑定当前 Candidate，不能交接人工终审")
    path_text = str(entry["path"])
    review_path = run_dir / path_text
    review = _load_json_object(review_path, "最新 Technical Review")
    _validate_json_schema(review, "schemas/technical_review.schema.json", "最新 Technical Review")
    if review.get("review_id") != entry.get("review_id"):
        raise ValueError("最新 Technical Review 的 review_id 与不可变 history 不一致")
    if review.get("decision") != entry.get("decision"):
        raise ValueError("最新 Technical Review 的 decision 与不可变 history 不一致")
    if review.get("decision") != "approved":
        raise ValueError("最新 Technical Review 未通过，不能交接人工终审")
    reference = {
        "review_id": str(entry["review_id"]),
        "path": path_text,
        "sha256": str(entry["sha256"]),
        "decision": "approved",
        "candidate_id": candidate["candidate_id"],
        "candidate_manifest_sha256": candidate["candidate_manifest_sha256"],
    }
    approved_supporting_review(run_dir, reference, kind="technical", candidate=candidate)
    return review, reference, history_head


def _render_human_final_review_dossier(
    run_binding: Mapping[str, str],
    candidate_manifest: Mapping[str, Any],
    candidate_manifest_ref: Mapping[str, str],
    technical_review: Mapping[str, Any],
    technical_reference: Mapping[str, str],
    technical_history_head: str | None,
) -> str:
    """生成只读交接摘要；它明确不代表任何人工最终结论。"""
    source_files = candidate_manifest.get("source_files", [])
    source_lines = "\n".join(
        f"- `{item['path']}`：`{item['sha256']}`"
        for item in source_files
    ) or "- 当前 Candidate 未登记源文件。"
    return (
        "# 人工 Gate 5 终审交接包\n\n"
        "本文件仅用于人工读取和核验，不是 Gate 5 决策，也不表示任何人已经批准。\n\n"
        "## 当前运行\n\n"
        f"- Run：`{run_binding['run_id']}`\n"
        f"- 题目：`{run_binding['problem_id']}`\n"
        f"- Profile：`{run_binding['profile']}`\n"
        f"- Runtime：`{run_binding['runtime_version']}`\n"
        f"- Runtime Pack SHA-256：`{run_binding['runtime_pack_sha256']}`\n\n"
        "## 不可变 Candidate\n\n"
        f"- Candidate：`{candidate_manifest_ref['candidate_id']}`\n"
        f"- Manifest：`{candidate_manifest_ref['path']}`\n"
        f"- Manifest SHA-256：`{candidate_manifest_ref['sha256']}`\n"
        f"- 产生原因：{candidate_manifest.get('reason', '未记录')}\n"
        f"- 父 Candidate：`{candidate_manifest.get('parent_candidate_id') or '无'}`\n\n"
        "Candidate 源文件：\n\n"
        f"{source_lines}\n\n"
        "## 已通过的 Technical Review\n\n"
        f"- Review：`{technical_reference['review_id']}`\n"
        f"- 文件：`{technical_reference['path']}`\n"
        f"- 文件 SHA-256：`{technical_reference['sha256']}`\n"
        f"- 审核者类型：`{technical_review['reviewer']['type']}`\n"
        f"- 审核者标识：`{technical_review['reviewer']['identity']}`\n"
        f"- 审核时间：`{technical_review['reviewed_at']}`\n"
        f"- Technical Review history 链头：`{technical_history_head or '空'}`\n\n"
        "## 人工操作\n\n"
        "人工应独立核对上述 Candidate、技术审核及其证据后，再填写同目录的 "
        "`gate_5_review.human-input.template.json`。模板刻意不符合 Gate 5 Schema，"
        "不能直接提交；删除模板提示并填写真实身份、时间、结论、检查项和证据后，"
        "再使用 `record-gate5-review` 保存最终决策。\n\n"
        "若结论为 `needs_revision`，Agent 必须产生新 Candidate，并重新进行 AI/Technical Review，"
        "不得继续使用本交接包批准旧 Candidate。\n"
    )


def _human_final_review_template(
    run_binding: Mapping[str, str], candidate: Mapping[str, str], technical_reference: Mapping[str, str]
) -> dict[str, Any]:
    """生成不可直接提交的人工输入模板，固定不可变 Candidate 与 Technical Review 引用。"""
    checklist = {
        key: {
            "status": "__REQUIRED_passed_or_failed__",
            "reason": "__REQUIRED_human_rationale__",
            "evidence_refs": [],
        }
        for key in GATE_5_CHECKLIST_KEYS
    }
    return {
        "_template_notice": (
            "此文件不是 Gate 5 审核记录，不能直接提交。删除本字段并填写所有 __REQUIRED__ "
            "占位符后，方可交给 record-gate5-review。"
        ),
        "schema_version": GATE_5_REVIEW_V2_CONTRACT_VERSION,
        "artifact_type": "gate_5_review",
        "review_id": "__REQUIRED_HUMAN_REVIEW_ID__",
        "review_type": "final_decision",
        "policy_version": GATE_5_HUMAN_FINAL_TECHNICAL_POLICY,
        "attempt": 0,
        **dict(run_binding),
        **dict(candidate),
        "candidate_binding_version": "versioned_candidate_v2",
        "reviewer": {
            "type": "human",
            "identity": "__REQUIRED_HUMAN_IDENTITY__",
            "session_id": "__OPTIONAL_HUMAN_SESSION_ID_OR_NULL__",
        },
        "reviewed_at": "__REQUIRED_RFC3339_TIMESTAMP__",
        "decision": "__REQUIRED_approved_needs_revision_or_rejected__",
        "reason": "__REQUIRED_HUMAN_FINAL_RATIONALE__",
        "checklist": checklist,
        "issues": [],
        "required_actions": [],
        "claim_restrictions": [],
        "required_limitations": [],
        "restriction_closure_refs": [],
        "requested_revision_scope": "__REQUIRED_NULL_OR_REVISION_SCOPE__",
        "supporting_reviews": [dict(technical_reference)],
    }


def prepare_human_final_review_handoff(run_dir: Path) -> dict[str, Any]:
    """生成绑定当前 Candidate 的人工 Gate 5 交接包，不写入审批或状态转换。"""
    with acquire_run_write_lock(run_dir):
        policy = _gate_5_policy_for_run(run_dir)
        if policy != GATE_5_HUMAN_FINAL_TECHNICAL_POLICY:
            raise ValueError(
                "prepare-human-final-review-handoff 仅支持 human_final_technical_required_v1"
            )
        _require_gate_f_ready_for_handoff(run_dir)
        run_binding = _load_current_run_binding(run_dir)
        candidate = current_candidate(run_dir)
        candidate_manifest_path = (
            run_dir / "paper_candidates" / candidate["candidate_id"] / "paper_candidate_manifest.json"
        )
        candidate_manifest = _load_json_object(candidate_manifest_path, "当前 Candidate Manifest")
        _validate_json_schema(
            candidate_manifest, "schemas/review_candidate_manifest.schema.json", "当前 Candidate Manifest"
        )
        candidate_manifest_ref = {
            "candidate_id": candidate["candidate_id"],
            "path": candidate_manifest_path.relative_to(run_dir).as_posix(),
            "sha256": candidate["candidate_manifest_sha256"],
        }
        if sha256_bytes(candidate_manifest_path.read_bytes()) != candidate_manifest_ref["sha256"]:
            raise ValueError("当前 Candidate Manifest 的哈希与 current_paper_candidate 不一致")
        technical_review, technical_reference, technical_history_head = _current_approved_technical_review(
            run_dir, candidate
        )
        handoff_digest = sha256_bytes(
            (
                f"{candidate['candidate_id']}:{candidate['candidate_manifest_sha256']}:"
                f"{technical_reference['review_id']}:{technical_reference['sha256']}"
            ).encode("utf-8")
        )
        handoff_dir = run_dir / HUMAN_FINAL_REVIEW_HANDOFF_DIRECTORY / f"HFR-{handoff_digest[:16]}"
        relative_handoff_dir = handoff_dir.relative_to(run_dir).as_posix()
        template_name = "gate_5_review.human-input.template.json"
        dossier_name = "human_final_review_dossier.md"
        manifest_name = "handoff_manifest.json"

        expected_binding = {
            "handoff_contract_version": HUMAN_FINAL_REVIEW_HANDOFF_VERSION,
            "run_id": run_binding["run_id"],
            "candidate": candidate_manifest_ref,
            "technical_review": technical_reference,
            "technical_review_history_head_sha256": technical_history_head,
            "status": "pending_human_final_decision",
        }
        if handoff_dir.exists():
            manifest = _load_json_object(handoff_dir / manifest_name, "既有人工终审交接包")
            for field, expected in expected_binding.items():
                if manifest.get(field) != expected:
                    raise ValueError("既有人工终审交接包与当前 Candidate 或 Technical Review 绑定不一致")
            outputs = manifest.get("outputs")
            if not isinstance(outputs, Mapping):
                raise ValueError("既有人工终审交接包缺少 outputs")
            for filename in (dossier_name, template_name):
                path = handoff_dir / filename
                if not path.is_file() or outputs.get(filename) != sha256_bytes(path.read_bytes()):
                    raise ValueError("既有人工终审交接包文件缺失或哈希不一致")
            return {
                "handoff_dir": relative_handoff_dir,
                "dossier": f"{relative_handoff_dir}/{dossier_name}",
                "template": f"{relative_handoff_dir}/{template_name}",
                "manifest": f"{relative_handoff_dir}/{manifest_name}",
                "reused": True,
            }

        template = _human_final_review_template(run_binding, candidate, technical_reference)
        dossier = _render_human_final_review_dossier(
            run_binding,
            candidate_manifest,
            candidate_manifest_ref,
            technical_review,
            technical_reference,
            technical_history_head,
        )
        staging_dir = handoff_dir.parent / f".{handoff_dir.name}.{secrets.token_hex(8)}.staging"
        try:
            staging_dir.mkdir(parents=True, exist_ok=False)
            dossier_path = staging_dir / dossier_name
            template_path = staging_dir / template_name
            atomic_write_text(dossier_path, dossier)
            write_json(template_path, template)
            manifest = {
                **expected_binding,
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "outputs": {
                    dossier_name: sha256_bytes(dossier_path.read_bytes()),
                    template_name: sha256_bytes(template_path.read_bytes()),
                },
            }
            write_json(staging_dir / manifest_name, manifest)
            staging_dir.replace(handoff_dir)
        except Exception:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            raise
        return {
            "handoff_dir": relative_handoff_dir,
            "dossier": f"{relative_handoff_dir}/{dossier_name}",
            "template": f"{relative_handoff_dir}/{template_name}",
            "manifest": f"{relative_handoff_dir}/{manifest_name}",
            "reused": False,
        }


def record_gate_5_review(run_dir: Path, review: Mapping[str, Any]) -> dict[str, Any]:
    """保存 Gate 5 最终决策；失败审核只入账，不推进 Gate 或完成 Run。"""
    if not _is_gate_5_v2_run(run_dir):
        raise ValueError("历史 v1 Run 不支持 record_gate_5_review；请继续使用 gate_5_review.json")
    with acquire_run_write_lock(run_dir):
        state = replay_transition_log(run_dir)
        _assert_run_can_progress(run_dir, state)
        if state["completed"] or state["current_gate"] != 5:
            raise ValueError("只有处于 Gate 5 的未完成 Run 可以记录最终审核")
        if (run_dir / "gate_5_completion_journal.json").is_file():
            raise ValueError("Gate 5 完成事务进行中，禁止新增审核记录")
        result = append_immutable_review(
            run_dir,
            review,
            review_directory=GATE_5_REVIEW_DIRECTORY,
            history_filename=GATE_5_REVIEW_HISTORY_FILENAME,
            validate_review=lambda value: _validate_gate_5_v2_review(run_dir, value),
        )
        _rebuild_v2_gate_5_evidence(run_dir)
        return result


def _validate_v2_gate_5_evidence(run_dir: Path, evidence: Mapping[str, Any]) -> None:
    """确认 Evidence 完整保留 history 及每一份不可变 Gate 5 审核。"""
    entries, history_head = verify_review_history(run_dir, GATE_5_REVIEW_HISTORY_FILENAME)
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("run_evidence_manifest.artifacts 必须是数组")
    by_role = {item.get("role"): item for item in artifacts if isinstance(item, dict)}
    history_artifact = by_role.get("gate_5_review_history")
    history_path = run_dir / GATE_5_REVIEW_HISTORY_FILENAME
    if not isinstance(history_artifact, dict) or history_artifact.get("sha256") != sha256_bytes(history_path.read_bytes()):
        raise ValueError("Evidence 未精确绑定 gate_5_review_history.jsonl")
    for entry in entries:
        review_id = str(entry["review_id"])
        role = f"gate_5_review_record:{review_id}"
        artifact = by_role.get(role)
        if not isinstance(artifact, dict):
            raise ValueError(f"Evidence 缺少 Gate 5 Review：{review_id}")
        if artifact.get("path") != entry["path"] or artifact.get("sha256") != entry["sha256"]:
            raise ValueError(f"Evidence 对 Gate 5 Review {review_id} 的绑定不一致")
    if history_head is None and entries:
        raise ValueError("Gate 5 history 链头缺失")


def _validate_v2_completed_entry(run_dir: Path, entry: Mapping[str, Any]) -> None:
    """重放 completed 事件时重验最终 Review、history、Evidence 和 Gate 5 清单。"""
    review_id = entry.get("approved_review_id")
    if not isinstance(review_id, str):
        raise ValueError("completed 记录缺少 approved_review_id")
    review, relative, review_sha = _load_gate_5_v2_review(run_dir, review_id)
    if review["decision"] != "approved":
        raise ValueError("completed 记录绑定的 Gate 5 Review 必须为 approved")
    if entry.get("review_record") != relative or entry.get("review_record_sha256") != review_sha:
        raise ValueError("completed 记录绑定的 Gate 5 Review 路径或 SHA-256 不匹配")
    if entry.get("reviewer") != review["reviewer"]["identity"]:
        raise ValueError("completed 记录 reviewer 与 Gate 5 Review 不一致")
    history_entries, history_head = verify_review_history(run_dir, GATE_5_REVIEW_HISTORY_FILENAME)
    history_path = run_dir / GATE_5_REVIEW_HISTORY_FILENAME
    if entry.get("review_history_sha256") != sha256_bytes(history_path.read_bytes()):
        raise ValueError("completed 记录绑定的 Gate 5 history SHA-256 不匹配")
    if entry.get("review_history_head_sha256") != history_head:
        raise ValueError("completed 记录绑定的 Gate 5 history 链头不匹配")
    if not any(item.get("review_id") == review_id and item.get("sha256") == review_sha for item in history_entries):
        raise ValueError("completed 记录绑定的 Gate 5 Review 未进入 history")
    evidence_path = run_dir / "run_evidence_manifest.json"
    evidence_sha = sha256_bytes(evidence_path.read_bytes())
    if entry.get("evidence_manifest_sha256") != evidence_sha:
        raise ValueError("completed 记录绑定的 Evidence Manifest SHA-256 不匹配")
    evidence = _load_json_object(evidence_path, "run_evidence_manifest.json")
    _validate_v2_gate_5_evidence(run_dir, evidence)
    verify_gate_artifacts(run_dir, 5)


def _validate_runtime_context_binding(
    run_manifest: Mapping[str, Any], runtime_manifest: Mapping[str, Any]
) -> None:
    """验证运行包上下文与 Run workflow 的一对一绑定。"""
    workflow = run_manifest.get("workflow")
    if not isinstance(workflow, str) or workflow not in RUNTIME_CONTRACTS:
        raise ValueError(f"run_manifest.workflow 非法：{workflow!r}")
    manifest_version = runtime_manifest.get("manifest_version")
    if manifest_version == "1.1.0":
        if workflow != "full_replay":
            raise ValueError("runtime pack manifest 1.1.0 只支持历史 full_replay")
        if "workflow_context" in runtime_manifest or "runtime_contract" in runtime_manifest:
            raise ValueError("runtime pack manifest 1.1.0 不得携带 1.2.0 上下文字段")
        return
    if manifest_version not in {"1.2.0", "1.3.0"}:
        raise ValueError(f"runtime pack manifest_version 不支持：{manifest_version!r}")
    if manifest_version == "1.3.0":
        if runtime_manifest.get("gate_contract_version") != V21_GATE_CONTRACT_VERSION:
            raise ValueError("Runtime 1.3.0 未绑定 Gate Contract 2.1.0")
        if runtime_manifest.get("model_route_schema_version") != "2.1.0":
            raise ValueError("Runtime 1.3.0 未绑定 model_route 2.1.0")
        if run_manifest.get("runtime_manifest_version") != "1.3.0":
            raise ValueError("run_manifest 未绑定 Runtime Manifest 1.3.0")
        for field in ("classification", "blind_generalization", "profile_promotion_eligible"):
            if run_manifest.get(field) != runtime_manifest.get(field):
                raise ValueError(f"run_manifest.{field} 与 Runtime 1.3.0 不一致")
    if runtime_manifest.get("workflow_context") != workflow:
        raise ValueError(
            "runtime_pack.manifest.json.workflow_context 与 run_manifest.workflow 不一致"
        )
    contract = runtime_manifest.get("runtime_contract")
    if not isinstance(contract, Mapping):
        raise ValueError("runtime_pack.manifest.json.runtime_contract 非法")
    if contract.get("path") != RUNTIME_CONTRACTS[workflow]:
        raise ValueError(
            "runtime_pack.manifest.json.runtime_contract 与 workflow_context 不一致"
        )


def verify_run_seal(run_dir: Path) -> dict[str, Any]:
    """验证 v2 封存记录与三个被封存文件的现场哈希。"""
    seal = _load_json_object(run_dir / "seal_record.json", "seal_record.json")
    _validate_json_schema(seal, "schemas/run_seal.schema.json", "seal_record.json")
    run_manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if seal.get("run_id") != run_manifest.get("run_id"):
        raise ValueError("seal_record.run_id 与 run_manifest.run_id 不一致")
    formal_policy = _formal_result_policy(run_manifest)
    if formal_policy == FORMAL_RESULT_POLICY_REQUIRED:
        for field, expected in FORMAL_IDENTITY_DEFAULTS.items():
            if seal.get(field) != expected or run_manifest.get(field) != expected:
                raise ValueError(f"seal_record.{field} 未绑定当前 required_v1 不可变身份")
        summary = _verify_required_formal_result(run_dir)
        expected_formal = {
            "formal_result_id": summary["formal_result_id"],
            "formal_result_envelope_sha256": summary["envelope_file_sha256"],
            "formal_result_envelope_semantic_sha256": summary["envelope_semantic_sha256"],
            **formal_result_state_summary(summary),
        }
        environment = summary["sandboxie_environment"]
        if environment["sandboxie_environment_verified"]:
            expected_formal.update(
                {
                    "sandboxie_environment_report_id": environment["report_id"],
                    "sandboxie_environment_report_sha256": environment[
                        "report_file_sha256"
                    ],
                    "sandboxie_environment_report_semantic_sha256": environment[
                        "report_semantic_sha256"
                    ],
                    "sandboxie_environment_attestation_sha256": environment[
                        "attestation_file_sha256"
                    ],
                    "sandboxie_environment_attestation_semantic_sha256": environment[
                        "attestation_semantic_sha256"
                    ],
                    "sandboxie_environment_original_report_sha256": environment[
                        "original_report_sha256"
                    ],
                    "sandboxie_environment_fingerprint": environment[
                        "environment_fingerprint"
                    ],
                    "sandboxie_environment_machine_key_id": environment[
                        "machine_key_id"
                    ],
                    "sandboxie_configuration_backup_sha256": environment[
                        "configuration_backup_sha256"
                    ],
                    "trusted_environment_registry_sha256": environment[
                        "trusted_registry_sha256"
                    ],
                    "trusted_environment_key_entry_semantic_sha256": environment[
                        "trusted_key_entry_semantic_sha256"
                    ],
                }
            )
            if environment.get("formal_result_executed_in_verified_environment"):
                expected_formal.update(
                    {
                        "sandboxie_run_execution_attestation_sha256": environment[
                            "run_attestation_file_sha256"
                        ],
                        "sandboxie_run_execution_attestation_semantic_sha256": environment[
                            "run_attestation_semantic_sha256"
                        ],
                        "sandboxie_execution_id": environment["execution_id"],
                    }
                )
        for field, expected in expected_formal.items():
            if seal.get(field) != expected:
                raise ValueError(f"seal_record.{field} 与当前 Formal Result 不一致")
    elif formal_policy == FORMAL_RESULT_POLICY_REHEARSAL:
        for field, expected in _formal_identity_defaults(formal_policy).items():
            if seal.get(field) != expected or run_manifest.get(field) != expected:
                raise ValueError(f"seal_record.{field} 未绑定本机演练不可变身份")
        expected_unqualified = {
            "formal_result_activation_status": "code_complete_candidate",
            "sandboxie_environment_observed": False,
            "sandboxie_environment_verified": False,
            "formal_result_executed_in_verified_environment": False,
            "formal_result_eligible": False,
            "execution_trust_model": "direct_local_unqualified",
        }
        for field, expected in expected_unqualified.items():
            if seal.get(field) != expected:
                raise ValueError(f"seal_record.{field} 违反本机演练非资格边界")

    if _is_gate_5_v2_run(run_dir):
        state = replay_transition_log(run_dir)
        completed_entry = state.get("completed_entry") or {}
        expected_gate_5 = {
            "gate_5_review_contract_version": GATE_5_REVIEW_V2_CONTRACT_VERSION,
            "gate_5_policy_version": run_manifest.get("gate_5_policy_version"),
            "approved_review_id": completed_entry.get("approved_review_id"),
            "approved_review_sha256": completed_entry.get("review_record_sha256"),
            "gate_5_review_history_sha256": completed_entry.get("review_history_sha256"),
            "gate_5_review_history_head_sha256": completed_entry.get("review_history_head_sha256"),
        }
        for field, expected in expected_gate_5.items():
            if seal.get(field) != expected:
                raise ValueError(f"seal_record.{field} 与 Gate 5 v2 完成记录不一致")

    sealed_files = {
        "run_manifest_sha256": run_dir / "run_manifest.json",
        "transitions_sha256": run_dir / "transitions.jsonl",
        "evidence_manifest_sha256": run_dir / "run_evidence_manifest.json",
    }
    for field, path in sealed_files.items():
        if not path.is_file():
            raise FileNotFoundError(f"seal_record 引用文件不存在：{path.name}")
        actual = sha256_bytes(path.read_bytes())
        if seal.get(field) != actual:
            raise ValueError(f"seal_record.{field} 与现场文件不一致")
    return seal


def _validate_json_schema(data: dict[str, Any], schema_relative: str, label: str) -> None:
    """按仓库内 Draft 2020-12 Schema 校验对象并汇总全部字段错误。"""
    schema_path = ROOT / schema_relative
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "；".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
            for error in errors
        )
        raise ValueError(f"{label} 不符合 Schema：{details}")


def _validate_gate_business_artifact(
    run_dir: Path,
    filename: str,
    role: str,
    schema_relative: str,
    schema_version: str,
    binding: Mapping[str, str],
) -> bytes:
    """校验单个 Gate 业务产物的结构、身份、类型和内容，返回原始字节。"""
    path = run_dir / filename
    raw = path.read_bytes() if path.is_file() else b""
    if not raw:
        raise ValueError(f"Gate 产物缺失或为空：{filename}")
    try:
        artifact = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Gate 产物 {filename} 无法解析：{exc}") from exc
    if not isinstance(artifact, dict):
        raise ValueError(f"Gate 产物 {filename} 必须是 JSON 对象")
    _validate_json_schema(artifact, schema_relative, filename)

    if role in V21_ARTIFACT_ROLES:
        if role != "gate_5_review" and artifact.get("artifact_type") != role:
            raise ValueError(f"{filename}.artifact_type 必须为 {role}")
        if role != "gate_5_review" and artifact.get("schema_version") != schema_version:
            raise ValueError(f"{filename}.schema_version 必须为 {schema_version}")
        declared_run = artifact.get("run_id")
        if declared_run is not None and declared_run != binding.get("run_id"):
            raise ValueError(f"{filename}.run_id 与当前运行现场不一致")
        return raw

    for field, expected in binding.items():
        if artifact.get(field) != expected:
            raise ValueError(f"{filename}.{field} 与当前运行现场不一致")
    if role != "gate_5_review":
        if artifact.get("artifact_type") != role:
            raise ValueError(f"{filename}.artifact_type 必须为 {role}")
        if artifact.get("schema_version") != schema_version:
            raise ValueError(f"{filename}.schema_version 必须为 {schema_version}")
    return raw


def build_gate_artifact_manifest(
    run_dir: Path,
    gate: int,
    *,
    completed_at: str | None = None,
    approved_review_id: str | None = None,
) -> dict[str, Any]:
    """从已完成业务产物构建单 Gate 身份与哈希清单。"""
    if gate not in GATE_ARTIFACT_SPECS:
        raise ValueError(f"未知 Gate：{gate}（允许 0-5）")
    binding = _load_current_run_binding(run_dir)
    run_manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if gate == 3:
        _assert_resolved_domain_contract(run_manifest)
    artifacts: list[dict[str, Any]] = []
    if gate == 5 and _is_gate_5_v2_run(run_dir):
        if approved_review_id is None:
            raise ValueError("Gate 5 Review v2 清单必须显式指定 approved_review_id")
        review, relative, review_sha = _load_gate_5_v2_review(run_dir, approved_review_id)
        if review["decision"] != "approved":
            raise ValueError("Gate 5 Artifact Manifest 只能绑定 approved Review")
        artifacts.append(
            {
                "path": relative,
                "role": "gate_5_review",
                "schema": "schemas/gate_5_review_v2.schema.json",
                "schema_version": GATE_5_REVIEW_V2_CONTRACT_VERSION,
                "sha256": review_sha,
                "size_bytes": len((run_dir / relative).read_bytes()),
            }
        )
    else:
        for filename, role, schema_relative, schema_version in _gate_artifact_specs_for_run(run_dir, gate):
            raw = _validate_gate_business_artifact(
                run_dir,
                filename,
                role,
                schema_relative,
                schema_version,
                binding,
            )
            artifacts.append(
                {
                    "path": filename,
                    "role": role,
                    "schema": schema_relative,
                    "schema_version": schema_version,
                    "sha256": sha256_bytes(raw),
                    "size_bytes": len(raw),
                }
            )
    manifest: dict[str, Any] = {
        "manifest_version": "1.0.0",
        "gate": gate,
        "completed_at": completed_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        **binding,
        "artifacts": artifacts,
    }
    if gate == 4 and _paper_pipeline_is_required(run_manifest):
        verify_candidate_manifest(run_dir, binding)
    formal_policy = _formal_result_policy(run_manifest)
    if formal_policy in {FORMAL_RESULT_POLICY_REQUIRED, FORMAL_RESULT_POLICY_REHEARSAL}:
        manifest.update(_formal_identity_defaults(formal_policy))
    if formal_policy == FORMAL_RESULT_POLICY_REQUIRED:
        if gate == 3:
            summary = _verify_required_formal_result(run_dir)
            manifest["formal_result"] = {
                "formal_result_id": summary["formal_result_id"],
                "envelope_path": summary["envelope_path"],
                "envelope_file_sha256": summary["envelope_file_sha256"],
                "envelope_semantic_sha256": summary["envelope_semantic_sha256"],
                **formal_result_state_summary(summary),
            }
    if gate == 3 and run_manifest.get("reasonableness_contract_version") == REASONABLENESS_CONTRACT_VERSION:
        manifest["reasonableness_review"] = require_approved_reasonableness_review(run_dir)
    if gate == 3 and formal_policy != FORMAL_RESULT_POLICY_REQUIRED:
        # 历史与演练运行均显式保留非资格状态，不能被下游误认作正式结果。
        rehearsal = formal_policy == FORMAL_RESULT_POLICY_REHEARSAL
        manifest["formal_result"] = {
            "formal_result_id": (
                "rehearsal-unqualified" if rehearsal else "legacy-unavailable"
            ),
            "envelope_path": (
                "formal_results/rehearsal-unqualified/formal_result_envelope.json"
                if rehearsal
                else "formal_results/legacy/formal_result_envelope.json"
            ),
            "envelope_file_sha256": "0" * 64,
            "envelope_semantic_sha256": "0" * 64,
            "formal_result_activation_status": "code_complete_candidate",
            "sandboxie_environment_observed": False,
            "sandboxie_environment_verified": False,
            "formal_result_executed_in_verified_environment": False,
            "formal_result_eligible": False,
            "execution_trust_model": (
                "direct_local_unqualified" if rehearsal else "trusted_local"
            ),
        }
    return manifest


def write_gate_artifact_manifest(
    run_dir: Path,
    gate: int,
    *,
    completed_at: str | None = None,
    approved_review_id: str | None = None,
) -> Path:
    """校验业务内容后写入 gate_artifacts/gate_N.manifest.json。"""
    manifest = build_gate_artifact_manifest(
        run_dir,
        gate,
        completed_at=completed_at,
        approved_review_id=approved_review_id,
    )
    manifest_path = run_dir / "gate_artifacts" / f"gate_{gate}.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(manifest_path, manifest)
    return manifest_path


def verify_gate_artifacts(run_dir: Path, gate: int) -> dict[str, Any]:
    """验证 Gate 清单、精确文件集合、业务 Schema、运行身份及内容哈希。"""
    if gate not in GATE_ARTIFACT_SPECS:
        raise ValueError(f"未知 Gate：{gate}（允许 0-5）")
    manifest_path = run_dir / "gate_artifacts" / f"gate_{gate}.manifest.json"
    manifest = _load_json_object(manifest_path, f"gate_{gate}.manifest.json")
    _validate_json_schema(
        manifest,
        "schemas/gate_artifact_manifest.schema.json",
        f"gate_{gate}.manifest.json",
    )
    if manifest.get("gate") != gate:
        raise ValueError(f"gate_{gate}.manifest.json.gate 必须为 {gate}")

    binding = _load_current_run_binding(run_dir)
    for field, expected in binding.items():
        if manifest.get(field) != expected:
            raise ValueError(f"gate_{gate}.manifest.json.{field} 与当前运行现场不一致")
    run_manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    formal_policy = _formal_result_policy(run_manifest)
    if formal_policy in {FORMAL_RESULT_POLICY_REQUIRED, FORMAL_RESULT_POLICY_REHEARSAL}:
        for field, expected in _formal_identity_defaults(formal_policy).items():
            if manifest.get(field) != expected or run_manifest.get(field) != expected:
                raise ValueError(f"gate_{gate}.manifest.json.{field} 未绑定当前不可变身份")

    if gate == 5 and _is_gate_5_v2_run(run_dir):
        entries = manifest.get("artifacts", [])
        if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
            raise ValueError("Gate 5 Review v2 Manifest 必须且只能包含一个最终审核记录")
        entry = entries[0]
        path_text = entry.get("path")
        if not isinstance(path_text, str) or not path_text.startswith(f"{GATE_5_REVIEW_DIRECTORY}/"):
            raise ValueError("Gate 5 Review v2 Manifest 必须绑定 reviews/gate5 下的不可变记录")
        review_id = Path(path_text).stem
        review, relative, review_sha = _load_gate_5_v2_review(run_dir, review_id)
        if review["decision"] != "approved":
            raise ValueError("Gate 5 Review v2 Manifest 不得绑定非 approved 审核")
        expected_metadata = {
            "path": relative,
            "role": "gate_5_review",
            "schema": "schemas/gate_5_review_v2.schema.json",
            "schema_version": GATE_5_REVIEW_V2_CONTRACT_VERSION,
            "sha256": review_sha,
            "size_bytes": len((run_dir / relative).read_bytes()),
        }
        for field, expected in expected_metadata.items():
            if entry.get(field) != expected:
                raise ValueError(f"Gate 5 Review v2 Manifest 的 {field} 不匹配")
        history_entries, _history_head = verify_review_history(run_dir, GATE_5_REVIEW_HISTORY_FILENAME)
        if not any(item.get("review_id") == review_id and item.get("sha256") == review_sha for item in history_entries):
            raise ValueError("Gate 5 Review v2 Manifest 引用的审核未进入 history")
        return manifest

    expected_specs = _gate_artifact_specs_for_run(run_dir, gate)
    expected_paths = {spec[0] for spec in expected_specs}
    entries = manifest.get("artifacts", [])
    actual_paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    if len(actual_paths) != len(set(actual_paths)):
        raise ValueError(f"gate_{gate}.manifest.json.artifacts 存在重复路径")
    if set(actual_paths) != expected_paths:
        raise ValueError(
            f"gate_{gate}.manifest.json 产物集合错误："
            f"期望 {sorted(expected_paths)}，实际 {sorted(str(path) for path in actual_paths)}"
        )
    entries_by_path = {entry["path"]: entry for entry in entries}
    for filename, role, schema_relative, schema_version in expected_specs:
        entry = entries_by_path[filename]
        expected_metadata = {
            "role": role,
            "schema": schema_relative,
            "schema_version": schema_version,
        }
        for field, expected in expected_metadata.items():
            if entry.get(field) != expected:
                raise ValueError(f"gate_{gate}.manifest.json {filename}.{field} 不符合固定契约")
        raw = _validate_gate_business_artifact(
            run_dir,
            filename,
            role,
            schema_relative,
            schema_version,
            binding,
        )
        if entry.get("sha256") != sha256_bytes(raw):
            raise ValueError(f"Gate {gate} 产物 {filename} SHA-256 不匹配")
        if entry.get("size_bytes") != len(raw):
            raise ValueError(f"Gate {gate} 产物 {filename} size_bytes 不匹配")
    if gate == 4 and _paper_pipeline_is_required(run_manifest):
        verify_candidate_manifest(run_dir, binding)
    if gate == 1 and _is_v21_run(run_dir):
        contract = _load_json_object(run_dir / "model_validity_contract.json", "model_validity_contract.json")
        contract_errors = validate_model_validity_contract(contract)
        if contract_errors:
            raise ValueError("Gate 1 模型有效性合同失败：" + "；".join(contract_errors))
    if run_manifest.get("communication_contract_version") == COMMUNICATION_CONTRACT_VERSION and gate in {0, 1, 2}:
        communication_path = {
            0: "diagnosis.json",
            1: "model_route_v2_1.json" if _is_v21_run(run_dir) else "model_route.json",
            2: "code_plan.json",
        }[gate]
        communication_artifact = _load_json_object(run_dir / communication_path, communication_path)
        diagnosis_path = run_dir / "diagnosis.json"
        diagnosis = _load_json_object(diagnosis_path, "diagnosis.json")
        communication_errors = validate_gate_communication(
            gate,
            communication_artifact,
            diagnosis_sha256=sha256_bytes(diagnosis_path.read_bytes()),
            proposed_result_role=diagnosis.get("proposed_result_role"),
        )
        if communication_errors:
            raise ValueError("Gate 沟通合同失败：" + "；".join(communication_errors))
        if gate == 1 and communication_artifact["result_role_binding"]["confirmation"] == "revision_required":
            raise ValueError("Gate 1 要求修订结果角色；必须 fork-revision，不能以 approved 推进当前 Run")
    if gate == 3:
        if _formal_result_policy(run_manifest) == FORMAL_RESULT_POLICY_REQUIRED:
            summary = _verify_required_formal_result(run_dir)
            expected_formal = {
                "formal_result_id": summary["formal_result_id"],
                "envelope_path": summary["envelope_path"],
                "envelope_file_sha256": summary["envelope_file_sha256"],
                "envelope_semantic_sha256": summary["envelope_semantic_sha256"],
                **formal_result_state_summary(summary),
            }
            if manifest.get("formal_result") != expected_formal:
                raise ValueError("Gate 3 Manifest 未精确绑定当前 Formal Result Envelope")
        result_report = _load_json_object(run_dir / "result_report.json", "result_report.json")
        result_manifest = _load_json_object(
            run_dir / "result_manifest.json", "result_manifest.json"
        )
        model_errors = validate_model_and_execution(
            result_report, result_manifest, run_dir=run_dir
        )
        if model_errors:
            raise ValueError("Gate 3 数学或复现检查失败：" + "；".join(model_errors))
        executable_evidence = collect_gate_3_math_validation(
            run_dir, result_report, result_manifest
        )
        requires_executable_evidence = _profile_requires_executable_evidence(run_manifest)
        if (
            requires_executable_evidence
            and executable_evidence["mathematical_validation"] != "passed"
        ):
            evidence_errors = executable_evidence["errors"]
            assert isinstance(evidence_errors, list)
            raise ValueError(
                "Gate 3 可执行数学检查证据失败："
                + "；".join(str(item) for item in evidence_errors)
            )
        if _is_v21_run(run_dir):
            validity_contract = _load_json_object(run_dir / "model_validity_contract.json", "model_validity_contract.json")
            validity_report = _load_json_object(run_dir / "model_validity_report.json", "model_validity_report.json")
            validity_errors = validate_model_validity_contract(validity_contract)
            validity_errors.extend(
                validate_model_validity_report(
                    validity_report,
                    validity_contract,
                    contract_path=run_dir / "model_validity_contract.json",
                )
            )
            if validity_errors:
                raise ValueError("v2.1 模型有效性检查失败：" + "；".join(validity_errors))
            contract_refs = validity_contract.get("assertion_refs", [])
            runtime_manifest = _load_json_object(run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json")
            assertion_errors = validate_assertion_refs(
                contract_refs,
                runtime_pack_text=(run_dir / "runtime_pack.md").read_text(encoding="utf-8"),
                runtime_manifest=runtime_manifest,
            )
            if assertion_errors:
                raise ValueError("公开/封存断言隔离失败：" + "；".join(assertion_errors))
            for matlab_name in ("matlab_level_a_report.json", "matlab_level_b_report.json"):
                matlab_report = _load_json_object(run_dir / matlab_name, matlab_name)
                _validate_json_schema(matlab_report, "schemas/matlab_recomputation_report.schema.json", matlab_name)
                matlab_errors = validate_matlab_recomputation(matlab_report)
                if matlab_errors:
                    raise ValueError(f"{matlab_name} 复算合同失败：" + "；".join(matlab_errors))
            binding = _load_json_object(run_dir / "formal_result_run_binding.json", "formal_result_run_binding.json")
            if _formal_result_policy(run_manifest) == FORMAL_RESULT_POLICY_REQUIRED:
                formal_summary = _verify_required_formal_result(run_dir)
                binding_errors = validate_formal_result_run_binding(
                    binding,
                    run_dir=run_dir,
                    run_manifest=run_manifest,
                    formal_result_summary=formal_summary,
                )
                if binding_errors:
                    raise ValueError("Formal Result 当前运行绑定失败：" + "；".join(binding_errors))
            assessment = _load_json_object(run_dir / "competition_value_assessment.json", "competition_value_assessment.json")
            assessment_errors = validate_competition_value_assessment(assessment)
            if assessment_errors:
                raise ValueError("竞赛价值审查失败：" + "；".join(assessment_errors))
            admission = _load_json_object(run_dir / "paper_admission_report.json", "paper_admission_report.json")
            _validate_json_schema(admission, "schemas/paper_admission_report.schema.json", "paper_admission_report.json")
            findings = list(admission.get("blocking_findings", []))
            for code in validity_report.get("fatal_codes", []):
                if not any(item.get("code") == code for item in findings):
                    findings.append({"code": code, "severity": "fatal", "resolved": False, "note": "模型有效性报告中的致命代码"})
            independence = _load_json_object(run_dir / "validator_independence_manifest.json", "validator_independence_manifest.json")
            if independence.get("f5_status") == "fail" and not any(item.get("code") == "F5" for item in findings):
                findings.append({"code": "F5", "severity": "fatal", "resolved": False, "note": "Validator 非独立"})
            expected_admission = evaluate_paper_admission(
                implementation_status=derive_implementation_status(executable_evidence),
                model_validity_status="pass" if validity_report.get("execution_status") == "passed" and not validity_report.get("fatal_codes") else "fail",
                competition_score=float(assessment["score"]),
                competition_status=str(assessment["status"]),
                findings=findings,
                reviewer_ref={"path": "competition_value_assessment.json", "sha256": sha256_bytes((run_dir / "competition_value_assessment.json").read_bytes())},
                baseline_improvement_supported=bool(assessment["baseline_improvement_supported"]),
                operational_value_supported=bool(assessment["operational_value_supported"]),
            )
            for field in ("implementation_correctness", "model_validity", "competition_value", "blocking_findings", "admission_status", "technical_report_allowed", "submission_paper_allowed"):
                if admission.get(field) != expected_admission.get(field):
                    raise ValueError(f"paper_admission_report.{field} 不是由 Gate 3 工件重新计算的结果")
        if run_manifest.get("reasonableness_contract_version") == REASONABLENESS_CONTRACT_VERSION:
            expected_reasonableness = require_approved_reasonableness_review(run_dir)
            if manifest.get("reasonableness_review") != expected_reasonableness:
                raise ValueError("Gate 3 Manifest 未精确绑定当前 approved Reasonableness Review")
    if gate == 2 and _is_v21_run(run_dir):
        independence = _load_json_object(run_dir / "validator_independence_manifest.json", "validator_independence_manifest.json")
        independence_errors = validate_validator_independence(independence)
        if independence_errors:
            raise ValueError("Validator 独立性检查失败：" + "；".join(independence_errors))
        contract = _load_json_object(run_dir / "model_validity_contract.json", "model_validity_contract.json")
        runtime_manifest = _load_json_object(run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json")
        assertion_errors = validate_assertion_refs(
            contract.get("assertion_refs", []),
            runtime_pack_text=(run_dir / "runtime_pack.md").read_text(encoding="utf-8"),
            runtime_manifest=runtime_manifest,
        )
        if assertion_errors:
            raise ValueError("Executor 断言隔离失败：" + "；".join(assertion_errors))
    if gate == 4:
        result_report = _load_json_object(run_dir / "result_report.json", "result_report.json")
        result_manifest = _load_json_object(
            run_dir / "result_manifest.json", "result_manifest.json"
        )
        claim_map = _load_json_object(run_dir / "paper_claim_map.json", "paper_claim_map.json")
        claim_errors = validate_model_and_execution(
            result_report,
            result_manifest,
            run_dir=run_dir,
            claim_map=claim_map,
        )
        if claim_errors:
            raise ValueError("Gate 4 Claim-Result 检查失败：" + "；".join(claim_errors))
        if _is_v21_run(run_dir):
            production = _load_json_object(run_dir / "paper_production_manifest.json", "paper_production_manifest.json")
            _validate_json_schema(production, "schemas/paper_production_manifest.schema.json", "paper_production_manifest.json")
            admission = _load_json_object(run_dir / "paper_admission_report.json", "paper_admission_report.json")
            production_errors = validate_paper_production_manifest(production, run_dir=run_dir, admission=admission)
            if production_errors:
                raise ValueError("论文生产清单检查失败：" + "；".join(production_errors))
            # Gate 4 只要求当前 Candidate 已通过 AI Technical Review；最终决定由 Gate 5 人工完成。
            _current_approved_technical_review(run_dir, current_candidate(run_dir))
    if gate == 5 and _is_v21_run(run_dir):
        score = _load_json_object(run_dir / "score_v2.json", "score_v2.json")
        _validate_json_schema(score, "schemas/score_v2.schema.json", "score_v2.json")
        expected_score = compute_score_v2(
            float(score["diagnosis_structure_score"]),
            float(score["model_quality_score"]),
            float(score["result_quality_score"]),
            float(score["paper_presentation_score"]),
            fatal_codes=list(score.get("fatal_codes", [])),
            unresolved_major=bool(score.get("unresolved_major")),
        )
        if abs(float(score["technical_merit"]) - expected_score["technical_merit"]) > 1e-9:
            raise ValueError("score_v2.technical_merit 与公式不一致")
        if abs(float(score["competition_submission_score"]) - expected_score["competition_submission_score"]) > 1e-9:
            raise ValueError("score_v2.competition_submission_score 与公式不一致")
        if score["competition_submission_status"] != expected_score["competition_submission_status"]:
            raise ValueError("score_v2.competition_submission_status 与阻断规则不一致")
    return manifest


def _load_and_validate_gate_5_review(run_dir: Path, reviewer: str) -> tuple[dict[str, Any], str]:
    """读取并验证 Gate 5 人工审核记录，返回记录和 SHA-256。"""
    if not str(reviewer).strip():
        raise ValueError("reviewer 不能为空")
    review_path = run_dir / "gate_5_review.json"
    if not review_path.is_file():
        raise FileNotFoundError(f"缺少 Gate 5 人工审核记录：{review_path}")
    raw = review_path.read_bytes()
    try:
        review = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"gate_5_review.json 无法解析：{exc}") from exc
    if not isinstance(review, dict):
        raise ValueError("gate_5_review.json 必须是 JSON 对象")

    _validate_gate_5_review_schema(review)
    current_binding = _load_current_run_binding(run_dir)
    for field, expected in current_binding.items():
        if review.get(field) != expected:
            raise ValueError(
                f"gate_5_review.{field} 与当前运行现场不一致："
                f"审核记录为 {review.get(field)!r}，当前运行为 {expected!r}"
            )
    if review.get("target_gate") != 5:
        raise ValueError("gate_5_review.target_gate 必须为 5")
    if review.get("reviewer") != str(reviewer).strip():
        raise ValueError("gate_5_review.reviewer 必须与 mark_run_completed 参数一致")
    _parse_datetime(review.get("reviewed_at"), "reviewed_at")
    if review.get("decision") != "approved":
        raise ValueError("gate_5_review.decision 必须为 approved")
    if review.get("final_acceptance") is not True:
        raise ValueError("gate_5_review.final_acceptance 必须为 true")
    if not isinstance(review.get("reason"), str) or len(review.get("reason", "").strip()) < 10:
        raise ValueError("gate_5_review.reason 至少需要 10 个字符")
    checklist = review["checklist"]
    if set(checklist) != set(GATE_5_CHECKLIST_KEYS):
        raise ValueError("gate_5_review.checklist 必须且只能包含固定八项")
    failed = [key for key in GATE_5_CHECKLIST_KEYS if checklist.get(key) is not True]
    if failed:
        raise ValueError(f"gate_5_review.checklist 存在未通过项：{', '.join(failed)}")
    return review, sha256_bytes(raw)


def _mark_run_completed_v1(run_dir: Path, reviewer: str) -> None:
    """保留历史 Gate 5 v1 的完成逻辑，确保已封存 Run 可继续重放。"""
    _assert_formal_result_mutable(run_dir)
    state = replay_transition_log(run_dir)
    _assert_run_can_progress(run_dir, state)
    if state["completed"]:
        raise ValueError("运行已标记为 completed，不能重复标记。")
    if state["max_gate"] < 5:
        raise ValueError(f"最大 Gate 为 {state['max_gate']}，0-4 的运行不得被标记为 completed。")
    if state["current_gate"] != 5:
        raise ValueError(f"当前不在 Gate 5（当前 Gate：{state['current_gate']}），无法完成运行。")

    review, review_sha = _load_and_validate_gate_5_review(run_dir, reviewer)
    if state.get("transition_version") == TRANSITION_VERSION:
        # Gate 5 封存前重验全部 Gate，避免 Gate 4 论文/Reviewer 工件在推进后被篡改。
        for gate in range(6):
            verify_gate_artifacts(run_dir, gate)
        entry = {
            "transition_version": TRANSITION_VERSION,
            "completed_gate": 5,
            "next_gate": None,
            "state": "completed",
            "reviewer": str(reviewer).strip(),
            "decision": "approved",
            "review_record": "gate_5_review.json",
            "review_record_sha256": review_sha,
            "reviewed_at": review["reviewed_at"],
            "note": "Gate 5 业务产物与最终审核均通过，运行完成。",
        }
    else:
        entry = {
            "from": 5,
            "to": None,
            "state": "completed",
            "reviewer": str(reviewer).strip(),
            "decision": "approved",
            "review_record": "gate_5_review.json",
            "review_record_sha256": review_sha,
            "reviewed_at": review["reviewed_at"],
            "note": "Gate 5 通过，运行完成。",
        }
    if state.get("transition_version") == TRANSITION_VERSION:
        _append_transition_event(run_dir / "transitions.jsonl", entry)
    else:
        transitions_path = run_dir / "transitions.jsonl"
        atomic_write_text(
            transitions_path,
            transitions_path.read_text(encoding="utf-8")
            + json.dumps(entry, ensure_ascii=False)
            + "\n",
        )

    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.is_file():
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if run_manifest.get("manifest_version") != "2.0.0":
            run_manifest["run_status"] = "completed"
            run_manifest.setdefault("integrity_status", "unsealed")
            write_json(manifest_path, run_manifest)


def _write_gate_5_completion_journal(run_dir: Path, payload: Mapping[str, Any]) -> None:
    """持久化 v2 完成事务进度，使中断后的同一 review_id 可幂等恢复。"""
    journal = dict(payload)
    journal["journal_version"] = "1.0.0"
    journal["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json(run_dir / "gate_5_completion_journal.json", journal)


def _mark_run_completed_v2(
    run_dir: Path,
    *,
    approved_review_id: str,
    reviewer: str | None,
) -> None:
    """以不可变 approved Review 完成并封存 v2 Run，支持事务边界中断恢复。"""
    _assert_formal_result_mutable(run_dir)
    with acquire_run_write_lock(run_dir):
        state = replay_transition_log(run_dir)
        if state["completed"]:
            completed_entry = state.get("completed_entry") or {}
            if completed_entry.get("approved_review_id") != approved_review_id:
                raise ValueError("Run 已由不同的 approved_review_id 完成")
        else:
            _assert_run_can_progress(run_dir, state)
            if state["max_gate"] < 5 or state["current_gate"] != 5:
                raise ValueError("只有位于 Gate 5 的完整 Run 可以完成")
            self_review, review_path, review_sha = _load_gate_5_v2_review(run_dir, approved_review_id)
            if self_review["decision"] != "approved":
                raise ValueError("mark_run_completed 只接受 approved_review_id")
            reviewer_identity = str(self_review["reviewer"]["identity"])
            if reviewer is not None and str(reviewer).strip() != reviewer_identity:
                raise ValueError("传入 reviewer 必须与 approved Gate 5 Review 的 reviewer.identity 一致")
            _reconcile_gate_5_review_history(run_dir)
            history_entries, history_head = verify_review_history(run_dir, GATE_5_REVIEW_HISTORY_FILENAME)
            if not any(item.get("review_id") == approved_review_id and item.get("sha256") == review_sha for item in history_entries):
                raise ValueError("approved Gate 5 Review 未进入 history")
            journal_path = run_dir / "gate_5_completion_journal.json"
            if journal_path.is_file():
                journal = _load_json_object(journal_path, "gate_5_completion_journal.json")
                if journal.get("approved_review_id") != approved_review_id:
                    raise ValueError("已有 Gate 5 完成事务绑定了不同的 approved_review_id")
            else:
                journal = {"approved_review_id": approved_review_id, "status": "prepared"}
                _write_gate_5_completion_journal(run_dir, journal)

            # 先重验 Gate 0-4；Gate 5 清单在此处才绑定最终不可变审核。
            for gate in range(5):
                verify_gate_artifacts(run_dir, gate)
            write_gate_artifact_manifest(run_dir, 5, approved_review_id=approved_review_id)
            journal["status"] = "gate_5_manifest_written"
            _write_gate_5_completion_journal(run_dir, journal)

            evidence = _rebuild_v2_gate_5_evidence(run_dir)
            _validate_v2_gate_5_evidence(run_dir, evidence)
            evidence_sha = sha256_bytes((run_dir / "run_evidence_manifest.json").read_bytes())
            history_sha = sha256_bytes((run_dir / GATE_5_REVIEW_HISTORY_FILENAME).read_bytes())
            journal.update({"status": "evidence_written", "evidence_manifest_sha256": evidence_sha})
            _write_gate_5_completion_journal(run_dir, journal)

            entry = {
                "transition_version": TRANSITION_VERSION,
                "completed_gate": 5,
                "next_gate": None,
                "state": "completed",
                "reviewer": reviewer_identity,
                "decision": "approved",
                "approved_review_id": approved_review_id,
                "review_record": review_path,
                "review_record_sha256": review_sha,
                "review_history_sha256": history_sha,
                "review_history_head_sha256": history_head,
                "evidence_manifest_sha256": evidence_sha,
                "reviewed_at": self_review["reviewed_at"],
                "note": "Gate 5 v2 最终审核、Evidence 与不可变 history 均已通过。",
            }
            _append_transition_event(run_dir / "transitions.jsonl", entry)
            journal["status"] = "completed_transition_written"
            _write_gate_5_completion_journal(run_dir, journal)

    # Evidence 在 v2 中不再哈希 completed event，避免 Evidence SHA 与 event SHA 的循环依赖；
    # Seal 仍绑定最终 transitions 文件，从而封存完整状态机。
    seal_path = run_dir / "seal_record.json"
    if not seal_path.is_file():
        from finalize_run_evidence import finalize_run_evidence

        finalize_run_evidence(run_dir)
    with acquire_run_write_lock(run_dir):
        journal = _load_json_object(run_dir / "gate_5_completion_journal.json", "gate_5_completion_journal.json")
        journal["status"] = "sealed"
        _write_gate_5_completion_journal(run_dir, journal)


def mark_run_completed(
    run_dir: Path,
    reviewer: str | None = None,
    *,
    approved_review_id: str | None = None,
) -> None:
    """完成 Run；v2 必须显式指定 approved_review_id，v1 保持原调用兼容。"""
    if _is_gate_5_v2_run(run_dir):
        if approved_review_id is None:
            raise ValueError("Gate 5 Review v2 必须显式提供 approved_review_id")
        _mark_run_completed_v2(
            run_dir,
            approved_review_id=approved_review_id,
            reviewer=reviewer,
        )
        return
    if approved_review_id is not None:
        raise ValueError("历史 Gate 5 v1 不接受 approved_review_id")
    if reviewer is None:
        raise ValueError("历史 Gate 5 v1 必须提供 reviewer")
    _mark_run_completed_v1(run_dir, reviewer)


def create_prompt_regression_run(args: argparse.Namespace) -> Path:
    """创建轻量 Prompt 回归目录；该流程不进入 Gate，也不能生成晋级证据。"""
    profile_name = resolve_profile_for_workflow(args, "prompt_regression")
    run_id, run_dir = _resolve_run_directory(
        args,
        workflow="prompt_regression",
        profile=profile_name,
    )
    run_dir.mkdir(parents=True)

    profile = _load_profile_state(profile_name)
    pack = build_pack(
        profile_name, "prompt_regression", args.candidate_patch, args.exclude_patch
    )
    pack_manifest = build_manifest(
        profile_name,
        "prompt_regression",
        pack,
        args.candidate_patch,
        args.exclude_patch,
    )
    atomic_write_text(run_dir / "runtime_pack.md", pack)
    write_json(run_dir / "runtime_pack.manifest.json", pack_manifest)
    write_json(run_dir / "runtime_profile.snapshot.json", profile)
    write_json(
        run_dir / "run_manifest.json",
        {
            "manifest_version": "2.0.0",
            "run_id": run_id,
            "workflow": "prompt_regression",
            "problem_id": args.problem,
            "profile": profile_name,
            "runtime_version": profile["version"],
            "runtime_pack_sha256": pack_manifest["runtime_pack_sha256"],
            "initial_state": "initialized",
            "eligible_for_promotion": False,
            "evidence_validity": "prompt_behavior_only",
        },
    )
    write_json(
        run_dir / "request.json",
        {"prompt": "", "model": "", "source": "pending", "response_reference": None},
    )
    write_json(run_dir / "response.json", {"_note": "待执行轻量提示词行为测试"})
    return run_dir


FORK_TRANSACTION_VERSION = "1.0.0"
FORK_TRANSACTION_STATUSES = {
    "prepared",
    "child_published",
    "parent_linked",
    "committed",
    "aborted",
}


def _fork_transaction_directory(run_root: Path) -> Path:
    """返回统一的 Profile Fork 事务目录。"""
    return run_root / ".transactions" / "fork-profile"


def _fork_transaction_path(run_root: Path, transaction_id: str) -> Path:
    """由事务 ID 计算唯一事务记录路径。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", transaction_id):
        raise ValueError("fork transaction ID 必须为 8-80 位安全字符")
    return _fork_transaction_directory(run_root) / f"{transaction_id}.json"


def _read_fork_transaction(path: Path) -> dict[str, Any]:
    """读取并检查事务记录的基本身份字段。"""
    transaction = _load_json_object(path, "fork transaction")
    if transaction.get("transaction_version") != FORK_TRANSACTION_VERSION:
        raise ValueError("fork transaction_version 不支持")
    if transaction.get("status") not in FORK_TRANSACTION_STATUSES:
        raise ValueError("fork transaction.status 非法")
    for field in (
        "fork_transaction_id",
        "parent_run_id",
        "child_run_id",
        "parent_transition_head_sha256",
        "parent_material_digest",
        "selected_profile",
        "reviewer",
        "reason",
    ):
        value = transaction.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"fork transaction 缺少合法 {field}")
    return transaction


def _write_fork_transaction(path: Path, transaction: Mapping[str, Any]) -> None:
    """原子更新事务记录及更新时间，避免恢复时读取半写入内容。"""
    payload = dict(transaction)
    payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json(path, payload)


def _transaction_head_sha256(run_dir: Path) -> str:
    """取得父 Run 当前不可变转换链头。"""
    entries = _read_transition_entries(run_dir / "transitions.jsonl")
    if not entries:
        raise ValueError("父 Run transitions.jsonl 为空")
    _validate_transition_hash_chain(entries)
    head = entries[-1].get("event_sha256")
    if not isinstance(head, str) or not re.fullmatch(r"[a-f0-9]{64}", head):
        raise ValueError("父 Run transitions 末端缺少合法 event_sha256")
    return head


def _material_path_from_run_manifest(manifest: Mapping[str, Any]) -> Path:
    """从 Run Manifest 解析原始材料目录，并拒绝缺失记录。"""
    raw_materials = manifest.get("materials")
    if not isinstance(raw_materials, str) or not raw_materials.strip():
        raise ValueError("run_manifest 缺少 materials")
    material_path = Path(raw_materials)
    if not material_path.is_absolute():
        material_path = ROOT / material_path
    return material_path.resolve()


def _verified_material_digest(manifest: Mapping[str, Any]) -> str:
    """重新验证材料并从当前字节派生问题摘要。"""
    material_path = _material_path_from_run_manifest(manifest)
    problem_id = manifest.get("problem_id")
    if not isinstance(problem_id, str) or not problem_id:
        raise ValueError("run_manifest 缺少 problem_id")
    verification = verify_materials(material_path, expected_problem_id=problem_id)
    if not verification.ready:
        raise ValueError("fork-profile 前材料重新验证失败")
    digest = build_problem_manifest(problem_id, material_path, verification).get("content_digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("无法从当前材料派生合法 content_digest")
    return digest


def _fork_lock_path(run_root: Path, parent_run_id: str) -> Path:
    """为同一父 Run 生成稳定的跨进程排他锁路径。"""
    key = sha256_bytes(parent_run_id.encode("utf-8"))
    return _fork_transaction_directory(run_root) / ".locks" / f"{key}.lock"


def _acquire_fork_lock(run_root: Path, parent_run_id: str, transaction_id: str, *, resume: bool) -> Path:
    """以独占创建锁阻止同一父 Run 并发 Fork。"""
    lock_path = _fork_lock_path(run_root, parent_run_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock_path.open("x", encoding="utf-8") as handle:
            handle.write(transaction_id)
    except FileExistsError as exc:
        holder = lock_path.read_text(encoding="utf-8").strip() if lock_path.is_file() else ""
        if resume and holder == transaction_id:
            lock_path.unlink(missing_ok=True)
            return _acquire_fork_lock(run_root, parent_run_id, transaction_id, resume=False)
        raise ValueError("该父 Run 已有进行中的 fork-profile 事务") from exc
    return lock_path


def _release_fork_lock(lock_path: Path, transaction_id: str) -> None:
    """仅释放本次事务持有的锁，避免删除其他调用方的锁。"""
    if lock_path.is_file() and lock_path.read_text(encoding="utf-8").strip() == transaction_id:
        lock_path.unlink(missing_ok=True)


def _find_parent_transactions(run_root: Path, parent_run_id: str) -> list[dict[str, Any]]:
    """列出同一父 Run 的已记录事务，用于阻止重复或并发 Fork。"""
    directory = _fork_transaction_directory(run_root)
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        transaction = _read_fork_transaction(path)
        if transaction["parent_run_id"] == parent_run_id:
            records.append(transaction)
    return records


def _assert_parent_fork_eligible(parent_run: Path, selected_profile: str) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """执行 fork-profile 的完整预检，并返回父身份、状态、材料摘要和链头。"""
    _assert_formal_result_mutable(parent_run)
    parent_manifest = _load_json_object(parent_run / "run_manifest.json", "run_manifest.json")
    if parent_manifest.get("workflow") != "new_problem":
        raise ValueError("fork-profile 只允许从 new_problem 父 Run 发起")
    if parent_manifest.get("profile") != "general":
        raise ValueError("fork-profile 当前只允许 general 父 Profile")
    if parent_manifest.get("profile") == selected_profile:
        raise ValueError("fork-profile 的目标 Profile 必须不同于父 Profile")
    _load_profile_state(selected_profile)
    state = replay_transition_log(parent_run)
    if state.get("lifecycle_status") != "active":
        raise ValueError("父 Run 已 superseded，不能再次 fork-profile")
    if state.get("completed") or state.get("current_gate") != 0:
        raise ValueError("fork-profile 只能在 Gate 0 已形成产物且尚未推进时执行")
    verify_gate_artifacts(parent_run, 0)
    problem_manifest = _load_json_object(parent_run / "problem_manifest.json", "problem_manifest.json")
    parent_digest = problem_manifest.get("content_digest")
    if not isinstance(parent_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", parent_digest):
        raise ValueError("父 Run problem_manifest.content_digest 非法")
    current_digest = _verified_material_digest(parent_manifest)
    if current_digest != parent_digest:
        raise ValueError("当前材料摘要与父 Run 不一致，禁止 fork-profile")
    return parent_manifest, state, parent_digest, _transaction_head_sha256(parent_run)


def _next_child_run_id(run_root: Path, parent_manifest: Mapping[str, Any], profile: str) -> str:
    """预分配不会覆盖正式目录的子 Run ID。"""
    problem_id = str(parent_manifest["problem_id"])
    for _attempt in range(RUN_ID_MAX_ATTEMPTS):
        run_id = build_automatic_run_id(problem_id, "new_problem", profile)
        if not (run_root / run_id).exists():
            return run_id
    raise FileExistsError("无法为 fork-profile 分配不冲突的子 Run ID")


def _prepare_fork_child(
    parent_run: Path,
    parent_manifest: Mapping[str, Any],
    transaction: Mapping[str, Any],
    staging_root: Path,
) -> Path:
    """在临时目录初始化子 Run，并重新绑定可验证的 Gate 0 产物。"""
    child_id = str(transaction["child_run_id"])
    args = argparse.Namespace(
        run_id=child_id,
        output_root=str(staging_root),
        problem=parent_manifest["problem_id"],
        profile=transaction["selected_profile"],
        gates="0-5",
        materials=str(_material_path_from_run_manifest(parent_manifest)),
        candidate_patch=[],
        exclude_patch=[],
        material_file=[],
        promotion_evidence=False,
        experiment_group_id=None,
        experiment_role=None,
        target_patch=None,
        workflow="new_problem",
        mode=parent_manifest.get("mode", "standard"),
        # Fork 必须继承父 Run 的合同版本，避免 v2.1 父 Run 降级为历史合同。
        v21=(parent_manifest.get("runtime_manifest_version") == V21_RUNTIME_MANIFEST_VERSION),
        formal_result_policy=_formal_result_policy(parent_manifest),
    )
    child_run, ready = create_new_problem_run(args)
    if not ready:
        raise ValueError("fork-profile 临时子 Run 材料未就绪")

    parent_diagnosis_path = parent_run / "diagnosis.json"
    parent_diagnosis = _load_json_object(parent_diagnosis_path, "parent diagnosis.json")
    child_manifest = _load_json_object(child_run / "run_manifest.json", "child run_manifest.json")
    child_runtime = _load_json_object(
        child_run / "runtime_pack.manifest.json", "child runtime_pack.manifest.json"
    )
    for field, value in {
        "run_id": child_manifest["run_id"],
        "problem_id": child_manifest["problem_id"],
        "profile": child_manifest["profile"],
        "runtime_version": child_manifest["runtime_version"],
        "runtime_pack_sha256": child_runtime["runtime_pack_sha256"],
    }.items():
        parent_diagnosis[field] = value
    write_json(child_run / "diagnosis.json", parent_diagnosis)
    write_gate_artifact_manifest(child_run, 0)
    atomic_write_bytes(child_run / "parent_diagnosis.snapshot.json", parent_diagnosis_path.read_bytes())

    parent_gate_manifest = parent_run / "gate_artifacts" / "gate_0.manifest.json"
    fork_record = {
        "fork_transaction_id": transaction["fork_transaction_id"],
        "parent_run_id": transaction["parent_run_id"],
        "child_run_id": child_manifest["run_id"],
        "parent_gate_0_manifest": "gate_artifacts/gate_0.manifest.json",
        "parent_gate_0_manifest_sha256": sha256_bytes(parent_gate_manifest.read_bytes()),
        "parent_diagnosis_sha256": sha256_bytes(parent_diagnosis_path.read_bytes()),
        "parent_problem_material_digest": transaction["parent_material_digest"],
        "selected_profile": transaction["selected_profile"],
        "profile_selection_reason": transaction["reason"],
        "reviewer": transaction["reviewer"],
        "lineage_type": "profile_fork",
        "status": "prepared",
    }
    write_json(child_run / "fork_record.json", fork_record)
    write_json(
        child_run / "run_evidence_manifest.json",
        build_run_evidence_manifest(child_run, str(child_manifest["run_id"])),
    )
    verify_gate_artifacts(child_run, 0)
    verify_run(child_run)
    return child_run


def _append_profile_fork_event(parent_run: Path, transaction: Mapping[str, Any]) -> None:
    """在父 Run 链尾追加 superseded 生命周期事件。"""
    expected_parent_head = transaction["parent_transition_head_sha256"]
    if _transaction_head_sha256(parent_run) != expected_parent_head:
        entries = _read_transition_entries(parent_run / "transitions.jsonl")
        existing = entries[-1]
        expected_fields = {
            "previous_event_sha256": expected_parent_head,
            "event_type": "profile_forked",
            "state": "profile_forked",
            "fork_transaction_id": transaction["fork_transaction_id"],
            "child_run_id": transaction["child_run_id"],
            "selected_profile": transaction["selected_profile"],
            "reviewer": transaction["reviewer"],
            "reason": transaction["reason"],
            "lifecycle_status": "superseded",
        }
        if all(existing.get(field) == value for field, value in expected_fields.items()):
            return
        raise ValueError("父 Run transition head 已变化，禁止覆盖新状态")
    state = replay_transition_log(parent_run)
    if state.get("current_gate") != 0 or state.get("lifecycle_status") != "active":
        raise ValueError("父 Run 已不满足 profile_forked 前提")
    _append_transition_event(
        parent_run / "transitions.jsonl",
        {
            "transition_version": TRANSITION_VERSION,
            "event_type": "profile_forked",
            "state": "profile_forked",
            "fork_transaction_id": transaction["fork_transaction_id"],
            "child_run_id": transaction["child_run_id"],
            "selected_profile": transaction["selected_profile"],
            "reviewer": transaction["reviewer"],
            "reason": transaction["reason"],
            "lifecycle_status": "superseded",
        },
    )


def _append_profile_fork_rollback_event(
    parent_run: Path,
    transaction: Mapping[str, Any],
    failure: Exception,
) -> None:
    """幂等追加 Fork 补偿事件，使尚未提交事务的父 Run 恢复 Gate 0 active。"""
    entries = _read_transition_entries(parent_run / "transitions.jsonl")
    if entries:
        existing = entries[-1]
        if (
            existing.get("state") == "profile_fork_rolled_back"
            and existing.get("fork_transaction_id") == transaction["fork_transaction_id"]
            and existing.get("child_run_id") == transaction["child_run_id"]
        ):
            return
    state = replay_transition_log(parent_run)
    if (
        state.get("lifecycle_status") != "superseded"
        or state.get("fork_transaction_id") != transaction["fork_transaction_id"]
        or state.get("superseded_by_run_id") != transaction["child_run_id"]
    ):
        raise ValueError("父 Run 不存在可补偿的 profile_forked 事件")
    _append_transition_event(
        parent_run / "transitions.jsonl",
        {
            "transition_version": TRANSITION_VERSION,
            "event_type": "profile_fork_rolled_back",
            "state": "profile_fork_rolled_back",
            "completed_gate": None,
            "next_gate": 0,
            "fork_transaction_id": transaction["fork_transaction_id"],
            "child_run_id": transaction["child_run_id"],
            "reviewer": transaction["reviewer"],
            "reason": f"子 Run 提交前完整性复核失败：{failure}",
            "lifecycle_status": "active",
        },
    )


def _fork_record_path(run_dir: Path) -> Path:
    """集中定义子 Run 的 Fork 记录位置。"""
    return run_dir / "fork_record.json"


def _fork_lineage_errors(run_dir: Path, state: Mapping[str, Any]) -> list[str]:
    """交叉验证父事件、子记录和事务，任何不一致均返回阻断错误。"""
    errors: list[str] = []
    run_root = run_dir.parent
    if state.get("lifecycle_status") == "superseded":
        entries = _read_transition_entries(run_dir / "transitions.jsonl")
        latest = entries[-1] if entries else {}
        if latest.get("event_type") == "revision_forked":
            child_id = latest.get("child_run_id")
            transaction_id = latest.get("revision_transaction_id")
            if not isinstance(child_id, str) or not isinstance(transaction_id, str):
                return ["修订 fork 事件缺少子 Run 或事务身份"]
            try:
                transaction = _read_revision_transaction(_revision_transaction_path(run_root, transaction_id))
            except (OSError, ValueError) as exc:
                return [f"修订 fork transaction 无法验证：{exc}"]
            if transaction.get("status") != "committed":
                return ["修订 fork transaction 尚未 committed"]
            if transaction.get("parent_run_id") != run_dir.name or transaction.get("child_run_id") != child_id:
                return ["修订 fork transaction 父子身份不一致"]
            child_path = run_dir.parent / str(child_id)
            if not child_path.is_dir():
                return ["修订子 Run 不存在"]
            try:
                child_manifest = _load_json_object(child_path / "run_manifest.json", "revision child run_manifest.json")
                child_record = _load_json_object(_revision_record_path(child_path), "revision_fork_record.json")
            except (OSError, ValueError):
                return ["修订子 Run manifest 无法验证"]
            if child_manifest.get("revision_parent_run_id") != run_dir.name or child_record.get("status") != "committed":
                return ["修订子 Run 未绑定父 Run"]
            for field in (
                "revision_transaction_id",
                "revision_scope",
                "parent_material_digest",
                "parent_gate_artifact_refs",
                "parent_integrity_failure",
            ):
                if child_record.get(field) != transaction.get(field):
                    return [f"修订子 Run {field} 与事务不一致"]
            return errors
        transaction_id = state.get("fork_transaction_id")
        child_id = state.get("superseded_by_run_id")
        if not isinstance(transaction_id, str) or not isinstance(child_id, str):
            return ["父 Run profile_forked 生命周期字段缺失"]
        try:
            transaction = _read_fork_transaction(_fork_transaction_path(run_root, transaction_id))
        except (OSError, ValueError) as exc:
            return [f"父 Run fork transaction 无效：{exc}"]
        if transaction.get("status") != "committed":
            errors.append("父 Run 引用的 fork transaction 尚未 committed")
        if transaction.get("parent_run_id") != run_dir.name or transaction.get("child_run_id") != child_id:
            errors.append("父 Run 与 fork transaction 身份不一致")
        child_run = run_root / child_id
        try:
            record = _load_json_object(_fork_record_path(child_run), "child fork_record.json")
        except (OSError, ValueError) as exc:
            errors.append(f"父 Run 引用的子 Run 缺少 fork_record：{exc}")
            return errors
        for field, expected in {
            "fork_transaction_id": transaction_id,
            "parent_run_id": run_dir.name,
            "child_run_id": child_id,
            "selected_profile": transaction.get("selected_profile"),
            "parent_problem_material_digest": transaction.get("parent_material_digest"),
        }.items():
            if record.get(field) != expected:
                errors.append(f"父子 fork 记录 {field} 不一致")
        if record.get("status") != "committed":
            errors.append("子 Run fork_record 尚未 committed")
    elif _revision_record_path(run_dir).is_file():
        try:
            record = _load_json_object(_revision_record_path(run_dir), "revision_fork_record.json")
            transaction_id = record.get("revision_transaction_id")
            parent_id = record.get("parent_run_id")
            if not isinstance(transaction_id, str) or not isinstance(parent_id, str):
                return ["修订子 Run 缺少父子事务身份"]
            transaction = _read_revision_transaction(_revision_transaction_path(run_root, transaction_id))
            parent_state = replay_transition_log(
                run_root / parent_id,
                verify_artifacts=transaction.get("parent_integrity_failure") is None,
            )
            if transaction.get("status") != "committed" or record.get("status") != "committed":
                errors.append("修订子 Run 事务尚未 committed")
            if parent_state.get("superseded_by_run_id") != run_dir.name:
                errors.append("修订子 Run 未被父 Run 的 revision_forked 事件引用")
            if parent_state.get("revision_transaction_id") != transaction_id:
                errors.append("修订子 Run 与父 Run revision_transaction_id 不一致")
        except (OSError, ValueError) as exc:
            errors.append(f"修订 Run 谱系无效：{exc}")
    elif _fork_record_path(run_dir).is_file():
        try:
            record = _load_json_object(_fork_record_path(run_dir), "fork_record.json")
            transaction_id = record.get("fork_transaction_id")
            parent_id = record.get("parent_run_id")
            if not isinstance(transaction_id, str) or not isinstance(parent_id, str):
                return ["子 Run fork_record 缺少父子事务身份"]
            transaction = _read_fork_transaction(_fork_transaction_path(run_root, transaction_id))
            parent_state = replay_transition_log(run_root / parent_id)
            if transaction.get("status") != "committed" or record.get("status") != "committed":
                errors.append("子 Run 的 fork transaction 尚未 committed")
            if parent_state.get("superseded_by_run_id") != run_dir.name:
                errors.append("子 Run 未被父 Run 的 profile_forked 事件引用")
            if parent_state.get("fork_transaction_id") != transaction_id:
                errors.append("子 Run 与父 Run fork_transaction_id 不一致")
        except (OSError, ValueError) as exc:
            errors.append(f"子 Run fork lineage 无效：{exc}")
    return errors


def _assert_run_can_progress(run_dir: Path, state: Mapping[str, Any]) -> None:
    """统一阻止 superseded 父 Run、半事务子 Run 和损坏谱系继续推进。"""
    if state.get("lifecycle_status") != "active":
        raise ValueError("Run 已 superseded，禁止 advance 或 complete")
    errors = _fork_lineage_errors(run_dir, state)
    if errors:
        raise ValueError("fork-profile 谱系未提交或不一致：" + "；".join(errors))
    if not _fork_record_path(run_dir).is_file() and not _revision_record_path(run_dir).is_file():
        pending = [
            item
            for item in _find_parent_transactions(run_dir.parent, run_dir.name)
            if item.get("status") not in {"committed", "aborted"}
        ]
        if pending:
            raise ValueError("父 Run 存在进行中的 fork-profile 事务，禁止推进")
        pending_revisions = [
            item
            for item in _find_revision_transactions(run_dir.parent, run_dir.name)
            if item.get("status") not in {"committed", "aborted"}
        ]
        if pending_revisions:
            raise ValueError("父 Run 存在进行中的 revision fork 事务，禁止推进")


def _staged_child_path(run_root: Path, transaction: Mapping[str, Any]) -> Path:
    """由事务字段确定唯一临时子 Run 路径，供恢复流程复用。"""
    staging_root = run_root / ".tmp" / (
        f"fork-{transaction['fork_transaction_id']}-{transaction['child_run_id']}"
    )
    return staging_root / str(transaction["child_run_id"])


def _verify_fork_child_for_resume(
    child_run: Path,
    transaction: Mapping[str, Any],
    *,
    label: str,
    parent_run: Path,
) -> None:
    """恢复发布步骤前重验子 Run、父级绑定和 Gate 0 核心证据。"""
    if child_run.is_symlink() or not child_run.is_dir():
        raise ValueError(f"{label}必须是非符号链接目录")
    record = _load_json_object(_fork_record_path(child_run), f"{label} fork_record.json")
    for field, expected in {
        "fork_transaction_id": transaction["fork_transaction_id"],
        "parent_run_id": transaction["parent_run_id"],
        "child_run_id": transaction["child_run_id"],
        "selected_profile": transaction["selected_profile"],
        "parent_problem_material_digest": transaction["parent_material_digest"],
        "profile_selection_reason": transaction["reason"],
        "reviewer": transaction["reviewer"],
        "lineage_type": "profile_fork",
        "parent_gate_0_manifest": "gate_artifacts/gate_0.manifest.json",
    }.items():
        if record.get(field) != expected:
            raise ValueError(f"{label}的 fork_record.{field} 与事务不一致")
    if record.get("status") not in {"prepared", "committed"}:
        raise ValueError(f"{label}的 fork_record.status 非法")
    for field, path in {
        "parent_gate_0_manifest_sha256": parent_run / "gate_artifacts" / "gate_0.manifest.json",
        "parent_diagnosis_sha256": parent_run / "diagnosis.json",
    }.items():
        if not path.is_file() or record.get(field) != sha256_bytes(path.read_bytes()):
            raise ValueError(f"{label}的 fork_record.{field} 与当前父 Run 不一致")

    run_manifest = _load_json_object(child_run / "run_manifest.json", "run_manifest.json")
    for field, expected in {
        "run_id": transaction["child_run_id"],
        "profile": transaction["selected_profile"],
        "workflow": "new_problem",
        "formal_result_policy": _formal_result_policy(
            _load_json_object(parent_run / "run_manifest.json", "parent run_manifest.json")
        ),
    }.items():
        if run_manifest.get(field) != expected:
            raise ValueError(f"{label}的 run_manifest.json.{field} 与事务不一致")
    problem_manifest = _load_json_object(
        child_run / "problem_manifest.json", "problem_manifest.json"
    )
    if problem_manifest.get("content_digest") != transaction["parent_material_digest"]:
        raise ValueError(f"{label}的 problem_manifest.content_digest 与父材料摘要不一致")

    verify_gate_artifacts(child_run, 0)
    evidence = _load_json_object(
        child_run / "run_evidence_manifest.json", "run_evidence_manifest.json"
    )
    if evidence.get("evidence_manifest_version") != "2.0.0":
        raise ValueError(f"{label}的 run_evidence_manifest 版本不支持")
    if evidence.get("run_id") != transaction["child_run_id"]:
        raise ValueError(f"{label}的 run_evidence_manifest.run_id 与事务不一致")
    from finalize_run_evidence import validate_evidence_manifest

    required = evidence_required_artifacts_for_workflow(
        "new_problem",
        completed=False,
        gate_5_review_contract_version=run_manifest.get("gate_5_review_contract_version"),
    )
    evidence_errors = validate_evidence_manifest(child_run, evidence, required)
    if evidence_errors:
        raise ValueError(f"{label}证据清单无效：" + "；".join(evidence_errors))


def _publish_staged_child(run_root: Path, transaction: Mapping[str, Any]) -> Path:
    """原子发布已完整验证的临时子 Run。"""
    staged_child = _staged_child_path(run_root, transaction)
    final_child = run_root / str(transaction["child_run_id"])
    parent_run = run_root / str(transaction["parent_run_id"])
    if final_child.exists():
        if staged_child.exists():
            raise FileExistsError("临时子 Run 与正式子 Run 同时存在，拒绝推断事务状态")
        _verify_fork_child_for_resume(
            final_child,
            transaction,
            label="已发布子 Run",
            parent_run=parent_run,
        )
        return final_child
    _verify_fork_child_for_resume(
        staged_child,
        transaction,
        label="临时子 Run",
        parent_run=parent_run,
    )
    staged_child.replace(final_child)
    _verify_fork_child_for_resume(
        final_child,
        transaction,
        label="已发布子 Run",
        parent_run=parent_run,
    )
    try:
        staged_child.parent.rmdir()
        staged_child.parent.parent.rmdir()
    except OSError:
        pass
    return final_child


def _commit_child_fork_record(child_run: Path, transaction: Mapping[str, Any]) -> None:
    """将子 Run 从不可推进的 prepared 状态原子切换为 committed。"""
    record_path = _fork_record_path(child_run)
    record = _load_json_object(record_path, "fork_record.json")
    if record.get("fork_transaction_id") != transaction["fork_transaction_id"]:
        raise ValueError("child fork_record 的 transaction ID 不一致")
    if record.get("status") not in {"prepared", "committed"}:
        raise ValueError("child fork_record.status 非法")
    record["status"] = "committed"
    write_json(record_path, record)


def _abort_child_fork_record(child_run: Path, transaction: Mapping[str, Any]) -> None:
    """将补偿事务的子记录标为 aborted，确保该目录永久不可推进。"""
    if child_run.is_symlink() or not child_run.is_dir():
        return
    record_path = _fork_record_path(child_run)
    try:
        record = _load_json_object(record_path, "fork_record.json")
    except (OSError, ValueError):
        return
    if record.get("fork_transaction_id") != transaction["fork_transaction_id"]:
        return
    record["status"] = "aborted"
    write_json(record_path, record)


def _abort_linked_fork_transaction(
    parent_run: Path,
    transaction_path: Path,
    transaction: dict[str, Any],
    failure: Exception,
) -> None:
    """补偿已写父事件但尚未提交子 Run 的事务，恢复父 Run 并封闭子 Run。"""
    _append_profile_fork_rollback_event(parent_run, transaction, failure)
    parent_manifest = _load_json_object(parent_run / "run_manifest.json", "run_manifest.json")
    write_json(
        parent_run / "run_evidence_manifest.json",
        build_run_evidence_manifest(parent_run, str(parent_manifest["run_id"])),
    )
    child_run = parent_run.parent / str(transaction["child_run_id"])
    _abort_child_fork_record(child_run, transaction)
    transaction["status"] = "aborted"
    transaction["abort_reason"] = str(failure)
    _write_fork_transaction(transaction_path, transaction)


def _verify_published_child_or_compensate(
    parent_run: Path,
    transaction_path: Path,
    transaction: dict[str, Any],
) -> None:
    """重验正式子 Run；父事件已写时以补偿事务恢复父状态。"""
    child_run = parent_run.parent / str(transaction["child_run_id"])
    try:
        _verify_fork_child_for_resume(
            child_run,
            transaction,
            label="已发布子 Run",
            parent_run=parent_run,
        )
    except Exception as exc:
        state = replay_transition_log(parent_run)
        parent_is_linked = (
            state.get("lifecycle_status") == "superseded"
            and state.get("fork_transaction_id") == transaction["fork_transaction_id"]
            and state.get("superseded_by_run_id") == transaction["child_run_id"]
        )
        entries = _read_transition_entries(parent_run / "transitions.jsonl")
        rollback_is_recorded = bool(entries) and all(
            entries[-1].get(field) == expected
            for field, expected in {
                "state": "profile_fork_rolled_back",
                "fork_transaction_id": transaction["fork_transaction_id"],
                "child_run_id": transaction["child_run_id"],
            }.items()
        )
        if parent_is_linked or rollback_is_recorded:
            _abort_linked_fork_transaction(parent_run, transaction_path, transaction, exc)
        raise


def _resume_fork_transaction(parent_run: Path, transaction_path: Path) -> dict[str, Any]:
    """从已落盘状态继续事务，重复调用不创建第二个子 Run。"""
    run_root = parent_run.parent
    transaction = _read_fork_transaction(transaction_path)
    if transaction["parent_run_id"] != parent_run.name:
        raise ValueError("--from-run 与 transaction.parent_run_id 不一致")
    status = transaction["status"]
    if status == "aborted":
        raise ValueError("aborted 事务不得自动复用，请创建新事务或人工清理")
    if status == "committed":
        errors = _fork_lineage_errors(parent_run, replay_transition_log(parent_run))
        if errors:
            raise ValueError("已提交事务谱系不一致：" + "；".join(errors))
        return {"child_run": str(run_root / transaction["child_run_id"]), "transaction_id": transaction["fork_transaction_id"], "status": status}
    if status == "prepared":
        _publish_staged_child(run_root, transaction)
        transaction["status"] = "child_published"
        _write_fork_transaction(transaction_path, transaction)
        status = "child_published"
    if status == "child_published":
        _verify_published_child_or_compensate(parent_run, transaction_path, transaction)
        try:
            _append_profile_fork_event(parent_run, transaction)
        except ValueError as exc:
            if "transition head" in str(exc):
                transaction["status"] = "aborted"
                _write_fork_transaction(transaction_path, transaction)
            raise
        transaction["status"] = "parent_linked"
        _write_fork_transaction(transaction_path, transaction)
        status = "parent_linked"
    if status == "parent_linked":
        _verify_published_child_or_compensate(parent_run, transaction_path, transaction)
        _commit_child_fork_record(run_root / str(transaction["child_run_id"]), transaction)
        transaction["status"] = "committed"
        _write_fork_transaction(transaction_path, transaction)
    errors = _fork_lineage_errors(parent_run, replay_transition_log(parent_run))
    if errors:
        raise ValueError("fork-profile 提交后的交叉验证失败：" + "；".join(errors))
    return {
        "child_run": str(run_root / transaction["child_run_id"]),
        "transaction_id": transaction["fork_transaction_id"],
        "status": "committed",
    }


REVISION_FORK_TRANSACTION_VERSION = "1.0.0"
REVISION_FORK_STATUSES = {"prepared", "child_published", "parent_linked", "committed", "aborted"}
REVISION_SCOPE_START_GATE = {"diagnosis": 0, "model_route": 1, "formal_result": 2}


def _revision_gate_manifest_ref(parent_run: Path, gate: int) -> dict[str, Any]:
    """绑定父 Run 已验证 Gate Manifest，避免修订谱系只记录题号而丢失证据来源。"""
    relative = f"gate_artifacts/gate_{gate}.manifest.json"
    path = parent_run / relative
    if not path.is_file():
        raise FileNotFoundError(f"缺少父 Run Gate {gate} Manifest：{path}")
    return {"gate": gate, "path": relative, "sha256": sha256_bytes(path.read_bytes())}


def _revision_parent_state(
    parent_run: Path,
    revision_scope: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """严格验证父 Run；仅为 revision 识别可验证前缀和首个封存漂移。"""
    scope_gate = REVISION_SCOPE_START_GATE[revision_scope]
    try:
        state = replay_transition_log(parent_run)
    except (FileNotFoundError, ValueError) as strict_error:
        state = replay_transition_log(parent_run, verify_artifacts=False)
        valid_refs: list[dict[str, Any]] = []
        failed_gate: int | None = None
        failure_message = ""
        for gate in state.get("completed_gates", []):
            try:
                verify_gate_artifacts(parent_run, int(gate))
            except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
                failed_gate = int(gate)
                failure_message = str(exc)
                break
            valid_refs.append(_revision_gate_manifest_ref(parent_run, int(gate)))
        if failed_gate is None:
            raise strict_error
        if failed_gate < scope_gate:
            required_scope = next(
                name for name, gate in REVISION_SCOPE_START_GATE.items() if gate == failed_gate
            )
            raise ValueError(
                f"父 Run 最早在 Gate {failed_gate} 失效，revision scope 必须改为 {required_scope}"
            ) from strict_error
        integrity_failure = {
            "status": "blocked_integrity_mismatch",
            "failed_gate": failed_gate,
            "error": failure_message,
        }
        return state, valid_refs, integrity_failure

    inherited_refs = []
    for gate in state.get("completed_gates", []):
        if int(gate) >= scope_gate:
            break
        inherited_refs.append(_revision_gate_manifest_ref(parent_run, int(gate)))
    return state, inherited_refs, None


def _revision_transaction_directory(run_root: Path) -> Path:
    """返回受控修订 Run 的独立事务目录。"""
    return run_root / ".transactions" / "fork-revision"


def _revision_transaction_path(run_root: Path, transaction_id: str) -> Path:
    """按安全 ID 定位修订事务，禁止路径穿越。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", transaction_id):
        raise ValueError("revision transaction ID 必须为 8-80 位安全字符")
    return _revision_transaction_directory(run_root) / f"{transaction_id}.json"


def _revision_record_path(run_dir: Path) -> Path:
    """集中定义修订子 Run 的谱系记录位置。"""
    return run_dir / "revision_fork_record.json"


def _read_revision_transaction(path: Path) -> dict[str, Any]:
    """读取并校验修订事务的不可变身份字段。"""
    transaction = _load_json_object(path, "revision fork transaction")
    if transaction.get("transaction_version") != REVISION_FORK_TRANSACTION_VERSION:
        raise ValueError("revision fork transaction_version 不支持")
    if transaction.get("status") not in REVISION_FORK_STATUSES:
        raise ValueError("revision fork transaction.status 非法")
    for field in (
        "revision_transaction_id", "parent_run_id", "child_run_id", "parent_transition_head_sha256",
        "parent_material_digest", "revision_scope", "reviewer", "reason",
    ):
        if not isinstance(transaction.get(field), str) or not str(transaction[field]).strip():
            raise ValueError(f"revision fork transaction 缺少 {field}")
    if transaction["revision_scope"] not in {"diagnosis", "model_route", "formal_result"}:
        raise ValueError("revision fork transaction.revision_scope 非法")
    refs = transaction.get("parent_gate_artifact_refs")
    if not isinstance(refs, list):
        raise ValueError("revision fork transaction 缺少 parent_gate_artifact_refs")
    seen_gates: set[int] = set()
    for ref in refs:
        if not isinstance(ref, Mapping):
            raise ValueError("revision fork parent_gate_artifact_refs 必须为对象列表")
        gate = ref.get("gate")
        if not isinstance(gate, int) or gate < 0 or gate > 5 or gate in seen_gates:
            raise ValueError("revision fork parent Gate 引用编号非法或重复")
        if ref.get("path") != f"gate_artifacts/gate_{gate}.manifest.json":
            raise ValueError("revision fork parent Gate 引用路径非法")
        if not isinstance(ref.get("sha256"), str) or not re.fullmatch(
            r"[a-f0-9]{64}", str(ref["sha256"])
        ):
            raise ValueError("revision fork parent Gate 引用缺少合法 SHA-256")
        seen_gates.add(gate)
    integrity_failure = transaction.get("parent_integrity_failure")
    if integrity_failure is not None:
        if not isinstance(integrity_failure, Mapping):
            raise ValueError("revision fork parent_integrity_failure 必须为对象或 null")
        if integrity_failure.get("status") != "blocked_integrity_mismatch":
            raise ValueError("revision fork parent_integrity_failure.status 非法")
        if not isinstance(integrity_failure.get("failed_gate"), int):
            raise ValueError("revision fork parent_integrity_failure 缺少 failed_gate")
        if not isinstance(integrity_failure.get("error"), str) or not str(
            integrity_failure["error"]
        ).strip():
            raise ValueError("revision fork parent_integrity_failure 缺少 error")
    return transaction


def _write_revision_transaction(path: Path, transaction: Mapping[str, Any]) -> None:
    """原子写入修订事务进度，使中断后可精确恢复。"""
    payload = dict(transaction)
    payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json(path, payload)


def _find_revision_transactions(run_root: Path, parent_run_id: str) -> list[dict[str, Any]]:
    """列出同一父 Run 的修订事务，阻止活动 Run 与半提交事务并行推进。"""
    directory = _revision_transaction_directory(run_root)
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        transaction = _read_revision_transaction(path)
        if transaction["parent_run_id"] == parent_run_id:
            records.append(transaction)
    return records


def _revision_staged_child_path(run_root: Path, transaction: Mapping[str, Any]) -> Path:
    """为修订子 Run 分配不可与正式 Run 混淆的临时路径。"""
    return run_root / ".tmp" / f"revision-{transaction['revision_transaction_id']}-{transaction['child_run_id']}" / str(transaction["child_run_id"])


def _prepare_revision_child(parent_run: Path, transaction: Mapping[str, Any]) -> Path:
    """在临时目录创建全新 Run，绝不回写父 Run 的结果或 Gate 产物。"""
    parent = _load_json_object(parent_run / "run_manifest.json", "parent run_manifest.json")
    staged_child = _revision_staged_child_path(parent_run.parent, transaction)
    if staged_child.exists():
        return staged_child
    args = argparse.Namespace(
        workflow=parent["workflow"],
        problem=parent["problem_id"],
        profile=parent["profile"],
        mode=parent.get("mode", "standard"),
        materials=parent["materials"],
        output_root=str(staged_child.parent),
        run_id=transaction["child_run_id"],
        candidate_patch=list(parent.get("candidate_patches", [])),
        exclude_patch=list(parent.get("excluded_patches", [])),
        promotion_evidence=False,
        experiment_group_id=None,
        experiment_role=None,
        target_patch=None,
        material_file=[],
        gates=parent.get("gates", "0-5"),
        v21=parent.get("runtime_manifest_version") == V21_RUNTIME_MANIFEST_VERSION,
        formal_result_policy=_formal_result_policy(parent),
    )
    if parent["workflow"] == "full_replay":
        child_run, ready = create_full_replay_run(args)
    elif parent["workflow"] == "new_problem":
        child_run, ready = create_new_problem_run(args)
    else:
        raise ValueError("仅 Gate workflow 支持修订 Run")
    if not ready:
        raise ValueError("修订子 Run 材料未就绪")
    manifest = _load_json_object(child_run / "run_manifest.json", "revision child run_manifest.json")
    manifest.update(
        {
            "revision_parent_run_id": transaction["parent_run_id"],
            "revision_scope": transaction["revision_scope"],
            "revision_reason": transaction["reason"],
            "revision_reviewer": transaction["reviewer"],
            "supersedes_reason": transaction["reason"],
            "inherited_material_sha256": transaction["parent_material_digest"],
            "revision_parent_gate_artifact_refs": transaction["parent_gate_artifact_refs"],
            "revision_parent_integrity_failure": transaction["parent_integrity_failure"],
        }
    )
    write_json(child_run / "run_manifest.json", manifest)
    write_json(
        _revision_record_path(child_run),
        {
            "transaction_version": REVISION_FORK_TRANSACTION_VERSION,
            "revision_transaction_id": transaction["revision_transaction_id"],
            "parent_run_id": transaction["parent_run_id"],
            "child_run_id": transaction["child_run_id"],
            "parent_transition_head_sha256": transaction["parent_transition_head_sha256"],
            "parent_material_digest": transaction["parent_material_digest"],
            "parent_gate_artifact_refs": transaction["parent_gate_artifact_refs"],
            "parent_integrity_failure": transaction["parent_integrity_failure"],
            "revision_scope": transaction["revision_scope"],
            "reviewer": transaction["reviewer"],
            "reason": transaction["reason"],
            "status": "prepared",
        },
    )
    write_json(child_run / "run_evidence_manifest.json", build_run_evidence_manifest(child_run, str(manifest["run_id"])))
    return child_run


def _verify_revision_child(parent_run: Path, child_run: Path, transaction: Mapping[str, Any]) -> None:
    """发布与恢复前校验子 Run 的身份、材料和预提交状态。"""
    if child_run.is_symlink() or not child_run.is_dir():
        raise ValueError("修订子 Run 必须为非符号链接目录")
    manifest = _load_json_object(child_run / "run_manifest.json", "revision child run_manifest.json")
    expected_manifest = {
        "run_id": transaction["child_run_id"],
        "revision_parent_run_id": transaction["parent_run_id"],
        "revision_scope": transaction["revision_scope"],
        "inherited_material_sha256": transaction["parent_material_digest"],
        "revision_parent_gate_artifact_refs": transaction["parent_gate_artifact_refs"],
        "revision_parent_integrity_failure": transaction["parent_integrity_failure"],
    }
    for field, expected in expected_manifest.items():
        if manifest.get(field) != expected:
            raise ValueError(f"修订子 Run {field} 与事务不一致")
    record = _load_json_object(_revision_record_path(child_run), "revision_fork_record.json")
    for field, expected in {
        "revision_transaction_id": transaction["revision_transaction_id"],
        "parent_run_id": transaction["parent_run_id"],
        "child_run_id": transaction["child_run_id"],
        "parent_transition_head_sha256": transaction["parent_transition_head_sha256"],
        "parent_material_digest": transaction["parent_material_digest"],
        "parent_gate_artifact_refs": transaction["parent_gate_artifact_refs"],
        "parent_integrity_failure": transaction["parent_integrity_failure"],
        "revision_scope": transaction["revision_scope"],
    }.items():
        if record.get(field) != expected:
            raise ValueError(f"revision_fork_record.{field} 与事务不一致")
    if record.get("status") not in {"prepared", "committed"}:
        raise ValueError("revision_fork_record.status 非法")
    for ref in transaction["parent_gate_artifact_refs"]:
        parent_path = (parent_run / str(ref["path"])).resolve()
        if not parent_path.is_relative_to(parent_run.resolve()) or not parent_path.is_file():
            raise ValueError("修订绑定的父 Gate Manifest 不存在或越界")
        if sha256_bytes(parent_path.read_bytes()) != ref["sha256"]:
            raise ValueError(f"修订绑定的父 Gate {ref['gate']} Manifest 已漂移")
    current_parent = _load_json_object(parent_run / "run_manifest.json", "parent run_manifest.json")
    if _verified_material_digest(current_parent) != transaction["parent_material_digest"]:
        raise ValueError("当前材料摘要已变化，禁止发布修订子 Run")


def _append_revision_fork_event(parent_run: Path, transaction: Mapping[str, Any]) -> None:
    """将父 Run 置为 superseded；重复恢复只接受同一事务的既有事件。"""
    expected_head = transaction["parent_transition_head_sha256"]
    if _transaction_head_sha256(parent_run) != expected_head:
        entries = _read_transition_entries(parent_run / "transitions.jsonl")
        latest = entries[-1] if entries else {}
        expected = {
            "previous_event_sha256": expected_head,
            "event_type": "revision_forked",
            "state": "revision_forked",
            "revision_transaction_id": transaction["revision_transaction_id"],
            "child_run_id": transaction["child_run_id"],
            "revision_scope": transaction["revision_scope"],
            "reviewer": transaction["reviewer"],
            "reason": transaction["reason"],
            "lifecycle_status": "superseded",
        }
        if all(latest.get(field) == value for field, value in expected.items()):
            return
        raise ValueError("父 Run transition head 已变化，禁止覆盖新状态")
    state = replay_transition_log(
        parent_run,
        verify_artifacts=transaction.get("parent_integrity_failure") is None,
    )
    if state.get("completed") or state.get("lifecycle_status") != "active":
        raise ValueError("父 Run 已不满足 revision fork 前提")
    _append_transition_event(
        parent_run / "transitions.jsonl",
        {
            "transition_version": TRANSITION_VERSION,
            "event_type": "revision_forked",
            "state": "revision_forked",
            "revision_transaction_id": transaction["revision_transaction_id"],
            "revision_scope": transaction["revision_scope"],
            "child_run_id": transaction["child_run_id"],
            "reviewer": transaction["reviewer"],
            "reason": transaction["reason"],
            "lifecycle_status": "superseded",
        },
    )


def _commit_revision_child(child_run: Path, transaction: Mapping[str, Any]) -> None:
    """父链已绑定后才允许子 Run 进入可推进状态。"""
    record = _load_json_object(_revision_record_path(child_run), "revision_fork_record.json")
    if record.get("revision_transaction_id") != transaction["revision_transaction_id"]:
        raise ValueError("revision_fork_record 事务身份不一致")
    if record.get("status") not in {"prepared", "committed"}:
        raise ValueError("revision_fork_record.status 非法")
    record["status"] = "committed"
    write_json(_revision_record_path(child_run), record)


def _resume_revision_fork(parent_run: Path, transaction_path: Path) -> dict[str, Any]:
    """按事务进度恢复发布、父链绑定和子 Run 提交。"""
    transaction = _read_revision_transaction(transaction_path)
    if transaction["status"] == "aborted":
        raise ValueError("已中止的 revision fork 不可恢复")
    run_root = parent_run.parent
    final = run_root / transaction["child_run_id"]
    if transaction["status"] == "prepared":
        if final.exists():
            _verify_revision_child(parent_run, final, transaction)
        else:
            child = _prepare_revision_child(parent_run, transaction)
            _verify_revision_child(parent_run, child, transaction)
            child.replace(final)
        transaction["status"] = "child_published"
        _write_revision_transaction(transaction_path, transaction)
    if transaction["status"] == "child_published":
        _verify_revision_child(parent_run, final, transaction)
        _append_revision_fork_event(parent_run, transaction)
        transaction["status"] = "parent_linked"
        _write_revision_transaction(transaction_path, transaction)
    if transaction["status"] == "parent_linked":
        _verify_revision_child(parent_run, final, transaction)
        _commit_revision_child(final, transaction)
        transaction["status"] = "committed"
        _write_revision_transaction(transaction_path, transaction)
    if transaction["status"] != "committed":
        raise ValueError("revision fork 未进入 committed 状态")
    return {"child_run": str(final), "revision_scope": transaction["revision_scope"], "transaction_id": transaction["revision_transaction_id"], "status": "committed"}


def fork_revision_run(
    parent_run: Path,
    *,
    revision_scope: str,
    reviewer: str,
    reason: str,
    transaction_id: str | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """可恢复地 Fork 修订 Run，并在子 Run 可验证发布后 supersede 父 Run。"""
    if revision_scope not in {"diagnosis", "model_route", "formal_result"}:
        raise ValueError("revision_scope 必须为 diagnosis、model_route 或 formal_result")
    parent_run = parent_run.resolve()
    if not parent_run.is_dir():
        raise ValueError("--from-run 不是有效 Run 目录")
    parent = _load_json_object(parent_run / "run_manifest.json", "run_manifest.json")
    state, parent_gate_refs, parent_integrity_failure = _revision_parent_state(
        parent_run,
        revision_scope,
    )
    if state.get("completed") or state.get("lifecycle_status") != "active":
        raise ValueError("仅未完成且 active 的父 Run 可以创建修订 Run")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("reviewer 与 reason 不能为空")
    run_root = parent_run.parent
    transaction_id = transaction_id or (
        datetime.now().strftime("%Y%m%d%H%M%S") + "_" + secrets.token_hex(6)
    )
    transaction_path = _revision_transaction_path(run_root, transaction_id)
    lock_path = _acquire_fork_lock(run_root, parent_run.name, transaction_id, resume=resume)
    try:
        if transaction_path.is_file():
            if not resume:
                raise ValueError("修订事务已存在；请使用 --resume 继续")
            return _resume_revision_fork(parent_run, transaction_path)
        if resume:
            raise ValueError("--resume 指定的修订事务不存在")
        material_digest = _verified_material_digest(parent)
        child_id = f"{parent_run.name}__rev_{revision_scope}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}"
        if (run_root / child_id).exists():
            raise FileExistsError("修订子 Run ID 已存在")
        transaction: dict[str, Any] = {
            "transaction_version": REVISION_FORK_TRANSACTION_VERSION,
            "revision_transaction_id": transaction_id,
            "parent_run_id": parent_run.name,
            "child_run_id": child_id,
            "parent_transition_head_sha256": _transaction_head_sha256(parent_run),
            "parent_material_digest": material_digest,
            "parent_gate_artifact_refs": parent_gate_refs,
            "parent_integrity_failure": parent_integrity_failure,
            "revision_scope": revision_scope,
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "status": "prepared",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        _revision_transaction_directory(run_root).mkdir(parents=True, exist_ok=True)
        _write_revision_transaction(transaction_path, transaction)
        return _resume_revision_fork(parent_run, transaction_path)
    finally:
        _release_fork_lock(lock_path, transaction_id)


def fork_profile(
    parent_run: Path,
    *,
    profile: str,
    reviewer: str,
    reason: str,
    transaction_id: str | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """将 general Gate 0 Run 可恢复地 Fork 为目标 Profile 子 Run。"""
    parent_run = parent_run.resolve()
    if not parent_run.is_dir():
        raise ValueError("--from-run 不是有效 Run 目录")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("fork-profile 的 reviewer 和 reason 均不能为空")
    run_root = parent_run.parent
    transaction_id = transaction_id or (
        datetime.now().strftime("%Y%m%d%H%M%S") + "_" + secrets.token_hex(6)
    )
    transaction_path = _fork_transaction_path(run_root, transaction_id)
    parent_manifest = _load_json_object(parent_run / "run_manifest.json", "run_manifest.json")
    lock_path = _acquire_fork_lock(
        run_root, str(parent_manifest.get("run_id", parent_run.name)), transaction_id, resume=resume
    )
    try:
        if transaction_path.is_file():
            if not resume:
                raise ValueError("事务已存在；请使用 --resume 继续")
            return _resume_fork_transaction(parent_run, transaction_path)
        if resume:
            raise ValueError("--resume 指定的事务不存在")
        parent_manifest, _state, material_digest, transition_head = _assert_parent_fork_eligible(
            parent_run, profile
        )
        existing = _find_parent_transactions(run_root, parent_run.name)
        if existing:
            raise ValueError("父 Run 已存在 fork-profile 事务，禁止创建第二个子 Run")
        child_id = _next_child_run_id(run_root, parent_manifest, profile)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        transaction: dict[str, Any] = {
            "transaction_version": FORK_TRANSACTION_VERSION,
            "fork_transaction_id": transaction_id,
            "parent_run_id": parent_run.name,
            "child_run_id": child_id,
            "parent_transition_head_sha256": transition_head,
            "parent_material_digest": material_digest,
            "selected_profile": profile,
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "status": "prepared",
            "created_at": now,
            "updated_at": now,
        }
        staged_child = _staged_child_path(run_root, transaction)
        try:
            _prepare_fork_child(parent_run, parent_manifest, transaction, staged_child.parent)
            _write_fork_transaction(transaction_path, transaction)
        except Exception:
            shutil.rmtree(staged_child.parent, ignore_errors=True)
            raise
        return _resume_fork_transaction(parent_run, transaction_path)
    finally:
        _release_fork_lock(lock_path, transaction_id)


def advance_run(run_dir: Path, reviewer: str, decision: str = "approved") -> dict[str, Any]:
    """推进一次 Gate；离开当前 Gate 时复用业务产物机器校验。"""
    _assert_formal_result_mutable(run_dir)
    state = replay_transition_log(run_dir)
    current = state["current_gate"]
    if current is None:
        record_transition(run_dir, None, 0, reviewer, decision)
    elif current == 5:
        raise ValueError("当前已在 Gate 5；请使用 complete 完成最终验收")
    else:
        record_transition(run_dir, current, current + 1, reviewer, decision)
    return replay_transition_log(run_dir)


def verify_run(run_dir: Path) -> dict[str, Any]:
    """复核运行现场；部分 Gate 运行可返回状态，但不会被标记为晋级证据。"""
    manifest = _load_json_object(run_dir / "run_manifest.json", "run_manifest.json")
    if manifest.get("workflow") == "prompt_regression":
        runtime_manifest = _load_json_object(
            run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json"
        )
        _validate_runtime_context_binding(manifest, runtime_manifest)
        return {
            "run_id": manifest.get("run_id"),
            "workflow": "prompt_regression",
            "eligible_for_promotion": False,
            "verified_gates": [],
            "completed": False,
            "sealed": False,
            "formal_result_activation_status": None,
            "sandboxie_environment_observed": False,
            "sandboxie_environment_verified": False,
            "formal_result_executed_in_verified_environment": False,
            "formal_result_eligible": False,
            "formal_result_eligibility_scope": None,
            "execution_trust_model": None,
            "git_head": None,
            "git_state_clean": False,
            "targeted_host_read_controls_passed": False,
            "default_deny_host_reads_verified": False,
            "privacy_mode_available": None,
        }
    state = replay_transition_log(run_dir)
    evidence_errors: list[str] = []
    lineage_errors = _fork_lineage_errors(run_dir, state)
    evidence_errors.extend(lineage_errors)
    try:
        runtime_manifest = _load_json_object(
            run_dir / "runtime_pack.manifest.json", "runtime_pack.manifest.json"
        )
        _validate_runtime_context_binding(manifest, runtime_manifest)
        purpose_error = validate_workflow_evidence_purpose(manifest, runtime_manifest)
        if purpose_error:
            evidence_errors.append(purpose_error)
        else:
            from finalize_run_evidence import validate_evidence_manifest

            workflow = manifest.get("workflow")
            assert isinstance(workflow, str)
            evidence = _load_json_object(
                run_dir / "run_evidence_manifest.json", "run_evidence_manifest.json"
            )
            required_artifacts = evidence_required_artifacts_for_workflow(
                workflow,
                completed=bool(state.get("completed")),
                runtime_manifest_version=str(runtime_manifest.get("manifest_version")),
                gate_5_review_contract_version=manifest.get("gate_5_review_contract_version"),
            )
            extend_review_pipeline_evidence_requirements(run_dir, required_artifacts)
            if state.get("completed"):
                extend_formal_result_evidence_requirements(run_dir, required_artifacts)
            evidence_errors.extend(validate_evidence_manifest(run_dir, evidence, required_artifacts))
            if evidence.get("run_id") != manifest.get("run_id"):
                evidence_errors.append("run_evidence_manifest.run_id 与 run_manifest 不一致")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        evidence_errors.append(str(exc))
    verified_gates: list[int] = []
    for gate in state.get("completed_gates", []):
        verify_gate_artifacts(run_dir, gate)
        verified_gates.append(gate)
    gate_3_validation: dict[str, object] = {
        "structural_validation": "not_run",
        "mathematical_validation": "not_run",
        "formal_result_eligible": False,
        "errors": [],
    }
    if 3 in verified_gates:
        result_report = _load_json_object(run_dir / "result_report.json", "result_report.json")
        result_manifest = _load_json_object(
            run_dir / "result_manifest.json", "result_manifest.json"
        )
        gate_3_validation = collect_gate_3_math_validation(
            run_dir, result_report, result_manifest
        )
    seal_errors: list[str] = []
    try:
        verify_run_seal(run_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        seal_errors.append(str(exc))

    promotion_errors = list(seal_errors) + evidence_errors
    if manifest.get("workflow") == "new_problem":
        promotion_errors.append("new_problem 的 competition_execution 运行不具备 Patch 晋级资格")
    if manifest.get("promotion_evidence") is not True:
        promotion_errors.append("运行初始化时未声明为晋级证据")
    if state.get("transition_version") != TRANSITION_VERSION:
        promotion_errors.append("晋级证据必须使用 Gate 语义完成契约 v2")
    if not state["completed"] or state["max_gate"] != 5:
        promotion_errors.append("Gate 0-5 尚未完整完成")
    requires_executable_evidence = _profile_requires_executable_evidence(manifest)
    if (
        requires_executable_evidence
        and gate_3_validation["mathematical_validation"] != "passed"
    ):
        promotion_errors.append(
            "Gate 3 数学检查未获机器证据确认："
            + str(gate_3_validation["mathematical_validation"])
        )

    if not promotion_errors:
        try:
            metadata = _load_json_object(run_dir / "ai_run_metadata.json", "ai_run_metadata.json")
            _validate_json_schema(
                metadata, "schemas/ai_run_metadata.schema.json", "ai_run_metadata.json"
            )
            if metadata.get("status") != "completed":
                promotion_errors.append("ai_run_metadata.status 不是 completed")
            request = _load_json_object(run_dir / "request.json", "request.json")
            if request.get("source") != "real_ai_run":
                promotion_errors.append("request.source 不是 real_ai_run")
            automatic = _load_json_object(
                run_dir / "automatic_evaluation.json", "automatic_evaluation.json"
            )
            if automatic.get("result") != "pass" or automatic.get("errors"):
                promotion_errors.append("automatic_evaluation 未通过")

            from finalize_run_evidence import validate_evidence_manifest

            workflow = manifest.get("workflow")
            assert isinstance(workflow, str)
            required = evidence_required_artifacts_for_workflow(
                workflow,
                completed=True,
                runtime_manifest_version=str(runtime_manifest.get("manifest_version")),
                gate_5_review_contract_version=manifest.get("gate_5_review_contract_version"),
            )
            extend_formal_result_evidence_requirements(run_dir, required)
            evidence = _load_json_object(
                run_dir / "run_evidence_manifest.json", "run_evidence_manifest.json"
            )
            promotion_errors.extend(validate_evidence_manifest(run_dir, evidence, required))
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            promotion_errors.append(str(exc))

    advance_allowed = (
        state.get("lifecycle_status") == "active"
        and not state["completed"]
        and not evidence_errors
        and not _fork_lineage_errors(run_dir, state)
    )
    if advance_allowed and not _fork_record_path(run_dir).is_file():
        advance_allowed = not any(
            item.get("status") not in {"committed", "aborted"}
            for item in _find_parent_transactions(run_dir.parent, run_dir.name)
        )
    formal_result_activation_status: str | None = None
    sandboxie_environment_observed = False
    sandboxie_environment_verified = False
    formal_result_executed_in_verified_environment = False
    formal_result_eligible = False
    formal_scope: dict[str, Any] = {
        "formal_result_eligibility_scope": None,
        "execution_trust_model": None,
        "git_head": None,
        "git_state_clean": False,
        "targeted_host_read_controls_passed": False,
        "default_deny_host_reads_verified": False,
        "privacy_mode_available": None,
    }
    if _formal_result_policy(manifest) in {
        FORMAL_RESULT_POLICY_LEGACY,
        FORMAL_RESULT_POLICY_REHEARSAL,
    }:
        formal_result_activation_status = "code_complete_candidate"
        formal_scope["execution_trust_model"] = (
            "direct_local_unqualified"
            if _formal_result_policy(manifest) == FORMAL_RESULT_POLICY_REHEARSAL
            else "trusted_local"
        )
    if _formal_result_policy(manifest) == FORMAL_RESULT_POLICY_REQUIRED:
        try:
            formal_summary = _verify_required_formal_result(run_dir)
            formal_result_activation_status = formal_summary[
                "formal_result_activation_status"
            ]
            sandboxie_environment_verified = bool(
                formal_summary["sandboxie_environment_verified"]
            )
            sandboxie_environment_observed = bool(
                formal_summary["sandboxie_environment_observed"]
            )
            formal_result_executed_in_verified_environment = bool(
                formal_summary["formal_result_executed_in_verified_environment"]
            )
            formal_result_eligible = bool(formal_summary["formal_result_eligible"])
            formal_scope.update(trusted_local_eligibility_scope(formal_summary))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    if (
        requires_executable_evidence
        and gate_3_validation["mathematical_validation"] != "passed"
    ):
        formal_result_eligible = False
    return {
        "run_id": manifest.get("run_id"),
        "workflow": manifest.get("workflow"),
        "mode": manifest.get("mode"),
        "eligible_for_promotion": not promotion_errors,
        "verified_gates": verified_gates,
        "current_gate": state["current_gate"],
        "completed": state["completed"],
        "sealed": not seal_errors and not evidence_errors,
        "lifecycle_status": state.get("lifecycle_status", "active"),
        "superseded_by_run_id": state.get("superseded_by_run_id"),
        "fork_transaction_id": state.get("fork_transaction_id"),
        "advance_allowed": advance_allowed,
        "complete_allowed": advance_allowed and state.get("current_gate") == 5,
        "formal_result_activation_status": formal_result_activation_status,
        "sandboxie_environment_observed": sandboxie_environment_observed,
        "sandboxie_environment_verified": sandboxie_environment_verified,
        "formal_result_executed_in_verified_environment": formal_result_executed_in_verified_environment,
        "formal_result_eligible": formal_result_eligible,
        "structural_validation": gate_3_validation["structural_validation"],
        "mathematical_validation": gate_3_validation["mathematical_validation"],
        **formal_scope,
        "promotion_readiness_errors": promotion_errors,
    }


def complete_and_seal_run(
    run_dir: Path,
    reviewer: str | None = None,
    *,
    approved_review_id: str | None = None,
) -> dict[str, Any]:
    """完成 Gate 5 并封存；中断后重复调用可从已完成转换处恢复。"""
    state = replay_transition_log(run_dir)
    if not state["completed"]:
        mark_run_completed(run_dir, reviewer, approved_review_id=approved_review_id)

    seal_path = run_dir / "seal_record.json"
    if seal_path.is_file():
        verify_run_seal(run_dir)
    else:
        from finalize_run_evidence import finalize_run_evidence

        finalize_run_evidence(run_dir)
    return verify_run(run_dir)


def _add_init_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workflow", required=True, choices=["prompt_regression", "full_replay", "new_problem"]
    )
    parser.add_argument("--problem", required=True, help="题号，例如 2024-C。")
    parser.add_argument("--profile", help="Runtime Profile；new_problem 未提供时使用 general。")
    parser.add_argument("--mode", default="standard", choices=["strict", "standard", "emergency"])
    parser.add_argument(
        "--formal-result-policy",
        default=FORMAL_RESULT_POLICY_REQUIRED,
        choices=[FORMAL_RESULT_POLICY_REQUIRED, FORMAL_RESULT_POLICY_REHEARSAL],
        help="正式资格运行或本机非资格演练策略。",
    )
    parser.add_argument("--materials", help="材料根目录；new_problem 必须显式提供。")
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--candidate-patch", action="append", default=[], dest="candidate_patch")
    parser.add_argument("--exclude-patch", action="append", default=[])
    parser.add_argument("--promotion-evidence", action="store_true")
    parser.add_argument("--experiment-group-id")
    parser.add_argument("--experiment-role", choices=["baseline", "patch_only"])
    parser.add_argument("--target-patch")
    parser.set_defaults(material_file=[])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="可追溯数学建模工作流 CLI。")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_init_arguments(commands.add_parser("init", help="冻结材料、Profile、Patch 和运行包"))
    advance = commands.add_parser("advance", help="验证并推进一个 Gate")
    advance.add_argument("--run-dir", required=True)
    advance.add_argument("--reviewer", required=True)
    advance.add_argument("--decision", default="approved", choices=["approved", "rejected"])
    complete = commands.add_parser("complete", help="验证 Gate 5 并完成运行")
    complete.add_argument("--run-dir", required=True)
    complete.add_argument("--reviewer")
    complete.add_argument("--approved-review-id")
    record_review = commands.add_parser("record-gate5-review", help="保存不可变 Gate 5 v2 最终审核记录")
    record_review.add_argument("--run-dir", required=True)
    record_review.add_argument("--review-file", required=True)
    handoff = commands.add_parser(
        "prepare-human-final-review-handoff",
        help="为当前 Candidate 生成只读人工 Gate 5 终审交接包",
    )
    handoff.add_argument("--run-dir", required=True)
    candidate = commands.add_parser("register-paper-candidate", help="注册不可变论文候选稿")
    candidate.add_argument("--run-dir", required=True)
    candidate.add_argument("--source", action="append", required=True)
    candidate.add_argument("--reason", required=True)
    candidate.add_argument("--parent-candidate-id")
    candidate.add_argument("--trigger-review-id")
    paper_revision = commands.add_parser("submit-paper-revision", help="根据 Gate 5 needs_revision 注册新的不可变论文候选稿")
    paper_revision.add_argument("--run-dir", required=True)
    paper_revision.add_argument("--source", action="append", required=True)
    paper_revision.add_argument("--reason", required=True)
    paper_revision.add_argument("--parent-candidate-id", required=True)
    paper_revision.add_argument("--trigger-review-id", required=True)
    technical = commands.add_parser("record-technical-review", help="保存不可变 Technical Review")
    technical.add_argument("--run-dir", required=True)
    technical.add_argument("--review-file", required=True)
    reasonable = commands.add_parser("record-reasonableness-review", help="保存独立合理性审核")
    reasonable.add_argument("--run-dir", required=True)
    reasonable.add_argument("--review-file", required=True)
    reader = commands.add_parser("record-paper-reader-review", help="保存隔离 Paper Reader 审核")
    reader.add_argument("--run-dir", required=True)
    reader.add_argument("--review-file", required=True)
    reader_workspace = commands.add_parser("create-paper-reader-workspace", help="创建仅含题面和论文的 Reader 输入包")
    reader_workspace.add_argument("--workspace", required=True)
    reader_workspace.add_argument("--problem-pdf", required=True)
    reader_workspace.add_argument("--submission-pdf", required=True)
    reader_workspace.add_argument("--review-contract", required=True)
    reader_workspace.add_argument("--prompt-file", required=True)
    revision = commands.add_parser("fork-revision", help="按 diagnosis/model_route/formal_result 创建修订 Run")
    revision.add_argument("--from-run", required=True)
    revision.add_argument("--scope", required=True, choices=["diagnosis", "model_route", "formal_result"])
    revision.add_argument("--reviewer", required=True)
    revision.add_argument("--reason", required=True)
    revision.add_argument("--transaction-id")
    revision.add_argument("--resume", action="store_true")
    verify = commands.add_parser("verify", help="复核当前运行状态与已完成 Gate")
    verify.add_argument("--run-dir", required=True)
    fork = commands.add_parser("fork-profile", help="从 general Gate 0 创建可恢复的专项 Profile 子 Run")
    fork.add_argument("--from-run", required=True)
    fork.add_argument("--profile", required=True)
    fork.add_argument("--reviewer", required=True)
    fork.add_argument("--reason", required=True)
    fork.add_argument("--transaction-id")
    fork.add_argument("--resume", action="store_true")
    matlab = commands.add_parser("matlab-recompute", help="执行 MATLAB Level A/B 独立复算")
    matlab.add_argument("--run-dir", required=True)
    matlab.add_argument("--level", required=True, choices=["A", "B"])
    matlab.add_argument("--input", required=True)
    matlab.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "init":
            if args.workflow == "prompt_regression":
                run_dir = create_prompt_regression_run(args)
                print(f"[READY] 已创建轻量 Prompt 回归：{run_dir}")
                return
            if args.workflow == "new_problem" and not args.materials:
                raise ValueError("new_problem 必须显式提供 --materials")
            args.gates = "0-5"
            # CLI 新建运行固定采用 v2.1；直接调用 create_* API 仍保留历史兼容语义。
            args.v21 = True
            if args.workflow == "new_problem":
                run_dir, material_ready = create_new_problem_run(args)
            else:
                run_dir, material_ready = create_full_replay_run(args)
            print(f"已创建运行目录：{run_dir}")
            if not material_ready:
                raise ValueError("题面、附件、模板或 SHA-256 校验未通过")
            print("[READY] 材料与冻结快照已就绪；请从 Gate 0 开始。")
        elif args.command == "advance":
            state = advance_run(Path(args.run_dir), args.reviewer, args.decision)
            print(json.dumps(state, ensure_ascii=False, indent=2))
        elif args.command == "complete":
            report = complete_and_seal_run(
                Path(args.run_dir),
                args.reviewer,
                approved_review_id=args.approved_review_id,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print("[SEALED] Gate 0-5 已完成并封存。")
        elif args.command == "record-gate5-review":
            review_file = Path(args.review_file)
            review = _load_json_object(review_file, str(review_file))
            result = record_gate_5_review(Path(args.run_dir), review)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "prepare-human-final-review-handoff":
            result = prepare_human_final_review_handoff(Path(args.run_dir))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command in {"register-paper-candidate", "submit-paper-revision"}:
            result = register_paper_candidate(
                Path(args.run_dir),
                args.source,
                reason=args.reason,
                parent_candidate_id=args.parent_candidate_id,
                trigger_review_id=args.trigger_review_id,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "record-technical-review":
            result = record_technical_review(Path(args.run_dir), _load_json_object(Path(args.review_file), args.review_file))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "record-reasonableness-review":
            result = record_reasonableness_review(Path(args.run_dir), _load_json_object(Path(args.review_file), args.review_file))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "record-paper-reader-review":
            result = record_paper_reader_review(Path(args.run_dir), _load_json_object(Path(args.review_file), args.review_file))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "create-paper-reader-workspace":
            contract = _load_json_object(Path(args.review_contract), args.review_contract)
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
            result = create_paper_reader_workspace(
                Path(args.workspace), problem_pdf=Path(args.problem_pdf), submission_pdf=Path(args.submission_pdf), review_contract=contract, prompt=prompt
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "fork-revision":
            result = fork_revision_run(
                Path(args.from_run),
                revision_scope=args.scope,
                reviewer=args.reviewer,
                reason=args.reason,
                transaction_id=args.transaction_id,
                resume=args.resume,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "verify":
            print(json.dumps(verify_run(Path(args.run_dir)), ensure_ascii=False, indent=2))
        elif args.command == "fork-profile":
            result = fork_profile(
                Path(args.from_run),
                profile=args.profile,
                reviewer=args.reviewer,
                reason=args.reason,
                transaction_id=args.transaction_id,
                resume=args.resume,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "matlab-recompute":
            from run_matlab_recomputation import run_recomputation

            output = Path(args.output) if args.output else Path(args.run_dir) / f"matlab_level_{args.level.lower()}_report.json"
            result = run_recomputation(Path(args.run_dir), Path(args.input), output, args.level)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
