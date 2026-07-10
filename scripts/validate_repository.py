from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

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

    def validate_schema(self, data: Any, schema_name: str, label: str) -> None:
        schema = self.load_json(f"schemas/{schema_name}")
        if schema is None:
            return
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            for error in errors:
                location = ".".join(str(part) for part in error.absolute_path) or "<root>"
                self.fail(f"{label} Schema：{location}：{error.message}")
        else:
            self.pass_(f"{label} Schema")

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
        """晋级规则强制校验：
        verified_candidate / stable 必须满足 positive + boundary + negative 全 pass。
        candidate 不强制完整三类测试。"""
        matrix = self.load_json("tests/prompt_regression/patch_negative_control_matrix.json")
        patch_index = self.load_json("prompt_patches/patch_index.json") or []
        if matrix is None:
            return
        matrix_by_id = {item.get("patch_id"): item for item in matrix.get("patches", [])}
        promotion_ok = True

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
                
                # Check manifest active patches
                rt_manifest = json.loads((run_dir / "runtime_pack.manifest.json").read_text(encoding="utf-8"))
                active_patches = {p.get("patch_id") for p in rt_manifest.get("patches", [])}
                if role == "patch_only" and target_patch not in active_patches:
                    self.fail(f"{run_dir.name} 宣称是 patch_only 但未加载 {target_patch}")
                    ok = False
                if role == "baseline" and target_patch in active_patches:
                    self.fail(f"{run_dir.name} 宣称是 baseline 但加载了 {target_patch}")
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

                eval_json = json.loads((run_dir / "automatic_evaluation.json").read_text(encoding="utf-8"))
                if not eval_json.get("case_id"):
                    self.fail(f"{run_dir.name} automatic_evaluation.case_id 为空")
                    ok = False
                if eval_json.get("result") != "pass":
                    self.fail(f"{run_dir.name} automatic_evaluation.result 不是 pass")
                    ok = False

            except Exception as e:
                self.fail(f"读取 {run_dir} 证据时出错: {e}")
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
            for control in ("positive", "boundary", "negative"):
                control_data = entry.get(control, {})
                result = control_data.get("result")
                if result != "pass":
                    self.fail(f"{patch_id} 标记为 {status}，但 {control}-control 结果为 {result}（必须为 pass）")
                    promotion_ok = False
                    continue
                
                if control == "negative" and "evidence" in control_data:
                    evidence = control_data["evidence"]
                    if isinstance(evidence, dict):
                        b_run = ROOT / evidence.get("baseline_run", "")
                        t_run = ROOT / evidence.get("treatment_run", "")
                        c_rev = ROOT / evidence.get("comparison_review", "")
                        
                        if ".." in str(b_run) or ".." in str(t_run) or ".." in str(c_rev):
                            self.fail(f"{patch_id} 证据路径逃逸仓库")
                            promotion_ok = False
                            continue

                        if not _verify_real_run(b_run, patch_id, "baseline"): promotion_ok = False
                        if not _verify_real_run(t_run, patch_id, "patch_only"): promotion_ok = False
                        
                        try:
                            rev_data = json.loads(c_rev.read_text(encoding="utf-8"))
                            if rev_data.get("final_result") != "pass":
                                self.fail(f"{patch_id} comparison_review 结果不为 pass")
                                promotion_ok = False
                        except Exception as e:
                            self.fail(f"无法读取 comparison_review: {c_rev.name} ({e})")
                            promotion_ok = False

                        try:
                            b_resp = (b_run / "response.json").read_text(encoding="utf-8")
                            t_resp = (t_run / "response.json").read_text(encoding="utf-8")
                            import hashlib
                            if hashlib.sha256(b_resp.encode('utf-8')).hexdigest() == hashlib.sha256(t_resp.encode('utf-8')).hexdigest():
                                self.fail(f"{patch_id} baseline 和 treatment 的 response 完全相同")
                                promotion_ok = False
                        except Exception:
                            pass
                        
                        try:
                            t_man = json.loads((t_run / "run_manifest.json").read_text(encoding="utf-8"))
                            if t_man.get("target_patch") != patch_id:
                                self.fail(f"{patch_id} treatment 运行记录 target_patch 不匹配")
                                promotion_ok = False
                        except Exception:
                            pass
        if promotion_ok:
            self.pass_("patch 晋级规则（verified 需 positive+boundary+negative 全 pass）")

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
