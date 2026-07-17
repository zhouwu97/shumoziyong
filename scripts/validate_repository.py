from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
import hashlib
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_prompt_response import evaluate_case, load_case, evaluate_manifest_alignment
from evaluation_case_registry import validate_registry
from evidence_validation import derive_v2_matrix_results
from profile_derivation import derive_profile_report
from promotion_engine import evaluate_status_eligibility, load_json as pe_load_json, stable_evidence_digest
from run_workflow import (
    OPTIONAL_GATE_EVIDENCE_SPECS,
    evidence_required_artifacts_for_workflow,
    extend_formal_result_evidence_requirements,
    replay_transition_log,
    verify_run_seal,
)
from route_contract_dispatch import RouteContractError, load_dispatch_registry
from upstream.sync_mathmodelagent import (
    UpstreamIntegrityError,
    load_and_validate_metadata,
)
from upstream.validate_requirements import (
    MAPPING_FILE as UPSTREAM_MAPPING_FILE,
    REGISTRY_FILES as UPSTREAM_REGISTRY_FILES,
    validate_requirement_bundle,
)

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
    import yaml
except ImportError as exc:  # pragma: no cover - 只在依赖缺失时触发
    raise SystemExit("缺少 jsonschema 或 PyYAML，请先执行：pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
MATURITIES = {"draft", "review_ready", "regression_verified", "competition_evidenced", "deprecated"}
PROFILE_IDS = {"general", "engineering_optimization", "prediction", "evaluation", "simulation"}
REPOSITORY_SCAN_EXCLUDED_DIRS = {".git", ".vendor", "export", "tmp"}


class RepositoryValidator:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes: list[str] = []

    
    def resolve_repo_path(self, raw: str) -> Path:
        path = (ROOT / raw).resolve()
        root = ROOT.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"证据路径位于仓库外：{raw}")
        return path

    def pass_(self, message: str) -> None:
        self.passes.append(message)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def sha256_lf_text(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def load_json(self, relative_path: str) -> Any | None:
        path = ROOT / relative_path
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.fail(f"JSON 无法读取：{relative_path}（{exc}）")
            return None

    def validate_schema(self, data: Any, schema_name: str, display_name: str) -> bool:
        """Validate JSON against schema, return True if ok."""
        schema = self.load_json(f"schemas/{schema_name}")
        if schema is None:
            return False
        # 所有 Schema 都从仓库本地注册，$ref 不允许退化为外部网络请求。
        registry = Registry()
        for candidate in SCHEMA_DIR.glob("*.json"):
            candidate_schema = json.loads(candidate.read_text(encoding="utf-8"))
            schema_id = candidate_schema.get("$id")
            if isinstance(schema_id, str):
                registry = registry.with_resource(schema_id, Resource.from_contents(candidate_schema))
        errors = sorted(
            Draft202012Validator(
                schema,
                registry=registry,
                format_checker=FormatChecker(),
            ).iter_errors(data),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            for error in errors:
                location = ".".join(str(part) for part in error.absolute_path) or "<root>"
                self.fail(f"{display_name} Schema：{location}：{error.message}")
            return False
        self.pass_(f"{display_name} Schema")
        return True

    def validate_all_json_syntax(self) -> None:
        broken = 0
        for path in sorted(ROOT.rglob("*.json")):
            if any(part in REPOSITORY_SCAN_EXCLUDED_DIRS for part in path.parts):
                continue
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                broken += 1
                self.fail(f"JSON 格式：{path.relative_to(ROOT).as_posix()}（{exc}）")
        if broken == 0:
            self.pass_("仓库内全部 JSON 格式")

    def validate_patch_index(self) -> None:
        patches = self.load_json("prompt_patches/patch_index.json")
        if not isinstance(patches, list):
            self.fail("patch_index 必须是数组")
            return
        self.validate_schema(patches, "patch_index.schema.json", "patch_index")

        ids = [patch.get("patch_id") for patch in patches]
        duplicates = [patch_id for patch_id, count in Counter(ids).items() if count > 1]
        if duplicates:
            self.fail(f"patch ID 重复：{', '.join(duplicates)}")
        else:
            self.pass_("patch ID 唯一")

        for patch in patches:
            patch_id = patch.get("patch_id", "<unknown>")
            for field in ("file",):
                relative_path = patch.get(field)
                if relative_path and not (ROOT / relative_path).is_file():
                    self.fail(f"{patch_id} 的 {field} 路径不存在：{relative_path}")
            knowledge_card = patch.get("source", {}).get("knowledge_card")
            if knowledge_card and not (ROOT / knowledge_card).is_file():
                self.fail(f"{patch_id} 的知识卡片不存在：{knowledge_card}")
            claim_ids = patch.get("source", {}).get("claim_ids", [])
            if knowledge_card and (ROOT / knowledge_card).is_file():
                card = self.load_json(knowledge_card)
                source = card.get("source", {}) if isinstance(card, dict) else {}
                available_claims = {
                    claim.get("claim_id")
                    for claim in source.get("claims", [])
                    if isinstance(claim, dict)
                }
                missing_claims = set(claim_ids) - available_claims
                if missing_claims:
                    self.fail(f"{patch_id} 引用了知识卡片中不存在的 Claim ID：{sorted(missing_claims)}")
                if patch.get("status") in {
                    "regression_verified",
                    "competition_evidenced",
                }:
                    if source.get("verification_status") != "verified" or not claim_ids:
                        self.fail(
                            f"{patch_id} 进入 {patch.get('status')} 前必须引用已验证 Claim ID"
                        )
            records = patch.get("validation_records", [])
            for record in records:
                if not (ROOT / record).is_file():
                    self.fail(f"{patch_id} 的验证证据不存在：{record}")
            if patch.get("status") in {"regression_verified", "competition_evidenced"} and not records:
                self.fail(f"{patch_id} 为 {patch.get('status')}，但没有 validation_records")
        if not any("的" in failure and "不存在" in failure for failure in self.failures):
            self.pass_("patch 文件、知识卡片和验证证据路径")

    def validate_profiles(self) -> None:
        """验证 Profile 只保存证据引用，并由现场证据重算状态和只读报告。"""
        patches = self.load_json("prompt_patches/patch_index.json") or []
        found_profiles: set[str] = set()
        for path in sorted((ROOT / "runtime_profiles").glob("*.json")):
            data = self.load_json(path.relative_to(ROOT).as_posix())
            if not isinstance(data, dict):
                continue
            profile_id = data.get("profile_id", path.stem)
            found_profiles.add(profile_id)
            self.validate_schema(
                data, "runtime_profile.schema.json", f"runtime profile {profile_id}"
            )
            if path.stem != profile_id:
                self.fail(
                    f"runtime profile 文件名与 profile_id 不一致：{path.name} / {profile_id}"
                )
            report = derive_profile_report(data, patches, root=ROOT)
            if report["invalid_records"]:
                self.fail(
                    f"runtime profile {profile_id} 存在无效 validation_records："
                    f"{report['invalid_records']}"
                )
            if data.get("maturity") != report["computed_maturity"]:
                self.fail(
                    f"runtime profile {profile_id}.maturity 不能由证据重算："
                    f"记录为 {data.get('maturity')}，现场派生为 {report['computed_maturity']}"
                )
        missing = PROFILE_IDS - found_profiles
        if missing:
            self.fail(f"缺少 runtime 状态文件：{', '.join(sorted(missing))}")
        else:
            self.pass_("runtime 状态文件覆盖、证据引用和派生状态")
        return

    def validate_patch_profile_consistency(self) -> None:
        """已验证 Patch 必须引用存在的 Profile；正式选择不再依赖人工缓存列表。"""
        patches = self.load_json("prompt_patches/patch_index.json") or []
        existing_profiles = {
            path.stem for path in (ROOT / "runtime_profiles").glob("*.json")
        }
        invalid_refs: list[str] = []
        for patch in patches:
            if patch.get("status") not in {
                "regression_verified",
                "competition_evidenced",
            }:
                continue
            for profile_id in patch.get("runtime_profiles", []):
                if profile_id not in existing_profiles:
                    invalid_refs.append(f"{patch.get('patch_id')}->{profile_id}")
        if invalid_refs:
            self.fail(f"已验证 Patch 引用了不存在的 Profile：{', '.join(invalid_refs)}")
        else:
            self.pass_("正式 Patch 状态与 Profile 归属可现场派生")
        return

    def validate_patch_promotion(self) -> None:
        """晋级规则强制校验：委托给 promotion_engine（promotion_policy.json 的唯一事实源）。"""
        policy = self.load_json("policies/promotion_policy.json")
        matrix = self.load_json("tests/prompt_regression/patch_negative_control_matrix.json")
        patch_index = self.load_json("prompt_patches/patch_index.json") or []
        if matrix is None:
            return
        if not (ROOT / "policies" / "promotion_policy.json").is_file():
            self.fail("缺少 policies/promotion_policy.json")
            return
        policy = pe_load_json(ROOT / "policies" / "promotion_policy.json")

        matrix_is_v2 = matrix.get("matrix_version") == "2.0.0"
        if matrix_is_v2 and not self.validate_schema(
            matrix, "control_matrix.schema.json", "Patch 控制证据矩阵 v2"
        ):
            return

        promotion_ok = True
        if matrix_is_v2:
            matrix, evidence_errors = derive_v2_matrix_results(matrix, policy, root=ROOT)
            for error in evidence_errors:
                self.fail(f"v2 控制现场证据：{error}")
                promotion_ok = False
        matrix_by_id = {item.get("patch_id"): item for item in matrix.get("patches", [])}

        def normalize_prompt(text: str) -> str:
            return "\n".join(
                line.rstrip()
                for line in text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
            )

        def parse_iso8601(value: str) -> datetime:
            """解析带时区的 ISO 8601 时间，避免按字符串比较不同时区时间。"""
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("时间戳必须包含时区")
            return parsed

        def _is_legacy_evidence(
            run_dir: Path,
            target_patch: str,
            role: str,
            run_manifest: dict[str, Any],
            policy: dict[str, Any],
        ) -> bool:
            """仅放行政策中固定的历史证据，禁止新证据伪造 legacy 标记绕过门禁。"""
            neg_entry = matrix_by_id.get(target_patch, {}).get("negative", {})
            evidence = neg_entry.get("evidence") if isinstance(neg_entry.get("evidence"), dict) else {}
            if evidence.get("schema_generation") != "legacy_v1_grandfathered":
                return False

            requirements = policy.get("diagnosis_schema_requirements", {})
            group_id = run_manifest.get("experiment_group_id")
            allowlist = requirements.get("legacy_evidence_allowlist", [])
            expected_paths = requirements.get("legacy_evidence_paths", {}).get(group_id, {})
            valid = True
            if group_id not in allowlist:
                self.fail(f"{run_dir.name} legacy 证据组不在 allowlist：{group_id!r}")
                valid = False
            role_path_keys = {
                "baseline": "baseline_run",
                "patch_only": "treatment_run",
            }
            path_key = role_path_keys.get(role)
            if path_key is None:
                self.fail(f"未知实验角色：{role}")
                return False
            if evidence.get(path_key) != expected_paths.get(path_key):
                self.fail(f"{run_dir.name} legacy {path_key} 不是政策登记路径")
                valid = False
            if evidence.get("comparison_review") != expected_paths.get("comparison_review"):
                self.fail(f"{run_dir.name} legacy comparison_review 路径不是政策登记的历史路径")
                valid = False

            cutoff = requirements.get("legacy_evidence_cutoff")
            created_at = run_manifest.get("created_at")
            try:
                if not cutoff or not created_at or parse_iso8601(created_at) > parse_iso8601(cutoff):
                    self.fail(f"{run_dir.name} legacy 证据创建时间不早于 cutoff：{created_at!r}")
                    valid = False
            except (TypeError, ValueError):
                self.fail(f"{run_dir.name} legacy 证据 created_at/cutoff 不是合法带时区 ISO 8601 时间")
                valid = False
            return valid

        def _verify_run_evidence_manifest(
            run_dir: Path,
            run_manifest: dict[str, Any],
            policy: dict[str, Any],
            is_legacy: bool = False,
        ) -> bool:
            """验证证据引用的角色、路径、字节数和 SHA-256，形成可执行证据契约。"""
            ok = True
            reqs = policy.get("run_evidence_requirements", {}).get("ai_run_metadata_checks", {})
            manifest_path = run_dir / "run_evidence_manifest.json"
            if not manifest_path.is_file():
                self.fail(f"{run_dir.name} 缺少 run_evidence_manifest.json")
                return False
            try:
                evidence_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.fail(f"{run_dir.name} run_evidence_manifest.json 无法解析: {exc}")
                return False

            schema_name = Path(reqs.get("run_evidence_manifest_schema", "schemas/run_evidence_manifest.schema.json")).name
            if not self.validate_schema(evidence_manifest, schema_name, f"{run_dir.name} run_evidence_manifest"):
                ok = False
            if evidence_manifest.get("run_id") != run_manifest.get("run_id"):
                self.fail(f"{run_dir.name} run_evidence_manifest.run_id 与 run_manifest 不一致")
                ok = False

            workflow = run_manifest.get("workflow")
            if not isinstance(workflow, str):
                self.fail(f"{run_dir.name} run_manifest.workflow 非法")
                return False
            try:
                required_artifacts = evidence_required_artifacts_for_workflow(
                    workflow, completed=True
                )
            except ValueError as exc:
                self.fail(f"{run_dir.name} {exc}")
                return False
            if run_manifest.get("formal_result_policy") == "required_v1":
                try:
                    extend_formal_result_evidence_requirements(run_dir, required_artifacts)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    self.fail(f"{run_dir.name} Formal Result 证据链无效：{exc}")
                    return False

            required_roles = set(required_artifacts)
            seen_roles: set[str] = set()
            seen_paths: set[str] = set()
            run_root = run_dir.resolve()
            for artifact in evidence_manifest.get("artifacts", []):
                if not isinstance(artifact, dict):
                    continue
                role_name = artifact.get("role")
                if not isinstance(role_name, str):
                    self.fail(f"{run_dir.name} run_evidence_manifest.role 必须是字符串")
                    ok = False
                    continue
                if role_name in seen_roles:
                    self.fail(f"{run_dir.name} run_evidence_manifest.role 重复：{role_name}")
                    ok = False
                seen_roles.add(role_name)
                raw_path = artifact.get("path")
                if not isinstance(raw_path, str):
                    continue
                if raw_path in seen_paths:
                    self.fail(f"{run_dir.name} run_evidence_manifest.path 重复：{raw_path}")
                    ok = False
                seen_paths.add(raw_path)
                optional_artifacts = {
                    role: filename for filename, role in OPTIONAL_GATE_EVIDENCE_SPECS
                }
                optional_artifacts.update(
                    {
                        f"gate_{gate}_artifact_manifest": f"gate_artifacts/gate_{gate}.manifest.json"
                        for gate in range(6)
                    }
                )
                expected_path = required_artifacts.get(
                    role_name, optional_artifacts.get(role_name)
                )
                if expected_path is None:
                    self.fail(f"{run_dir.name} run_evidence_manifest 包含未知证据角色：{role_name}")
                    ok = False
                elif raw_path != expected_path:
                    self.fail(
                        f"{run_dir.name} run_evidence_manifest 角色 {role_name} 必须对应固定文件：{expected_path}"
                    )
                    ok = False
                artifact_path = (run_dir / raw_path).resolve()
                if not artifact_path.is_relative_to(run_root):
                    self.fail(f"{run_dir.name} run_evidence_manifest 路径位于运行目录外：{raw_path}")
                    ok = False
                    continue
                if not artifact_path.is_file():
                    self.fail(f"{run_dir.name} run_evidence_manifest 引用文件不存在：{raw_path}")
                    ok = False
                    continue
                actual_size = artifact_path.stat().st_size
                if artifact.get("size_bytes") != actual_size:
                    self.fail(f"{run_dir.name} run_evidence_manifest.size_bytes 不匹配：{raw_path}")
                    ok = False
                actual_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                if artifact.get("sha256") != actual_sha:
                    self.fail(f"{run_dir.name} run_evidence_manifest.sha256 不匹配：{raw_path}")
                    ok = False

            missing_roles = required_roles - seen_roles
            if missing_roles:
                self.fail(f"{run_dir.name} run_evidence_manifest 缺少证据角色：{', '.join(sorted(missing_roles))}")
                ok = False
            missing_paths = set(required_artifacts.values()) - seen_paths
            if missing_paths:
                self.fail(f"{run_dir.name} run_evidence_manifest 缺少固定证据文件：{', '.join(sorted(missing_paths))}")
                ok = False
            return ok

        def _verify_real_run(run_dir: Path, target_patch: str, role: str, *, allow_legacy: bool = True) -> bool:
            ok = True
            try:
                run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
                legacy = _is_legacy_evidence(run_dir, target_patch, role, run_manifest, policy)
                if legacy and not allow_legacy:
                    self.fail(f"{run_dir.name} 禁止使用 legacy 历史证据（allow_legacy=False）")
                    ok = False
                immutable_manifest = run_manifest.get("manifest_version") == "2.0.0"
                if immutable_manifest:
                    if run_manifest.get("promotion_evidence") is not True:
                        self.fail(f"{run_dir.name} 初始化时未声明 promotion_evidence=true")
                        ok = False
                else:
                    if not run_manifest.get("eligible_for_promotion"):
                        self.fail(f"{run_dir.name} eligible_for_promotion 为 false")
                        ok = False
                    if run_manifest.get("evidence_validity") != "real_ai_run":
                        self.fail(f"{run_dir.name} evidence_validity 不是 real_ai_run")
                        ok = False
                if not legacy:
                    if immutable_manifest:
                        try:
                            verify_run_seal(run_dir)
                        except (OSError, ValueError, json.JSONDecodeError) as exc:
                            self.fail(f"{run_dir.name} v2 封存记录无效：{exc}")
                            ok = False
                    else:
                        if run_manifest.get("run_status") != "completed":
                            self.fail(f"{run_dir.name} run_status 必须为 completed 才可作为晋级证据")
                            ok = False
                        if run_manifest.get("integrity_status") != "sealed":
                            self.fail(f"{run_dir.name} integrity_status 必须为 sealed 才可作为晋级证据")
                            ok = False
                    try:
                        state = replay_transition_log(run_dir)
                    except (OSError, ValueError, json.JSONDecodeError) as exc:
                        self.fail(f"{run_dir.name} Gate 状态机记录无效：{exc}")
                        ok = False
                    else:
                        if not state["completed"]:
                            self.fail(f"{run_dir.name} Gate 状态机未完成")
                            ok = False
                        if state["max_gate"] != 5:
                            self.fail(f"{run_dir.name} 晋级证据必须来自 Gate 0-5 完整运行")
                            ok = False
                        if matrix_is_v2 and state.get("transition_version") != "2.0.0":
                            self.fail(f"{run_dir.name} 晋级证据必须使用 Gate 语义完成契约 v2")
                            ok = False

                request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
                if not request.get("prompt"):
                    self.fail(f"{run_dir.name} request.prompt 为空")
                    ok = False
                if not request.get("model"):
                    self.fail(f"{run_dir.name} request.model 为空")
                    ok = False
                if request.get("source") != "real_ai_run":
                    self.fail(f"{run_dir.name} request.source 不是 real_ai_run")
                    ok = False
                if request.get("runtime_version") != run_manifest.get("runtime_version"):
                    self.fail(f"{run_dir.name} request.runtime_version 与 run_manifest.runtime_version 不一致")
                    ok = False

                response_text = (run_dir / "response.json").read_text(encoding="utf-8")
                response = json.loads(response_text)

                # 版本感知校验 + 晋级证据强制 v2 要求
                schema_version = response.get("schema_version", "1.0.0")
                try:
                    if schema_version.startswith("2."):
                        if not self.validate_schema(response, "diagnosis.schema.json", f"{run_dir.name} response.json"):
                            ok = False
                    else:
                        if not self.validate_schema(response, "diagnosis_output.schema.json", f"{run_dir.name} response.json"):
                            ok = False
                except Exception as e:
                    self.fail(f"{run_dir.name} response 不符合 diagnosis schema ({e})")
                    ok = False

                # 强制 v2 检查：新 evidence 不支持旧 v1
                diag_req = policy.get("diagnosis_schema_requirements", {})
                min_version = diag_req.get("minimum_schema_version", "1.0.0")
                cutoff = diag_req.get("legacy_evidence_cutoff", "")
                if not schema_version.startswith("2.") and min_version.startswith("2."):
                    if not legacy:
                        self.fail(
                            f"{run_dir.name} 使用 diagnosis v1（schema_version={schema_version}），"
                            f"但 policy 要求新晋级证据使用 v{min_version}+（cutoff={cutoff}）。"
                            "请重新运行并使用 diagnosis.schema.json v2 生成结构化输出。"
                        )
                        ok = False

                eval_json = json.loads((run_dir / "automatic_evaluation.json").read_text(encoding="utf-8"))
                if not eval_json.get("case_id"):
                    self.fail(f"{run_dir.name} automatic_evaluation.case_id 为空")
                    ok = False
                if eval_json.get("result") != "pass":
                    self.fail(f"{run_dir.name} automatic_evaluation.result 不是 pass")
                    ok = False
                if eval_json.get("errors"):
                    self.fail(f"{run_dir.name} automatic_evaluation.errors 非空")
                    ok = False
                
                # Check Hashes
                actual_resp_sha = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
                if eval_json.get("response_sha256") != actual_resp_sha:
                    self.fail(f"{run_dir.name} response_sha256 不匹配")
                    ok = False
                    
                manifest_text = (run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8")
                actual_man_sha = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
                if eval_json.get("manifest_sha256") != actual_man_sha:
                    self.fail(f"{run_dir.name} manifest_sha256 不匹配")
                    ok = False

                case_file = self.resolve_repo_path(eval_json.get("case_file", ""))
                actual_case_sha = hashlib.sha256(case_file.read_bytes()).hexdigest()
                if eval_json.get("case_sha256") != actual_case_sha:
                    self.fail(f"{run_dir.name} case_sha256 不匹配")
                    ok = False
                
                # Re-evaluate
                case = load_case(case_file, eval_json.get("case_id"))
                re_errors = evaluate_case(case, response)
                re_errors.extend(evaluate_manifest_alignment(response, json.loads(manifest_text)))
                if re_errors:
                    self.fail(f"{run_dir.name} 现场重算发现错误: {re_errors}")
                    ok = False

                # ===== AI 运行元数据校验 =====
                if not legacy:
                    required_files = policy.get("run_evidence_requirements", {}).get("required_run_files", [])
                    for required_file in required_files:
                        if not (run_dir / required_file).is_file():
                            self.fail(f"{run_dir.name} 缺少必需晋级证据文件：{required_file}")
                            ok = False
                ok = _verify_ai_run_metadata(run_dir, policy, target_patch, role, legacy) and ok
                if not legacy:
                    ok = _verify_run_evidence_manifest(run_dir, run_manifest, policy, legacy) and ok

            except Exception as e:
                self.fail(f"读取 {run_dir} 证据时出错: {e}")
                ok = False
            return ok

        def _verify_ai_run_metadata(
            run_dir: Path,
            policy: dict[str, Any],
            target_patch: str,
            role: str,
            legacy: bool,
        ) -> bool:
            """校验 ai_run_metadata.json：Schema、哈希一致性、合法性。"""
            ok = True
            meta_path = run_dir / "ai_run_metadata.json"
            reqs = policy.get("run_evidence_requirements", {}).get("ai_run_metadata_checks", {})

            if not meta_path.is_file():
                if legacy:
                    return True  # grandfathered 旧证据不要求 ai_run_metadata
                self.fail(f"{run_dir.name} 缺少 ai_run_metadata.json（非 legacy 证据必须提供）")
                return False

            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                self.fail(f"{run_dir.name} ai_run_metadata.json 无法解析: {e}")
                return False

            # Schema
            if not self.validate_schema(meta, "ai_run_metadata.schema.json", f"{run_dir.name} ai_run_metadata"):
                ok = False

            if meta.get("status") != "completed":
                self.fail(f"{run_dir.name} ai_run_metadata.status 必须为 completed 才可作为晋级证据")
                ok = False

            # metadata_version_minimum 必须真实执行，不能只写在政策中。
            minimum_version = reqs.get("metadata_version_minimum")
            try:
                current_version = tuple(int(part) for part in str(meta.get("metadata_version", "")).split("."))
                minimum = tuple(int(part) for part in str(minimum_version).split("."))
                if len(current_version) != 3 or len(minimum) != 3 or current_version < minimum:
                    self.fail(
                        f"{run_dir.name} ai_run_metadata.metadata_version {meta.get('metadata_version')!r} "
                        f"低于政策最低版本 {minimum_version}"
                    )
                    ok = False
            except ValueError:
                self.fail(f"{run_dir.name} ai_run_metadata.metadata_version 不是合法 SemVer")
                ok = False

            # 非空 provider/model
            if reqs.get("require_non_empty_provider") and not meta.get("provider"):
                self.fail(f"{run_dir.name} ai_run_metadata.provider 为空")
                ok = False
            if reqs.get("require_non_empty_model") and not meta.get("model"):
                self.fail(f"{run_dir.name} ai_run_metadata.model 为空")
                ok = False
            try:
                request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            else:
                if request.get("model") != meta.get("model"):
                    self.fail(f"{run_dir.name} request.model 与 ai_run_metadata.model 不一致")
                    ok = False

            # started_at 必须存在且为 ISO 8601
            if reqs.get("require_started_at_iso8601") and not meta.get("started_at"):
                self.fail(f"{run_dir.name} ai_run_metadata.started_at 为空")
                ok = False

            # completed_at < started_at 检查
            if reqs.get("reject_completed_before_started"):
                started = meta.get("started_at", "")
                completed = meta.get("completed_at")
                if isinstance(completed, str) and completed and isinstance(started, str) and started:
                    try:
                        completed_at = parse_iso8601(completed)
                        started_at = parse_iso8601(started)
                    except ValueError:
                        self.fail(f"{run_dir.name} ai_run_metadata 时间不是合法带时区 ISO 8601")
                        ok = False
                    else:
                        if completed_at < started_at:
                            self.fail(f"{run_dir.name} ai_run_metadata.completed_at ({completed}) 早于 started_at ({started})")
                            ok = False

            # prompt_sha256 匹配
            if reqs.get("require_prompt_sha256_match"):
                expected = meta.get("prompt_sha256", "")
                if expected:
                    try:
                        req = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
                        prompt_text = req.get("prompt", "")
                        normalized = "\n".join(
                            line.rstrip() for line in prompt_text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
                        )
                        actual_sha = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                        if actual_sha != expected:
                            self.fail(f"{run_dir.name} ai_run_metadata.prompt_sha256 不匹配（期望 {expected}，实际 {actual_sha}）")
                            ok = False
                    except (OSError, json.JSONDecodeError):
                        pass

            # runtime_pack_sha256 匹配
            if reqs.get("require_runtime_pack_sha256_match"):
                expected = meta.get("runtime_pack_sha256", "")
                rp_path = run_dir / "runtime_pack.md"
                manifest_path = run_dir / "runtime_pack.manifest.json"
                if not rp_path.is_file():
                    self.fail(f"{run_dir.name} 缺少 runtime_pack.md")
                    ok = False
                else:
                    actual_sha = hashlib.sha256(rp_path.read_bytes()).hexdigest()
                    if expected != actual_sha:
                        self.fail(f"{run_dir.name} ai_run_metadata.runtime_pack_sha256 不匹配（期望 {expected}，实际 {actual_sha}）")
                        ok = False
                    if not manifest_path.is_file():
                        self.fail(f"{run_dir.name} 缺少 runtime_pack.manifest.json")
                        ok = False
                    else:
                        try:
                            runtime_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                            manifest_sha = runtime_manifest.get("runtime_pack_sha256")
                            if manifest_sha != actual_sha:
                                self.fail(f"{run_dir.name} runtime_pack.manifest.json.runtime_pack_sha256 与 runtime_pack.md 不一致")
                                ok = False
                            if manifest_sha != expected:
                                self.fail(f"{run_dir.name} runtime_pack.manifest.json.runtime_pack_sha256 与 ai_run_metadata 不一致")
                                ok = False
                        except (OSError, json.JSONDecodeError) as exc:
                            self.fail(f"{run_dir.name} runtime_pack.manifest.json 无法解析: {exc}")
                            ok = False

            # problem_material_digest 匹配
            if reqs.get("require_problem_material_digest_match"):
                expected = meta.get("problem_material_digest", "")
                pm_path = run_dir / "problem_manifest.json"
                if not pm_path.is_file():
                    self.fail(f"{run_dir.name} 缺少 problem_manifest.json")
                    ok = False
                else:
                    try:
                        pm = json.loads(pm_path.read_text(encoding="utf-8"))
                        actual = pm.get("content_digest")
                        if not actual:
                            self.fail(f"{run_dir.name} problem_manifest.content_digest 缺失")
                            ok = False
                        elif actual != expected:
                            self.fail(f"{run_dir.name} ai_run_metadata.problem_material_digest 不匹配（期望 {expected}，实际 {actual}）")
                            ok = False
                    except (OSError, json.JSONDecodeError) as exc:
                        self.fail(f"{run_dir.name} problem_manifest.json 无法解析: {exc}")
                        ok = False

            # 绝对路径拒绝
            if reqs.get("reject_absolute_paths_in_note"):
                note = meta.get("note", "")
                if isinstance(note, str) and note:
                    import re as _re
                    if _re.search(r"[A-Za-z]:[/\\]", note):
                        self.fail(f"{run_dir.name} ai_run_metadata.note 包含可能的本机绝对路径")
                        ok = False

            return ok
            
        def verify_experiment_pair(b_dir: Path, t_dir: Path, target_patch: str) -> bool:
            ok = True
            try:
                b_man = json.loads((b_dir / "run_manifest.json").read_text(encoding="utf-8"))
                t_man = json.loads((t_dir / "run_manifest.json").read_text(encoding="utf-8"))
                
                if b_man.get("experiment_group_id") != t_man.get("experiment_group_id"):
                    self.fail(f"experiment_group_id 不同: {b_man.get('experiment_group_id')} vs {t_man.get('experiment_group_id')}")
                    ok = False
                if b_man.get("experiment_role") != "baseline":
                    self.fail(f"baseline role 错误: {b_man.get('experiment_role')}")
                    ok = False
                if t_man.get("experiment_role") != "patch_only":
                    self.fail(f"treatment role 错误: {t_man.get('experiment_role')}")
                    ok = False
                if t_man.get("target_patch") != target_patch:
                    self.fail(f"treatment target_patch 错误: {t_man.get('target_patch')}")
                    ok = False
                if b_man.get("problem_id") != t_man.get("problem_id"):
                    self.fail("problem_id 不同")
                    ok = False
                if b_man.get("profile") != t_man.get("profile"):
                    self.fail("profile 不同")
                    ok = False
                if b_man.get("runtime_version") != t_man.get("runtime_version"):
                    self.fail("runtime_version 不同")
                    ok = False
                
                b_req = json.loads((b_dir / "request.json").read_text(encoding="utf-8"))
                b_resp_text = (b_dir / "response.json").read_text(encoding="utf-8")
                t_resp_text = (t_dir / "response.json").read_text(encoding="utf-8")
                if hashlib.sha256(b_resp_text.encode("utf-8")).hexdigest() == hashlib.sha256(t_resp_text.encode("utf-8")).hexdigest():
                    self.fail("baseline 和 treatment 的 response 完全相同")
                    ok = False

                t_req = json.loads((t_dir / "request.json").read_text(encoding="utf-8"))
                if b_req.get("model") != t_req.get("model"):
                    self.fail("request.model 不同")
                    ok = False
                if normalize_prompt(b_req.get("prompt", "")) != normalize_prompt(t_req.get("prompt", "")):
                    self.fail("规范化后的 prompt 不同")
                    ok = False
                    
                b_pm = json.loads((b_dir / "problem_manifest.json").read_text(encoding="utf-8"))
                t_pm = json.loads((t_dir / "problem_manifest.json").read_text(encoding="utf-8"))
                if b_pm != t_pm:
                    self.fail("problem_manifest 完全不同")
                    ok = False
                
                b_rm = json.loads((b_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8"))
                t_rm = json.loads((t_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8"))
                b_active = {p.get("patch_id") for p in b_rm.get("patches", [])}
                t_active = {p.get("patch_id") for p in t_rm.get("patches", [])}
                
                if t_active - b_active != {target_patch}:
                    self.fail("active patches 增加的不止 target_patch")
                    ok = False
                if b_active - t_active != set():
                    self.fail("active patches 减少了其他 patch")
                    ok = False

                # baseline/treatment AI 运行元数据一致性
                ok = _verify_metadata_pair(b_dir, t_dir, policy) and ok

            except Exception as e:
                self.fail(f"校验对照实验组时出错: {e}")
                ok = False
            return ok

        def _verify_metadata_pair(b_dir: Path, t_dir: Path, policy: dict[str, Any]) -> bool:
            """验证 baseline 和 treatment 的 ai_run_metadata 一致性。"""
            ok = True
            b_meta_path = b_dir / "ai_run_metadata.json"
            t_meta_path = t_dir / "ai_run_metadata.json"

            reqs = policy.get("run_evidence_requirements", {}).get("ai_run_metadata_checks", {})
            match_fields = reqs.get("baseline_treatment_must_match", [])

            if not b_meta_path.is_file() or not t_meta_path.is_file():
                return ok  # 缺少的已在 _verify_real_run 中报告

            try:
                b_meta = json.loads(b_meta_path.read_text(encoding="utf-8"))
                t_meta = json.loads(t_meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return ok

            for field in match_fields:
                b_val = b_meta.get(field)
                t_val = t_meta.get(field)
                if b_val != t_val:
                    self.fail(
                        f"baseline/treatment ai_run_metadata.{field} 不一致："
                        f"{b_val!r} vs {t_val!r}"
                    )
                    ok = False

            return ok

        def _collect_stable_inner_hashes(patch: dict[str, Any]) -> dict[str, str]:
            """现场计算 stable 证据组件哈希，禁止把路径文字当作内容绑定。"""
            patch_id = patch.get("patch_id", "<unknown>")
            evidence = patch.get("stable_evidence")
            if not isinstance(evidence, dict):
                return {}

            hashes: dict[str, str] = {}

            def add_file(key: str, raw_path: Any, label: str) -> None:
                if isinstance(raw_path, Path):
                    path = raw_path
                else:
                    if not isinstance(raw_path, str) or not raw_path:
                        self.fail(f"{patch_id} stable_evidence 缺少 {label}，无法生成内容摘要")
                        return
                    try:
                        path = self.resolve_repo_path(raw_path)
                    except ValueError as exc:
                        self.fail(f"{patch_id} stable_evidence {label} 路径无效：{exc}")
                        return
                if not path.is_file():
                    self.fail(f"{patch_id} stable_evidence {label} 文件不存在：{raw_path}")
                    return
                hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()

            for index, item in enumerate(evidence.get("negative_control_runs", [])):
                if not isinstance(item, dict):
                    continue
                for role, field in (("baseline", "baseline_run"), ("treatment", "treatment_run")):
                    raw_run = item.get(field)
                    if not isinstance(raw_run, str) or not raw_run:
                        self.fail(f"{patch_id} stable_evidence 负控缺少 {field}，无法生成内容摘要")
                        continue
                    try:
                        run_dir = self.resolve_repo_path(raw_run)
                    except ValueError as exc:
                        self.fail(f"{patch_id} stable_evidence {field} 路径无效：{exc}")
                        continue
                    add_file(
                        f"negative_control_runs/{index}/{role}/run_evidence_manifest.json",
                        run_dir / "run_evidence_manifest.json",
                        f"{field} 的 run_evidence_manifest.json",
                    )
                add_file(
                    f"negative_control_runs/{index}/comparison_review",
                    item.get("comparison_review"),
                    "comparison_review",
                )

            for index, item in enumerate(evidence.get("failure_fix_retests", [])):
                if not isinstance(item, dict):
                    continue
                for key in ("failure_record", "fix_record", "review_record"):
                    add_file(f"failure_fix_retests/{index}/{key}", item.get(key), key)
                raw_run = item.get("retest_run")
                if isinstance(raw_run, str) and raw_run:
                    try:
                        run_dir = self.resolve_repo_path(raw_run)
                    except ValueError as exc:
                        self.fail(f"{patch_id} stable_evidence retest_run 路径无效：{exc}")
                    else:
                        add_file(
                            f"failure_fix_retests/{index}/retest_evidence_manifest.json",
                            run_dir / "run_evidence_manifest.json",
                            "retest_run 的 run_evidence_manifest.json",
                        )
                else:
                    self.fail(f"{patch_id} stable_evidence 缺少 retest_run，无法生成内容摘要")

            for index, item in enumerate(evidence.get("competition_validation_records", [])):
                if not isinstance(item, dict):
                    continue
                add_file(
                    f"competition_validation_records/{index}/runtime_pack_manifest",
                    item.get("runtime_pack_manifest"),
                    "runtime_pack_manifest",
                )
                add_file(
                    f"competition_validation_records/{index}/result_record",
                    item.get("result_record"),
                    "result_record",
                )
            return dict(sorted(hashes.items()))

        for patch in patch_index:
            patch_id = patch.get("patch_id", "<unknown>")
            status = patch.get("status")
            if status not in {"regression_verified", "competition_evidenced"}:
                continue
            entry = matrix_by_id.get(patch_id)
            if entry is None:
                self.fail(f"{patch_id} 标记为 {status}，但负控矩阵中没有该 patch 的记录")
                promotion_ok = False
                continue

            patch_file = self.resolve_repo_path(str(patch.get("file", "")))
            if patch_file.is_file():
                patch["_resolved_patch_sha256"] = hashlib.sha256(patch_file.read_bytes()).hexdigest()
            if status == "competition_evidenced":
                patch["_resolved_inner_sha256s"] = _collect_stable_inner_hashes(patch)

            # 委托给 promotion_engine（promotion_policy.json 唯一事实源）
            report = evaluate_status_eligibility(
                patch, entry, policy, status,
                all_matrix_entries=matrix_by_id,
            )
            for gap in report.gaps:
                self.fail(f"{patch_id}：{gap}")
                promotion_ok = False

            # 负控证据验证（补充：promotion_engine 检查证据字段存在性，
            # 这里深入验证证据目录内部的真实文件、哈希、对照实验一致性）
            for control in ("positive", "boundary", "negative"):
                control_data = entry.get(control, {})
                result = control_data.get("result")
                if result != "pass":
                    continue

                if control == "negative":
                    matrix_case = control_data.get("case")
                    if not matrix_case:
                        self.fail(f"{patch_id} negative-control 缺少 case")
                        promotion_ok = False
                        continue

                    evidence = control_data.get("evidence")
                    if not isinstance(evidence, dict) or not all(k in evidence for k in ["baseline_run", "treatment_run", "comparison_review"]):
                        self.fail(f"{patch_id} negative-control 为 pass，但缺少结构化 evidence 或必填字段")
                        promotion_ok = False
                        continue

                    try:
                        b_run = self.resolve_repo_path(evidence["baseline_run"])
                        t_run = self.resolve_repo_path(evidence["treatment_run"])
                        c_rev = self.resolve_repo_path(evidence["comparison_review"])

                        if not _verify_real_run(b_run, patch_id, "baseline"): promotion_ok = False
                        if not _verify_real_run(t_run, patch_id, "patch_only"): promotion_ok = False
                        if not verify_experiment_pair(b_run, t_run, patch_id): promotion_ok = False

                        # Validate comparison review json（v2：允许 fail/invalid/needs_retest）
                        rev_data = json.loads(c_rev.read_text(encoding="utf-8"))
                        if not self.validate_schema(rev_data, "comparison_review.schema.json", f"{patch_id} comparison_review"):
                            promotion_ok = False
                        else:
                            # promotion_engine 只检查存在性；这里验证 review 结论是否满足晋级要求
                            if rev_data.get("final_result") != "pass":
                                self.fail(
                                    f"{patch_id} comparison_review final_result 为 {rev_data.get('final_result')}（必须为 pass 才可作为 promotion evidence）"
                                )
                                promotion_ok = False
                            risk_flags = rev_data.get("risk_flags", {})
                            for flag_name, flag_value in risk_flags.items():
                                if flag_value is True:
                                    self.fail(
                                        f"{patch_id} comparison_review risk_flags.{flag_name} 为 true（负控通过要求所有 risk flags 为 false）"
                                    )
                                    promotion_ok = False

                        b_man = json.loads(b_run.joinpath("run_manifest.json").read_text(encoding="utf-8"))
                        t_man = json.loads(t_run.joinpath("run_manifest.json").read_text(encoding="utf-8"))
                        baseline_case = b_man.get("problem_id")
                        treatment_case = t_man.get("problem_id")
                        if matrix_case != baseline_case or matrix_case != treatment_case:
                            self.fail(
                                f"{patch_id} negative.case 与运行题号不一致："
                                f"{matrix_case} / {baseline_case} / {treatment_case}"
                            )
                            promotion_ok = False

                        if rev_data.get("experiment_group_id") != b_man.get("experiment_group_id") or rev_data.get("experiment_group_id") != t_man.get("experiment_group_id"):
                            self.fail(f"{patch_id} comparison_review experiment_group_id 与运行组不一致")
                            promotion_ok = False

                        if rev_data.get("baseline_run") != evidence["baseline_run"]:
                            self.fail(f"{patch_id} comparison_review baseline_run 路径不匹配")
                            promotion_ok = False
                        if rev_data.get("treatment_run") != evidence["treatment_run"]:
                            self.fail(f"{patch_id} comparison_review treatment_run 路径不匹配")
                            promotion_ok = False
                        if rev_data.get("target_patch") != patch_id:
                            self.fail(f"{patch_id} comparison_review target_patch 错误")
                            promotion_ok = False

                    except Exception as e:
                        self.fail(f"校验 {patch_id} 证据时出错: {e}")
                        promotion_ok = False

        def _verify_stable_evidence(patch: dict[str, Any]) -> bool:
            """深度验证 stable 证据，禁止仅凭路径存在或手填布尔值晋级。"""
            patch_id = patch.get("patch_id", "<unknown>")
            evidence = patch.get("stable_evidence")
            if not isinstance(evidence, dict):
                self.fail(f"{patch_id} 缺失 stable_evidence 对象")
                return False

            ok = True
            policy_version = policy.get("policy_version")
            if not isinstance(policy_version, str) or not policy_version.strip():
                self.fail(f"{patch_id} promotion policy 缺少合法 policy_version")
                return False

            def _read_json_file(path: Path, label: str) -> dict[str, Any] | None:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    self.fail(f"{patch_id} stable_evidence {label} 无法解析：{exc}")
                    return None
                if not isinstance(data, dict):
                    self.fail(f"{patch_id} stable_evidence {label} 必须是 JSON 对象")
                    return None
                return data

            def _verify_comparison_review(
                review_path: Path,
                review_ref: str,
                baseline_ref: str,
                treatment_ref: str,
                b_dir: Path,
                t_dir: Path,
                expected_group_id: str,
                expected_case: str | None = None,
            ) -> bool:
                review_ok = True
                if not review_path.is_file():
                    self.fail(f"{patch_id} stable_evidence comparison_review 不存在：{review_ref}")
                    return False
                rev_data = _read_json_file(review_path, "comparison_review")
                if rev_data is None:
                    return False
                if not self.validate_schema(rev_data, "comparison_review.schema.json", f"{patch_id} stable comparison_review"):
                    review_ok = False
                if rev_data.get("final_result") != "pass":
                    self.fail(f"{patch_id} stable comparison_review final_result 必须为 pass")
                    review_ok = False
                for flag_name, flag_value in rev_data.get("risk_flags", {}).items():
                    if flag_value is True:
                        self.fail(f"{patch_id} stable comparison_review risk_flags.{flag_name} 为 true")
                        review_ok = False
                for check_name, check_value in rev_data.get("consistency_checks", {}).items():
                    if check_value is not True:
                        self.fail(f"{patch_id} stable comparison_review consistency_checks.{check_name} 不是 true")
                        review_ok = False

                try:
                    b_man = json.loads((b_dir / "run_manifest.json").read_text(encoding="utf-8"))
                    t_man = json.loads((t_dir / "run_manifest.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    self.fail(f"{patch_id} stable 负控运行 manifest 无法解析：{exc}")
                    return False

                if rev_data.get("experiment_group_id") != expected_group_id:
                    self.fail(f"{patch_id} stable comparison_review experiment_group_id 与 stable_evidence 不一致")
                    review_ok = False
                if rev_data.get("experiment_group_id") not in {b_man.get("experiment_group_id"), t_man.get("experiment_group_id")}:
                    self.fail(f"{patch_id} stable comparison_review experiment_group_id 与运行组不一致")
                    review_ok = False
                if rev_data.get("baseline_run") != baseline_ref:
                    self.fail(f"{patch_id} stable comparison_review baseline_run 路径不匹配")
                    review_ok = False
                if rev_data.get("treatment_run") != treatment_ref:
                    self.fail(f"{patch_id} stable comparison_review treatment_run 路径不匹配")
                    review_ok = False
                if rev_data.get("target_patch") != patch_id:
                    self.fail(f"{patch_id} stable comparison_review target_patch 错误")
                    review_ok = False
                if expected_case and (b_man.get("problem_id") != expected_case or t_man.get("problem_id") != expected_case):
                    self.fail(f"{patch_id} stable 负控 case 与运行题号不一致")
                    review_ok = False
                return review_ok

            negative_runs = evidence.get("negative_control_runs", [])
            if not isinstance(negative_runs, list):
                self.fail(f"{patch_id} stable_evidence.negative_control_runs 必须是数组")
                negative_runs = []
                ok = False
            seen_groups: set[str] = set()
            for nc in negative_runs:
                if not isinstance(nc, dict):
                    self.fail(f"{patch_id} stable_evidence 负控条目必须是对象")
                    ok = False
                    continue
                group_id = nc.get("experiment_group_id")
                if not isinstance(group_id, str) or not group_id.strip():
                    self.fail(f"{patch_id} stable_evidence 负控缺少 experiment_group_id")
                    ok = False
                    continue
                if group_id in seen_groups:
                    self.fail(f"{patch_id} stable_evidence 存在重复的负控组 {group_id}")
                    ok = False
                seen_groups.add(group_id)

                baseline_ref = nc.get("baseline_run")
                treatment_ref = nc.get("treatment_run")
                review_ref = nc.get("comparison_review")
                if not all(isinstance(v, str) and v for v in (baseline_ref, treatment_ref, review_ref)):
                    self.fail(f"{patch_id} stable_evidence 负控 {group_id} 缺少运行或审查路径")
                    ok = False
                    continue
                assert isinstance(baseline_ref, str)
                assert isinstance(treatment_ref, str)
                assert isinstance(review_ref, str)
                b_run = self.resolve_repo_path(baseline_ref)
                t_run = self.resolve_repo_path(treatment_ref)
                c_rev = self.resolve_repo_path(review_ref)
                if not b_run.is_dir():
                    self.fail(f"{patch_id} stable_evidence 负控 baseline_run 路径无效: {baseline_ref}")
                    ok = False
                if not t_run.is_dir():
                    self.fail(f"{patch_id} stable_evidence 负控 treatment_run 路径无效: {treatment_ref}")
                    ok = False
                if b_run.is_dir():
                    ok = _verify_real_run(b_run, patch_id, "baseline", allow_legacy=False) and ok
                if t_run.is_dir():
                    ok = _verify_real_run(t_run, patch_id, "patch_only", allow_legacy=False) and ok
                if b_run.is_dir() and t_run.is_dir():
                    ok = verify_experiment_pair(b_run, t_run, patch_id) and ok
                    ok = _verify_comparison_review(
                        c_rev,
                        review_ref,
                        baseline_ref,
                        treatment_ref,
                        b_run,
                        t_run,
                        group_id,
                        nc.get("case") if isinstance(nc.get("case"), str) else None,
                    ) and ok

            retests = evidence.get("failure_fix_retests", [])
            if not isinstance(retests, list):
                self.fail(f"{patch_id} stable_evidence.failure_fix_retests 必须是数组")
                retests = []
                ok = False
            for idx, fix in enumerate(retests, start=1):
                if not isinstance(fix, dict):
                    self.fail(f"{patch_id} stable_evidence 失败重测 #{idx} 必须是对象")
                    ok = False
                    continue
                resolved: dict[str, Path] = {}
                for key in ("failure_record", "fix_record", "retest_run", "review_record"):
                    raw = fix.get(key)
                    if not isinstance(raw, str) or not raw:
                        self.fail(f"{patch_id} stable_evidence 失败重测 #{idx} 缺少 {key}")
                        ok = False
                        continue
                    path = self.resolve_repo_path(raw)
                    resolved[key] = path
                    exists = path.is_dir() if key == "retest_run" else path.is_file()
                    if not exists:
                        self.fail(f"{patch_id} stable_evidence 失败重测 {key} 路径无效: {raw}")
                        ok = False
                retest_dir = resolved.get("retest_run")
                if retest_dir and retest_dir.is_dir():
                    ok = _verify_real_run(retest_dir, patch_id, "patch_only") and ok
                    retest_eval = _read_json_file(retest_dir / "automatic_evaluation.json", "失败重测 automatic_evaluation")
                    if retest_eval and retest_eval.get("result") != "pass":
                        self.fail(f"{patch_id} stable_evidence 失败重测结果必须为 pass")
                        ok = False
                    retest_manifest = _read_json_file(retest_dir / "run_manifest.json", "失败重测 run_manifest")
                    if retest_manifest and retest_manifest.get("target_patch") != patch_id:
                        self.fail(f"{patch_id} stable_evidence 失败重测 target_patch 与当前 Patch 不一致")
                        ok = False
                for key in ("failure_record", "fix_record", "review_record"):
                    record_path = resolved.get(key)
                    if record_path and record_path.is_file() and record_path.suffix.lower() == ".json":
                        record = _read_json_file(record_path, key)
                        if record is None:
                            ok = False
                            continue
                        record_patch = record.get("patch_id", record.get("target_patch"))
                        if record_patch is not None and record_patch != patch_id:
                            self.fail(f"{patch_id} stable_evidence 失败重测 {key} 绑定到其他 Patch：{record_patch}")
                            ok = False
                        if key == "failure_record" and not any(k in record for k in ("failure_label", "failure_labels", "original_failure", "failure")):
                            self.fail(f"{patch_id} stable_evidence failure_record 缺少原失败描述或标签")
                            ok = False
                        if key == "review_record" and record.get("decision") not in ("approved", "pass"):
                            self.fail(f"{patch_id} stable_evidence review_record 必须批准失败修复重测")
                            ok = False

            competitions = evidence.get("competition_validation_records", [])
            if not isinstance(competitions, list):
                self.fail(f"{patch_id} stable_evidence.competition_validation_records 必须是数组")
                competitions = []
                ok = False
            for comp in competitions:
                if not isinstance(comp, dict):
                    self.fail(f"{patch_id} stable_evidence 比赛验证条目必须是对象")
                    ok = False
                    continue
                manifest_ref = comp.get("runtime_pack_manifest")
                if not isinstance(manifest_ref, str) or not manifest_ref:
                    self.fail(f"{patch_id} stable_evidence 缺少比赛 manifest 路径")
                    ok = False
                    continue
                resolved_man = self.resolve_repo_path(manifest_ref)
                if not resolved_man.is_file():
                    self.fail(f"{patch_id} stable_evidence 比赛 manifest 不存在: {manifest_ref}")
                    ok = False
                    continue
                man_sha = hashlib.sha256(resolved_man.read_bytes()).hexdigest()
                if comp.get("runtime_pack_manifest_sha256") != man_sha:
                    self.fail(f"{patch_id} stable_evidence 比赛 manifest SHA256 不匹配")
                    ok = False
                man_data = _read_json_file(resolved_man, "比赛 runtime manifest")
                if man_data is None:
                    ok = False
                    continue
                if not self.validate_schema(man_data, "runtime_pack_manifest.schema.json", f"{patch_id} stable 比赛 runtime manifest"):
                    ok = False
                patch_entries = man_data.get("patches")
                if not isinstance(patch_entries, list):
                    self.fail(f"{patch_id} stable_evidence 比赛 manifest 缺少 patches 数组")
                    ok = False
                    patch_entries = []
                matching = [entry for entry in patch_entries if isinstance(entry, dict) and entry.get("patch_id") == patch_id]
                if len(matching) != 1:
                    self.fail(f"{patch_id} stable_evidence 比赛 manifest 中 Patch 条目数量必须为 1，实际 {len(matching)}")
                    ok = False
                else:
                    patch_entry = matching[0]
                    if patch_entry.get("path") != patch.get("file"):
                        self.fail(f"{patch_id} stable_evidence 比赛 manifest Patch path 与 patch_index.file 不一致")
                        ok = False
                    status_value = patch_entry.get("status")
                    if status_value not in MATURITIES:
                        self.fail(f"{patch_id} stable_evidence 比赛 manifest Patch status 非法：{status_value}")
                        ok = False
                    patch_file = self.resolve_repo_path(str(patch.get("file", "")))
                    if not patch_file.is_file():
                        self.fail(f"{patch_id} stable_evidence 比赛 Patch 文件不存在：{patch.get('file')}")
                        ok = False
                    else:
                        patch_sha = hashlib.sha256(patch_file.read_bytes()).hexdigest()
                        if patch_entry.get("sha256") != patch_sha:
                            self.fail(f"{patch_id} stable_evidence 比赛 manifest Patch sha256 与实际文件不一致")
                            ok = False

                result_ref = comp.get("result_record")
                if not isinstance(result_ref, str) or not result_ref:
                    self.fail(f"{patch_id} stable_evidence 比赛验证缺少 result_record")
                    ok = False
                    continue
                result_path = self.resolve_repo_path(result_ref)
                if not result_path.is_file():
                    self.fail(f"{patch_id} stable_evidence 比赛 result_record 不存在: {result_ref}")
                    ok = False
                    continue
                result_data = _read_json_file(result_path, "比赛 result_record")
                if result_data is None:
                    ok = False
                    continue
                if not self.validate_schema(result_data, "result_record.schema.json", f"{patch_id} stable 比赛 result_record"):
                    ok = False
                result_value = result_data.get("result", result_data.get("final_result"))
                if result_value != "pass":
                    self.fail(f"{patch_id} stable_evidence 比赛 result_record 结果必须为 pass")
                    ok = False
                result_patch = result_data.get("patch_id", result_data.get("target_patch"))
                if result_patch is not None and result_patch != patch_id:
                    self.fail(f"{patch_id} stable_evidence 比赛 result_record Patch 不一致")
                    ok = False
                result_manifest_ref = result_data.get("runtime_pack_manifest")
                if result_manifest_ref is not None and result_manifest_ref != manifest_ref:
                    self.fail(f"{patch_id} stable_evidence 比赛题目、运行包和结果记录不属于同一次运行")
                    ok = False
                result_manifest_sha = result_data.get("runtime_pack_manifest_sha256")
                if result_manifest_sha is not None and result_manifest_sha != man_sha:
                    self.fail(f"{patch_id} stable_evidence 比赛 result_record manifest SHA256 不一致")
                    ok = False

            approval = evidence.get("human_approval_record")
            if not isinstance(approval, dict):
                self.fail(f"{patch_id} stable_evidence 缺少 human_approval_record")
                return False
            expected_digest = stable_evidence_digest(
                patch, 
                evidence, 
                patch_sha256=patch.get("_resolved_patch_sha256", ""),
                inner_component_sha256s=patch.get("_resolved_inner_sha256s", {}),
                policy_version=policy_version,
            )
            if approval.get("evidence_digest") != expected_digest:
                self.fail(f"{patch_id} stable_evidence 人工批准 evidence_digest 与当前证据不匹配")
                ok = False
            if approval.get("decision") not in (None, "approved"):
                self.fail(f"{patch_id} stable_evidence 人工批准 decision 必须为 approved")
                ok = False
            if approval.get("policy_version") != policy_version:
                self.fail(f"{patch_id} stable_evidence 人工批准 policy_version 与当前策略不一致")
                ok = False
            reviewer = approval.get("reviewer", approval.get("approved_by", ""))
            if not isinstance(reviewer, str) or not reviewer.strip():
                self.fail(f"{patch_id} stable_evidence 人工批准 reviewer 不能为空")
                ok = False

            return ok

        for patch in patch_index:
            if patch.get("status") == "competition_evidenced":
                if not _verify_stable_evidence(patch):
                    promotion_ok = False

        if promotion_ok:
            self.pass_("patch 晋级规则（promotion_policy.json 统一评估 + 负控证据验证）")


    def validate_knowledge_cards(self) -> None:
        paths = list((ROOT / "papers").glob("*_知识卡片.json"))
        paths.extend((ROOT / "papers" / "templates").glob("知识卡片模板.json"))
        paths.extend((ROOT / "output" / "pdf").glob("*_knowledge_card.json"))
        for path in sorted(paths):
            data = self.load_json(path.relative_to(ROOT).as_posix())
            if data is not None:
                self.validate_schema(data, "knowledge_card.schema.json", f"知识卡片 {path.name}")

    def validate_optional_records(self) -> None:
        groups = [
            ("tests/old_problems", "*.json", "old_problem_test.schema.json", "旧题记录"),
            ("reviews/failure_cards", "*.json", "failure_card.schema.json", "失败复盘"),
        ]
        for directory, pattern, schema_name, label in groups:
            for path in sorted((ROOT / directory).glob(pattern)):
                data = self.load_json(path.relative_to(ROOT).as_posix())
                if data is not None:
                    self.validate_schema(data, schema_name, f"{label} {path.name}")

        manifest_path = ROOT / "export" / "cumcm_runtime_pack.manifest.json"
        if manifest_path.is_file():
            manifest = self.load_json("export/cumcm_runtime_pack.manifest.json")
            if manifest is not None:
                self.validate_schema(manifest, "runtime_manifest.schema.json", "runtime manifest")

    def validate_markdown_links(self) -> None:
        link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
        missing: list[str] = []
        for path in sorted(ROOT.rglob("*.md")):
            if any(part in REPOSITORY_SCAN_EXCLUDED_DIRS for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            for target in link_pattern.findall(text):
                clean_target = target.strip().split("#", 1)[0]
                if not clean_target or clean_target.startswith(("http://", "https://", "mailto:")):
                    continue
                destination = (path.parent / clean_target).resolve()
                if not destination.exists():
                    missing.append(f"{path.relative_to(ROOT).as_posix()} -> {target}")
        if missing:
            for item in missing:
                self.fail(f"Markdown 内部链接失效：{item}")
        else:
            self.pass_("Markdown 内部链接")

    def validate_training_log_duplicates(self) -> None:
        path = ROOT / "training_log.md"
        rows = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if re.match(r"^\|\s*20\d{2}-\d{2}-\d{2}\s*\|", line)
        ]
        duplicates = [row for row, count in Counter(rows).items() if count > 1]
        if duplicates:
            self.fail(f"training_log 存在 {len(duplicates)} 条完全重复记录")
        else:
            self.pass_("training_log 无完全重复记录")

    def validate_prompt_regression_cases(self) -> None:
        case_ids: list[str] = []
        for path in sorted((ROOT / "tests" / "prompt_regression").glob("test_*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                self.fail(f"提示词回归 YAML 无法读取：{path.name}（{exc}）")
                continue
            cases = data.get("cases", []) if isinstance(data, dict) else []
            if not cases:
                self.fail(f"提示词回归文件没有 cases：{path.name}")
                continue
            for case in cases:
                case_id = case.get("case_id")
                expected = case.get("expected", {})
                if not case_id or not case.get("input") or not expected:
                    self.fail(f"提示词回归用例字段不完整：{path.name}")
                    continue
                if not expected.get("must_have_paths"):
                    self.fail(f"提示词回归用例缺少 must_have_paths：{case_id}")
                case_ids.append(case_id)
        duplicates = [case_id for case_id, count in Counter(case_ids).items() if count > 1]
        if duplicates:
            self.fail(f"提示词回归 case_id 重复：{', '.join(duplicates)}")
        elif case_ids:
            self.pass_(f"提示词回归用例结构与 ID（{len(case_ids)} 个）")

        matrix = self.load_json("tests/prompt_regression/patch_negative_control_matrix.json")
        patch_index = self.load_json("prompt_patches/patch_index.json") or []
        if matrix is not None:
            matrix_ids = {item.get("patch_id") for item in matrix.get("patches", [])}
            patch_ids = {item.get("patch_id") for item in patch_index}
            if matrix_ids != patch_ids:
                self.fail("负控矩阵与 patch_index 的 patch ID 集合不一致")
            else:
                self.pass_("patch 负控矩阵覆盖全部已注册 patch")

    def validate_evaluation_case_registry(self) -> None:
        """复用共享注册表检查，避免 CI 与本地总校验规则漂移。"""
        registry_path = "tests/prompt_regression/evaluation_case_registry.json"
        registry = self.load_json(registry_path)
        if not isinstance(registry, dict):
            return
        issues = validate_registry(registry, root=ROOT)
        if issues:
            for issue in issues:
                self.fail(f"晋级自动评估用例注册表：{issue}")
        else:
            self.pass_("晋级自动评估用例注册表 Schema、LF、哈希和授权约束")

    def validate_capability_framework(self) -> None:
        """检查国奖竞争力路线的政策与新增合同，避免文档与机器接口脱节。"""
        policy = self.load_json("policies/capability_maturity_policy.json")
        required_statuses = [
            "foundation",
            "runtime_trusted",
            "contract_ready",
            "executor_validated",
            "profile_qualified",
            "benchmark_candidate",
            "competition_ready",
            "national_award_competitive",
        ]
        if not isinstance(policy, dict):
            self.fail("能力成熟度政策无法读取")
        elif policy.get("ordered_statuses") != required_statuses:
            self.fail("能力成熟度政策的状态顺序不符合固定资格链")
        elif any(status not in policy for status in required_statuses):
            self.fail("能力成熟度政策缺少状态判定规则")
        else:
            self.pass_("能力成熟度政策状态链")

        for schema_name in (
            "capability_evidence.schema.json",
            "model_route_v2.schema.json",
            "execution_spec.schema.json",
            "executor_handoff.schema.json",
            "executor_blocker.schema.json",
            "execution_record.schema.json",
            "formal_result_envelope.schema.json",
            "domain_manifest.schema.json",
            "formal_result_bundle_manifest.schema.json",
            "formal_result_core_artifact.schema.json",
            "formal_result_decision_variables.schema.json",
            "formal_result_provenance_manifest.schema.json",
            "collector_attestation.schema.json",
            "sandboxie_environment_report.schema.json",
            "sandboxie_environment_attestation.schema.json",
            "sandboxie_run_execution_attestation.schema.json",
            "formal_result_payload_manifest.schema.json",
            "collector_derivation_attestation.schema.json",
            "trusted_environment_registry.schema.json",
            "gate_3_check_evidence.schema.json",
            "gate_3_execution_attestation.schema.json",
            "gate_3_input_manifest.schema.json",
            "gate_3_validator_contract.schema.json",
            "model_text_consistency_report.schema.json",
            "paper_profile.schema.json",
            "paper_candidate_manifest.schema.json",
            "paper_humanization_report.schema.json",
            "paper_figure_build_report.schema.json",
            "paper_figure_spec.schema.json",
            "paper_render_attestation.schema.json",
            "paper_source_manifest.schema.json",
            "paper_template_manifest.schema.json",
            "paper_visual_review.schema.json",
            "paper_verify_report.schema.json",
            "paper_external_precheck_report.schema.json",
            "suggested_repairs.schema.json",
            "paper_production_manifest_v2.schema.json",
            "paper_narrative_contract.schema.json",
            "paper_narrative_input.schema.json",
            "paper_narrative_report.schema.json",
            "template_source_manifest.schema.json",
            "template_overlay.schema.json",
            "template_selection.schema.json",
            "upstream_requirement_registry.schema.json",
            "upstream_requirement_mapping.schema.json",
            "competition_production_adapter_report.schema.json",
            "competition_production_capability.schema.json",
            "model_route_v3.schema.json",
            "route_comparison_result.schema.json",
            "operability_contract.schema.json",
            "operability_report.schema.json",
            "risk_decision_contract.schema.json",
            "risk_decision_report.schema.json",
            "route_execution_report.schema.json",
            "competition_gate3_decision.schema.json",
            "score_v3_policy.schema.json",
            "score_v3_ratings.schema.json",
            "score_v3.schema.json",
            "route_contract_dispatch.schema.json",
            "competition_integration_fixture_campaign.schema.json",
            "competition_integration_fixture_manifest.schema.json",
            "competition_full_replay_run_record.schema.json",
            "competition_integration_fixture_report.schema.json",
            "competition_full_replay_acceptance.schema.json",
            "competition_full_replay_acceptance_manifest.schema.json",
            "competition_full_replay_acceptance_report.schema.json",
            "problem_replay_requirements_registry.schema.json",
            "problem_semantics_registry.schema.json",
            "paper_semantic_map.schema.json",
            "paper_semantic_report.schema.json",
            "problem_validator_registry.schema.json",
            "problem_validator_report.schema.json",
            "competition_qualification_protocol.schema.json",
            "competition_qualification_authority_registry.schema.json",
            "competition_qualification_evidence.schema.json",
            "competition_qualification_report.schema.json",
            "competition_qualification_protocol_v2.schema.json",
            "competition_qualification_authority_registry_v2.schema.json",
            "competition_qualification_evidence_v2.schema.json",
            "competition_qualification_report_v2.schema.json",
            "competition_qualification_protocol_v3.schema.json",
            "competition_qualification_authority_registry_v3.schema.json",
            "competition_qualification_evidence_v3.schema.json",
            "competition_qualification_report_v3.schema.json",
            "competition_72h_simulation_protocol.schema.json",
            "competition_72h_simulation_authority_registry.schema.json",
            "competition_72h_simulation_evidence.schema.json",
            "competition_72h_simulation_report.schema.json",
            "competition_72h_simulation_status.schema.json",
        ):
            schema = self.load_json(f"schemas/{schema_name}")
            if schema is None:
                continue
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as exc:  # jsonschema 会提供包含路径的具体结构错误。
                self.fail(f"能力合同 Schema 无效：{schema_name}（{exc}）")
            else:
                self.pass_(f"能力合同 Schema：{schema_name}")

        paper_profile = self.load_json("paper_profiles/cumcm_academic_v1.json")
        if paper_profile is not None:
            self.validate_schema(
                paper_profile,
                "paper_profile.schema.json",
                "CUMCM 提交论文 Profile",
            )

        trusted_registry = self.load_json("policies/trusted_environment_registry.json")
        if trusted_registry is not None:
            self.validate_schema(
                trusted_registry,
                "trusted_environment_registry.schema.json",
                "可信环境机器公钥注册表",
            )

    def validate_upstream_source_lock(self) -> None:
        try:
            _lock, manifest = load_and_validate_metadata()
        except (OSError, UpstreamIntegrityError) as exc:
            self.fail(f"MathModelAgent 上游来源锁：{exc}")
            return
        if manifest.get("file_count") != 389:
            self.fail("MathModelAgent 上游来源锁：固定文件数不是 389")
            return
        ignore_lines = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        }
        if ".vendor/mathmodelagent/" not in ignore_lines:
            self.fail("MathModelAgent 上游来源锁：本地 Source Asset 未被 Git 忽略")
            return
        self.pass_("MathModelAgent 上游来源锁、许可与逐文件哈希")

    def validate_upstream_requirements(self) -> None:
        requirements_root = "runtime_contracts/upstream_requirements"
        for filename in UPSTREAM_REGISTRY_FILES:
            registry = self.load_json(f"{requirements_root}/{filename}")
            if registry is not None:
                self.validate_schema(
                    registry,
                    "upstream_requirement_registry.schema.json",
                    f"上游需求注册表 {filename}",
                )
        mapping = self.load_json(f"{requirements_root}/{UPSTREAM_MAPPING_FILE}")
        if mapping is not None:
            self.validate_schema(
                mapping,
                "upstream_requirement_mapping.schema.json",
                "上游需求映射注册表",
            )
        issues = validate_requirement_bundle(ROOT)
        if issues:
            for issue in issues:
                self.fail(f"上游需求映射闭包：{issue}")
        else:
            self.pass_("上游需求来源、映射与 Adapter 权限闭包")

    def validate_route_contract_dispatch(self) -> None:
        registry = self.load_json("runtime_contracts/route_contract_dispatch_v1.json")
        if registry is None:
            return
        self.validate_schema(
            registry,
            "route_contract_dispatch.schema.json",
            "路线合同版本分派注册表",
        )
        try:
            load_dispatch_registry(ROOT)
        except RouteContractError as exc:
            self.fail(f"路线合同版本分派：{exc}")
        else:
            self.pass_("路线合同 v2/v3 兼容、历史哈希与 review_ready 边界")

    def validate_score_v3_policy(self) -> None:
        policy = self.load_json("runtime_contracts/score_v3_policy_v1.json")
        if policy is None:
            return
        self.validate_schema(policy, "score_v3_policy.schema.json", "score_v3 固定政策")
        weights = policy.get("weights", {})
        if not isinstance(weights, dict) or abs(
            sum(float(value) for value in weights.values()) - 1.0
        ) > 1e-12:
            self.fail("score_v3 九维权重和不为 1")
            return
        legacy = policy.get("legacy_namespace", {})
        if legacy != {
            "artifact_type": "score_v2",
            "fatal_codes": ["F1", "F2", "F3", "F4", "F5"],
            "reinterpretation_forbidden": True,
        }:
            self.fail("score_v3 改写了 score_v2/F1-F5 历史命名空间")
            return
        self.pass_("score_v3 九维权重、70 分封顶与历史命名空间隔离")

    def validate_competition_production_capability(self) -> None:
        capability = self.load_json(
            "runtime_contracts/competition_production_capability_v1.json"
        )
        if capability is None:
            return
        self.validate_schema(
            capability,
            "competition_production_capability.schema.json",
            "Competition Production 能力生命周期",
        )
        lifecycle = capability.get("lifecycle")
        allowed_lifecycles = {
            "review_ready",
            "integration_fixture_campaign_passed",
            "full_replay_passed",
            "qualification_candidate",
            "blind_review_passed",
            "human_assisted_review_passed",
            "default_candidate",
        }
        if lifecycle not in allowed_lifecycles:
            self.fail("Competition Production 生命周期非法")
        elif lifecycle != "default_candidate" and capability.get("activation_contexts") != [
            "full_replay"
        ]:
            self.fail("Competition Production 晋级前只允许显式 full_replay")
        elif capability.get("new_problem_default_enabled") is True and lifecycle != "default_candidate":
            self.fail("只有 default_candidate 才可能启用 new_problem 默认能力")
        elif lifecycle == "integration_fixture_campaign_passed":
            evidence = capability.get("promotion_evidence", {})
            report_path = ROOT / str(evidence.get("path", ""))
            report = self.load_json(str(evidence.get("path", "")))
            actual_sha = self.sha256_lf_text(report_path) if report_path.is_file() else None
            if report is None:
                return
            report_valid = self.validate_schema(
                report,
                "competition_integration_fixture_report.schema.json",
                "Competition Production 集成 fixture 证据报告",
            )
            if not report_valid:
                return
            if actual_sha != evidence.get("sha256"):
                self.fail("Competition Production 晋级报告哈希漂移")
            elif report.get("status") != "passed" or report.get(
                "derived_lifecycle"
            ) != "integration_fixture_campaign_passed":
                self.fail("Competition Production 报告未证明 integration_fixture_campaign_passed")
            elif report.get("new_problem_default_enabled") is not False:
                self.fail("Competition Production 晋级报告错误启用 new_problem")
            else:
                self.pass_("Competition Production integration_fixture_campaign_passed 证据闭包")
        elif lifecycle == "full_replay_passed":
            evidence = capability.get("promotion_evidence", {})
            report_path = ROOT / str(evidence.get("path", ""))
            report = self.load_json(str(evidence.get("path", "")))
            actual_sha = self.sha256_lf_text(report_path) if report_path.is_file() else None
            if report is None:
                return
            if not self.validate_schema(
                report,
                "competition_full_replay_acceptance_report.schema.json",
                "Competition Production 完整官方旧题回放准入报告",
            ):
                return
            if actual_sha != evidence.get("sha256"):
                self.fail("Competition Production 完整回放报告哈希漂移")
            elif report.get("status") != "passed" or report.get(
                "derived_lifecycle"
            ) != "full_replay_passed":
                self.fail("Competition Production 完整回放报告未证明 full_replay_passed")
            elif report.get("new_problem_default_enabled") is not False:
                self.fail("Competition Production 完整回放报告错误启用 new_problem")
            else:
                self.pass_("Competition Production full_replay_passed 证据闭包")
        else:
            qualification_ref = capability.get("qualification_evidence", {})
            report_path = ROOT / str(qualification_ref.get("path", ""))
            report = self.load_json(str(qualification_ref.get("path", "")))
            actual_sha = self.sha256_lf_text(report_path) if report_path.is_file() else None
            if lifecycle == "review_ready":
                self.pass_("Competition Production review_ready 生命周期边界")
            elif report is None:
                self.fail("Competition Production 高阶生命周期缺少资格报告")
            elif not self.validate_schema(
                report,
                (
                    "competition_qualification_report_v3.schema.json"
                    if str(qualification_ref.get("path", "")).endswith("_v3.json")
                    else (
                        "competition_qualification_report_v2.schema.json"
                        if str(qualification_ref.get("path", "")).endswith("_v2.json")
                        else "competition_qualification_report.schema.json"
                    )
                ),
                "Competition Production 资格晋级报告",
            ):
                return
            elif actual_sha != qualification_ref.get("sha256"):
                self.fail("Competition Production 资格报告哈希漂移")
            elif report.get("derived_lifecycle") != (
                "blind_review_passed" if lifecycle == "default_candidate" else lifecycle
            ) or report.get("status") != (
                "blind_review_passed" if lifecycle == "default_candidate" else lifecycle
            ):
                self.fail("Competition Production 资格报告与登记生命周期不一致")
            elif report.get("new_problem_default_enabled") is not False:
                self.fail("资格报告不得自行启用 new_problem 默认能力")
            elif lifecycle == "default_candidate":
                simulation_ref = capability.get("simulation_evidence", {})
                simulation_path = ROOT / str(simulation_ref.get("path", ""))
                simulation_report = self.load_json(str(simulation_ref.get("path", "")))
                simulation_sha = (
                    self.sha256_lf_text(simulation_path)
                    if simulation_path.is_file()
                    else None
                )
                if simulation_report is None:
                    self.fail("default_candidate 缺少 72 小时模拟赛报告")
                elif not self.validate_schema(
                    simulation_report,
                    "competition_72h_simulation_report.schema.json",
                    "Competition Production 72 小时模拟赛报告",
                ):
                    return
                elif simulation_sha != simulation_ref.get("sha256"):
                    self.fail("72 小时模拟赛报告哈希漂移")
                elif simulation_report.get("status") != "competition_72h_simulation_passed":
                    self.fail("72 小时模拟赛报告未证明通过")
                else:
                    self.pass_("Competition Production default_candidate 双证据闭包")
            else:
                self.pass_(f"Competition Production {lifecycle} 资格证据闭包")

    def validate_integration_fixture_campaign_contract(self) -> None:
        contract = self.load_json(
            "runtime_contracts/competition_integration_fixture_campaign_v1.json"
        )
        manifest = self.load_json(
            "capability_evidence/competition_production/integration_fixture/campaign_manifest_v1.json"
        )
        if contract is None or manifest is None:
            return
        contract_valid = self.validate_schema(
            contract,
            "competition_integration_fixture_campaign.schema.json",
            "Competition Production 集成 fixture Campaign 合同",
        )
        manifest_valid = self.validate_schema(
            manifest,
            "competition_integration_fixture_manifest.schema.json",
            "Competition Production 集成 fixture Campaign 索引",
        )
        if not contract_valid or not manifest_valid:
            return
        expected_problems = {"2016-C", "2023-B", "2024-B", "2024-C", "2024-D"}
        contract_problems = {
            item.get("problem_id") for item in contract.get("required_problems", [])
        }
        manifest_problems = {item.get("problem_id") for item in manifest.get("runs", [])}
        run_ids = [item.get("run_id") for item in manifest.get("runs", [])]
        plugin = contract.get("required_runtime_plugin", {})
        plugin_path = ROOT / str(plugin.get("path", ""))
        actual_plugin_sha = (
            hashlib.sha256(plugin_path.read_bytes()).hexdigest()
            if plugin_path.is_file()
            else None
        )
        expected_contract_ref = {
            "path": "runtime_contracts/competition_integration_fixture_campaign_v1.json",
            "sha256": hashlib.sha256(
                (ROOT / "runtime_contracts/competition_integration_fixture_campaign_v1.json").read_bytes()
            ).hexdigest(),
        }
        if contract_problems != expected_problems or manifest_problems != expected_problems:
            self.fail("集成 fixture Campaign 未恰好覆盖固定五题")
        elif len(run_ids) != len(set(run_ids)):
            self.fail("集成 fixture Campaign 的五个 Run ID 不唯一")
        elif manifest.get("contract") != expected_contract_ref:
            self.fail("集成 fixture Campaign 索引未绑定当前合同哈希")
        elif actual_plugin_sha != plugin.get("sha256"):
            self.fail("集成 fixture Campaign 合同中的 Adapter 哈希漂移")
        elif contract.get("new_problem_default_enabled") is not False:
            self.fail("集成 fixture Campaign 不得启用 new_problem 默认能力")
        else:
            self.pass_("集成 fixture Campaign 固定题集、唯一 Run 与 Adapter 哈希闭包")

    def validate_full_replay_acceptance_contract(self) -> None:
        contract = self.load_json(
            "runtime_contracts/competition_full_replay_acceptance_v1.json"
        )
        if contract is None:
            return
        if self.validate_schema(
            contract,
            "competition_full_replay_acceptance.schema.json",
            "Competition Production 完整官方旧题回放准入合同",
        ):
            self.pass_("完整回放要求官方全材料、逐问复算、题目专用 Validator 与完整论文")

    def validate_problem_semantics_registry(self) -> None:
        registry = self.load_json("runtime_contracts/problem_semantics_registry_v1.json")
        if registry is None:
            return
        if not self.validate_schema(
            registry,
            "problem_semantics_registry.schema.json",
            "题目论文语义注册表",
        ):
            return
        problems = registry.get("problems", [])
        problem_ids = [item.get("problem_id") for item in problems]
        expected = {"2016-C", "2023-B", "2024-B", "2024-C", "2024-D"}
        sections = set(registry.get("required_section_aliases", {}))
        acceptance = self.load_json(
            "runtime_contracts/competition_full_replay_acceptance_v1.json"
        )
        if acceptance is None:
            return
        required_sections = set(
            acceptance.get("paper_requirements", {}).get("required_sections", [])
        )
        if len(problem_ids) != len(set(problem_ids)) or set(problem_ids) != expected:
            self.fail("题目论文语义注册表未唯一覆盖固定五题")
        elif sections != required_sections:
            self.fail("题目论文语义章节与完整回放合同不一致")
        else:
            self.pass_("题目论文语义实体、禁入主题、逐问绑定与正式章节闭包")

    def validate_problem_validator_registry(self) -> None:
        registry = self.load_json("runtime_contracts/problem_validator_registry_v1.json")
        if registry is None:
            return
        if not self.validate_schema(
            registry,
            "problem_validator_registry.schema.json",
            "题目专用 Validator 注册表",
        ):
            return
        entries = registry.get("validators", [])
        problem_ids = [item.get("problem_id") for item in entries]
        expected = {"2016-C", "2023-B", "2024-B", "2024-C", "2024-D"}
        hashes_valid = True
        for entry in entries:
            module_path = ROOT / str(entry.get("module_path", ""))
            if not module_path.is_file() or hashlib.sha256(module_path.read_bytes()).hexdigest() != entry.get("module_sha256"):
                hashes_valid = False
                break
        if len(problem_ids) != len(set(problem_ids)) or set(problem_ids) != expected:
            self.fail("题目专用 Validator 注册表未唯一覆盖固定五题")
        elif not hashes_valid:
            self.fail("题目专用 Validator 模块缺失或哈希漂移")
        else:
            active_count = sum(item.get("status") == "active" for item in entries)
            self.pass_(
                f"五题 Validator 注册与哈希闭包（active={active_count}/5；其余失败关闭）"
            )

    def validate_problem_replay_requirements(self) -> None:
        registry = self.load_json(
            "runtime_contracts/problem_replay_requirements_registry_v1.json"
        )
        if registry is None:
            return
        if not self.validate_schema(
            registry,
            "problem_replay_requirements_registry.schema.json",
            "完整回放逐题输出要求注册表",
        ):
            return
        entries = registry.get("problems", [])
        problem_ids = [item.get("problem_id") for item in entries]
        expected = {"2016-C", "2023-B", "2024-B", "2024-C", "2024-D"}
        if len(problem_ids) != len(set(problem_ids)) or set(problem_ids) != expected:
            self.fail("完整回放输出要求未唯一覆盖固定五题")
        else:
            self.pass_("完整回放逐题子问题与附件输出要求闭包")

    def validate_competition_qualification_contract(self) -> None:
        """验证历史协议、单人工辅助协议与可信双外部人工协议。"""
        expected_slots = ["Q01", "Q02", "Q03", "Q04", "Q05", "Q06"]
        expected_metrics = {
            "model_quality",
            "executable_solution_rate",
            "paper_quality",
            "manual_revision_minutes",
            "conclusion_overclaim_rate",
        }
        variants = (
            (
                "v1",
                "runtime_contracts/competition_qualification_protocol_v1.json",
                "policies/competition_qualification_authorities_v1.json",
                "competition_qualification_protocol.schema.json",
                "competition_qualification_authority_registry.schema.json",
                2,
                "human_reviewer",
            ),
            (
                "v2",
                "runtime_contracts/competition_qualification_protocol_v2.json",
                "policies/competition_qualification_authorities_v2.json",
                "competition_qualification_protocol_v2.schema.json",
                "competition_qualification_authority_registry_v2.schema.json",
                1,
                "human_qualification_owner",
            ),
            (
                "v3",
                "runtime_contracts/competition_qualification_protocol_v3.json",
                "policies/competition_qualification_authorities_v3.json",
                "competition_qualification_protocol_v3.schema.json",
                "competition_qualification_authority_registry_v3.schema.json",
                2,
                "external_human_reviewer",
            ),
        )
        for (
            version,
            protocol_path,
            registry_path,
            protocol_schema,
            registry_schema,
            reviewers_per_package,
            required_role,
        ) in variants:
            protocol = self.load_json(protocol_path)
            registry = self.load_json(registry_path)
            if protocol is None or registry is None:
                continue
            protocol_valid = self.validate_schema(
                protocol,
                protocol_schema,
                f"Competition Production 资格协议 {version}",
            )
            registry_valid = self.validate_schema(
                registry,
                registry_schema,
                f"Competition Production 资格公钥注册表 {version}",
            )
            if not protocol_valid or not registry_valid:
                continue
            if protocol.get("case_slots") != expected_slots:
                self.fail(f"资格协议 {version} 未冻结六个唯一隐藏题槽位")
            elif set(protocol.get("metrics", [])) != expected_metrics:
                self.fail(f"资格协议 {version} 未覆盖固定五项基线对比指标")
            elif protocol.get("blinding", {}).get("reviewers_per_package") != reviewers_per_package:
                self.fail(f"资格协议 {version} 的每包人工决定数不符合冻结值")
            elif version in {"v2", "v3"} and (
                protocol.get("blinding", {}).get("ai_decision_authority") is not False
                or protocol.get("blinding", {}).get("human_decision_required") is not True
            ):
                self.fail(f"资格协议 {version} 未冻结人工决策、AI 仅记录边界")
            elif registry.get("status") == "unconfigured" and registry.get("keys") == []:
                self.pass_(f"资格协议 {version} 已预注册；人工公钥尚未配置，生命周期保持不晋级")
            elif registry.get("status") == "active":
                roles = [item.get("role") for item in registry.get("keys", [])]
                minimum = 2 if version in {"v1", "v3"} else 1
                if roles.count(required_role) < minimum:
                    self.fail(f"active 资格公钥注册表 {version} 缺少所需人工角色")
                elif version == "v1" and roles.count("qualification_coordinator") < 1:
                    self.fail("active 资格公钥注册表 v1 缺少资格协调员")
                elif version == "v3" and roles.count("independent_coordinator") < 1:
                    self.fail("active 资格公钥注册表 v3 缺少独立协调员")
                else:
                    self.pass_(f"资格协议 {version} 与人工公钥信任边界")
            else:
                self.fail(f"资格评审公钥注册表 {version} 状态非法")

    def validate_competition_72h_simulation_contract(self) -> None:
        """验证 72 小时模拟赛预注册协议和未运行事实状态。"""
        protocol = self.load_json(
            "runtime_contracts/competition_72h_simulation_protocol_v1.json"
        )
        registry = self.load_json(
            "policies/competition_72h_simulation_authorities_v1.json"
        )
        status = self.load_json(
            "capability_evidence/competition_production/simulation/status_v1.json"
        )
        if protocol is None or registry is None or status is None:
            return
        valid = self.validate_schema(
            protocol,
            "competition_72h_simulation_protocol.schema.json",
            "Competition Production 72 小时模拟赛协议",
        )
        valid = self.validate_schema(
            registry,
            "competition_72h_simulation_authority_registry.schema.json",
            "Competition Production 72 小时模拟赛人工公钥注册表",
        ) and valid
        valid = self.validate_schema(
            status,
            "competition_72h_simulation_status.schema.json",
            "Competition Production 72 小时模拟赛当前状态",
        ) and valid
        if not valid:
            return
        if registry.get("status") == "unconfigured" and status.get("status") == "not_run":
            self.pass_("72 小时模拟赛已预注册，当前如实保持 not_run 且不可晋级")
        else:
            self.fail("72 小时模拟赛当前仓库状态与未配置人工观察员事实不一致")

    def validate_template_registry(self) -> None:
        registry = self.load_json("runtime_contracts/template_source_manifest_v1.json")
        overlay = self.load_json("runtime_contracts/template_overlay_v1.json")
        if registry is None or overlay is None:
            return
        registry_valid = self.validate_schema(
            registry,
            "template_source_manifest.schema.json",
            "模板来源注册表",
        )
        overlay_valid = self.validate_schema(
            overlay,
            "template_overlay.schema.json",
            "Windows 模板覆盖层",
        )
        keys = registry.get("logical_keys", [])
        templates = registry.get("templates", [])
        if not registry_valid or not overlay_valid:
            return
        if len(keys) != 17 or len(templates) != 34:
            self.fail("模板注册表必须包含 17 个逻辑键和 34 套引擎模板")
        elif any(item.get("default_engine") != "typst" for item in keys):
            self.fail("模板注册表默认引擎必须是 Typst")
        elif any(item.get("fallback_engine") != "xelatex" for item in keys):
            self.fail("模板注册表回退引擎必须是 XeLaTeX")
        elif any(item.get("upstream_default_overridden") is not True for item in keys):
            self.fail("模板注册表未记录 upstream_default_overridden=true")
        else:
            self.pass_("模板注册表数量、引擎与上游默认覆盖边界")

    def run(self) -> int:
        self.validate_all_json_syntax()
        self.validate_patch_index()
        self.validate_profiles()
        self.validate_patch_profile_consistency()
        self.validate_patch_promotion()
        self.validate_knowledge_cards()
        self.validate_optional_records()
        self.validate_markdown_links()
        self.validate_training_log_duplicates()
        self.validate_prompt_regression_cases()
        self.validate_evaluation_case_registry()
        self.validate_capability_framework()
        self.validate_upstream_source_lock()
        self.validate_upstream_requirements()
        self.validate_route_contract_dispatch()
        self.validate_score_v3_policy()
        self.validate_competition_production_capability()
        self.validate_integration_fixture_campaign_contract()
        self.validate_full_replay_acceptance_contract()
        self.validate_problem_semantics_registry()
        self.validate_problem_validator_registry()
        self.validate_problem_replay_requirements()
        self.validate_competition_qualification_contract()
        self.validate_competition_72h_simulation_contract()
        self.validate_template_registry()
        for message in self.passes:
            print(f"[PASS] {message}")
        for message in self.failures:
            print(f"[FAIL] {message}")
        print(f"\n校验完成：{len(self.passes)} 项通过，{len(self.failures)} 项失败。")
        return 1 if self.failures else 0


def main() -> None:
    raise SystemExit(RepositoryValidator().run())


if __name__ == "__main__":
    main()
