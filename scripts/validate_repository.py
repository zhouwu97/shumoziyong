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
