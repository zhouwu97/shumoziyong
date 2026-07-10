from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_prompt_response import evaluate_case, load_case, evaluate_manifest_alignment
from promotion_engine import evaluate_status_eligibility, load_json as pe_load_json

try:
    from jsonschema import Draft202012Validator, FormatChecker
    import yaml
except ImportError as exc:  # pragma: no cover - 只在依赖缺失时触发
    raise SystemExit("缺少 jsonschema 或 PyYAML，请先执行：pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
MATURITIES = {"draft", "candidate", "verified_candidate", "stable", "deprecated"}
PROFILE_IDS = {"general", "engineering_optimization", "prediction", "evaluation", "simulation"}


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

    def load_json(self, relative_path: str) -> Any | None:
        path = ROOT / relative_path
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.fail(f"JSON 无法读取：{relative_path}（{exc}）")
            return None

    def validate_schema(self, data: Any, schema_name: str, display_name: str) -> bool:
        """Validate JSON against schema, return True if ok."""
        from jsonschema import Draft202012Validator, FormatChecker
        schema = self.load_json(f"schemas/{schema_name}")
        if schema is None:
            return False
        errors = sorted(
            Draft202012Validator(
                schema,
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
            if ".git" in path.parts:
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
            records = patch.get("validation_records", [])
            for record in records:
                if not (ROOT / record).is_file():
                    self.fail(f"{patch_id} 的验证证据不存在：{record}")
            if patch.get("status") in {"verified_candidate", "stable"} and not records:
                self.fail(f"{patch_id} 为 {patch.get('status')}，但没有 validation_records")
        if not any("的" in failure and "不存在" in failure for failure in self.failures):
            self.pass_("patch 文件、知识卡片和验证证据路径")

    def validate_profiles(self) -> None:
        patches = self.load_json("prompt_patches/patch_index.json") or []
        patch_by_id = {patch.get("patch_id"): patch for patch in patches}
        found_profiles: set[str] = set()
        for path in sorted((ROOT / "runtime_profiles").glob("*.json")):
            data = self.load_json(path.relative_to(ROOT).as_posix())
            if data is None:
                continue
            profile_id = data.get("profile_id", path.stem)
            found_profiles.add(profile_id)
            self.validate_schema(data, "runtime_profile.schema.json", f"runtime profile {profile_id}")
            if path.stem != profile_id:
                self.fail(f"runtime profile 文件名与 profile_id 不一致：{path.name} / {profile_id}")
            for patch_id in data.get("verified_patches", []):
                patch = patch_by_id.get(patch_id)
                if not patch:
                    self.fail(f"runtime profile {profile_id} 引用了未知 patch：{patch_id}")
                elif patch.get("status") not in {"verified_candidate", "stable"}:
                    self.fail(f"runtime profile {profile_id} 错误导入未验证 patch：{patch_id}")
            for evidence in data.get("validation", {}).get("evidence", []):
                if not (ROOT / evidence).is_file():
                    self.fail(f"runtime profile {profile_id} 的证据不存在：{evidence}")
            if data.get("competition_verified") and data.get("validation_level") != "competition_verified":
                self.fail(f"runtime profile {profile_id} 的 competition_verified 与 validation_level 冲突")
        missing = PROFILE_IDS - found_profiles
        if missing:
            self.fail(f"缺少 runtime 状态文件：{', '.join(sorted(missing))}")
        else:
            self.pass_("runtime 状态文件覆盖和交叉引用")

    def validate_patch_profile_consistency(self) -> None:
        """patch → profile 方向：verified_candidate/stable 的 patch 必须进入至少一个
        runtime profile 的 verified_patches，否则其 verified 状态是悬空的，
        正式导出包也不会包含它（exporter 的 AND 条件）。"""
        patches = self.load_json("prompt_patches/patch_index.json") or []
        approved_everywhere: set[str] = set()
        for path in sorted((ROOT / "runtime_profiles").glob("*.json")):
            data = self.load_json(path.relative_to(ROOT).as_posix())
            if data is None:
                continue
            approved_everywhere.update(data.get("verified_patches", []))
        dangling: list[str] = []
        for patch in patches:
            patch_id = patch.get("patch_id", "<unknown>")
            status = patch.get("status")
            if status in {"verified_candidate", "stable"} and patch_id not in approved_everywhere:
                dangling.append(patch_id)
        if dangling:
            for patch_id in dangling:
                self.fail(
                    f"{patch_id} 状态为 verified 但未进入任何 runtime profile 的 verified_patches；"
                    "正式导出包不会包含它，请将其加入对应 profile 或降级为 candidate"
                )
        else:
            self.pass_("verified patch 全部进入 runtime profile verified_patches")

    def validate_patch_promotion(self) -> None:
        """晋级规则强制校验：委托给 promotion_engine（promotion_policy.json 的唯一事实源）。"""
        matrix = self.load_json("tests/prompt_regression/patch_negative_control_matrix.json")
        patch_index = self.load_json("prompt_patches/patch_index.json") or []
        if matrix is None:
            return
        if not (ROOT / "policies" / "promotion_policy.json").is_file():
            self.fail("缺少 policies/promotion_policy.json")
            return
        policy = pe_load_json(ROOT / "policies" / "promotion_policy.json")

        matrix_by_id = {item.get("patch_id"): item for item in matrix.get("patches", [])}
        promotion_ok = True

        def normalize_prompt(text: str) -> str:
            return "\n".join(
                line.rstrip()
                for line in text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
            )

        def _verify_real_run(run_dir: Path, target_patch: str, role: str) -> bool:
            ok = True
            try:
                run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
                if not run_manifest.get("eligible_for_promotion"):
                    self.fail(f"{run_dir.name} eligible_for_promotion 为 false")
                    ok = False
                if run_manifest.get("evidence_validity") != "real_ai_run":
                    self.fail(f"{run_dir.name} evidence_validity 不是 real_ai_run")
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
                    # 检查该证据是否为 legacy grandfathered
                    neg_entry = matrix_by_id.get(target_patch, {}).get("negative", {})
                    legacy = False
                    evidence = neg_entry.get("evidence") if isinstance(neg_entry.get("evidence"), dict) else {}
                    if evidence.get("schema_generation") == "legacy_v1_grandfathered":
                        legacy = True
                    # 也检查该 run 的 run_manifest 中是否在 cutoff 之前
                    created_at = run_manifest.get("created_at", "")
                    if cutoff and created_at and created_at < cutoff:
                        legacy = True

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
                case_text = case_file.read_text(encoding="utf-8")
                actual_case_sha = hashlib.sha256(case_text.encode("utf-8")).hexdigest()
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
                ok = _verify_ai_run_metadata(run_dir, policy, target_patch, role) and ok

            except Exception as e:
                self.fail(f"读取 {run_dir} 证据时出错: {e}")
                ok = False
            return ok

        def _verify_ai_run_metadata(run_dir: Path, policy: dict[str, Any], target_patch: str, role: str) -> bool:
            """校验 ai_run_metadata.json：Schema、哈希一致性、合法性。"""
            ok = True
            meta_path = run_dir / "ai_run_metadata.json"
            reqs = policy.get("run_evidence_requirements", {}).get("ai_run_metadata_checks", {})

            # 检查是否为 legacy grandfathered
            neg_entry = matrix_by_id.get(target_patch, {}).get("negative", {})
            evidence = neg_entry.get("evidence") if isinstance(neg_entry.get("evidence"), dict) else {}
            legacy = evidence.get("schema_generation") == "legacy_v1_grandfathered"

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

            # 非空 provider/model
            if reqs.get("require_non_empty_provider") and not meta.get("provider"):
                self.fail(f"{run_dir.name} ai_run_metadata.provider 为空")
                ok = False
            if reqs.get("require_non_empty_model") and not meta.get("model"):
                self.fail(f"{run_dir.name} ai_run_metadata.model 为空")
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
                    if completed < started:
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
                if expected:
                    rp_path = run_dir / "runtime_pack.manifest.json"
                    if rp_path.is_file():
                        actual_sha = hashlib.sha256(rp_path.read_bytes()).hexdigest()
                        if actual_sha != expected:
                            self.fail(f"{run_dir.name} ai_run_metadata.runtime_pack_sha256 不匹配（期望 {expected}，实际 {actual_sha}）")
                            ok = False

            # problem_material_digest 匹配
            if reqs.get("require_problem_material_digest_match"):
                expected = meta.get("problem_material_digest", "")
                if expected:
                    pm_path = run_dir / "problem_manifest.json"
                    if pm_path.is_file():
                        try:
                            pm = json.loads(pm_path.read_text(encoding="utf-8"))
                            actual = pm.get("content_digest", "")
                            if actual and actual != expected:
                                self.fail(f"{run_dir.name} ai_run_metadata.problem_material_digest 不匹配（期望 {expected}，实际 {actual}）")
                                ok = False
                        except (OSError, json.JSONDecodeError):
                            pass

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

        for patch in patch_index:
            patch_id = patch.get("patch_id", "<unknown>")
            status = patch.get("status")
            if status not in {"verified_candidate", "stable"}:
                continue
            entry = matrix_by_id.get(patch_id)
            if entry is None:
                self.fail(f"{patch_id} 标记为 {status}，但负控矩阵中没有该 patch 的记录")
                promotion_ok = False
                continue

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
            if any(part in {".git", "export"} for part in path.parts):
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
