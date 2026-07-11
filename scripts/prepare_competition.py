"""以人工确认分类和内容哈希为边界准备比赛材料。"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from atomic_io import atomic_write_bytes
from run_workflow import ROOT, create_new_problem_run
from verify_materials import verify_materials


PLAN_VERSION = "1.0.0"
PLAN_SCHEMA_PATH = ROOT / "schemas" / "competition_material_plan.schema.json"
CATEGORIES = frozenset({"problem", "attachments", "templates", "unknown"})
TOOL_FILENAMES = frozenset(
    {
        "material_manifest.json",
        "classification.json",
        "material_plan.json",
        ".prepare_competition_plan.json",
    }
)
IGNORED_DIRECTORY_NAMES = frozenset({".git", "__pycache__", "runs", ".transactions"})
GATE_0_PROMPT = (
    "仅执行 Gate 0：读取已冻结题面和材料，输出题型判断、候选路线、风险与人工确认项；"
    "不得进入 Gate 1 或生成最终答案。"
)


def _sha(content: bytes) -> str:
    """计算文件及计划身份所使用的 SHA-256。"""
    return hashlib.sha256(content).hexdigest()


def _canonical_bytes(data: Mapping[str, Any]) -> bytes:
    """生成稳定的扫描事实字节；人工确认分类不改变 plan 身份。"""
    payload = {key: value for key, value in data.items() if key != "plan_digest"}
    files = payload.get("files")
    if isinstance(files, list):
        payload["files"] = [
            {**item, "confirmed_category": None} if isinstance(item, Mapping) else item
            for item in files
        ]
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _plan_digest(data: Mapping[str, Any]) -> str:
    """现场重算计划摘要，拒绝人工修改后的过期计划。"""
    return _sha(_canonical_bytes(data))


def _relative_if_contained(path: Path, root: Path) -> str | None:
    """返回位于材料根目录内的相对路径，目录外文件不参与扫描排除。"""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _is_excluded(relative_path: Path, explicit_exclusions: set[str]) -> bool:
    """排除工具文件、内部目录和本次 plan 输出，避免清单自引用。"""
    normalized = relative_path.as_posix()
    if normalized in explicit_exclusions or relative_path.name in TOOL_FILENAMES:
        return True
    return any(part in IGNORED_DIRECTORY_NAMES or part.startswith(".") for part in relative_path.parts)


def _suggest_category(path: Path) -> str:
    """只给出可人工覆盖的分类建议，最终分类不能由文件名自动决定。"""
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix == ".pdf" and ("题" in name or "problem" in name):
        return "problem"
    if "template" in name or "模板" in name:
        return "templates"
    if suffix in {".xlsx", ".xls", ".csv", ".png", ".jpg", ".jpeg", ".docx", ".zip"}:
        return "attachments"
    return "unknown"


def _files(materials: Path, *, explicit_exclusions: Iterable[str] = ()) -> tuple[list[dict[str, Any]], list[str]]:
    """扫描材料并同步记录已排除路径，供人工审计。"""
    exclusions = set(explicit_exclusions)
    entries: list[dict[str, Any]] = []
    excluded_paths: list[str] = []
    for path in sorted(materials.rglob("*")):
        relative = path.relative_to(materials)
        if _is_excluded(relative, exclusions):
            excluded_paths.append(relative.as_posix())
            continue
        if path.is_symlink():
            raise ValueError(f"材料目录不允许符号链接：{relative.as_posix()}")
        if not path.is_file():
            continue
        content = path.read_bytes()
        entries.append(
            {
                "path": relative.as_posix(),
                "size_bytes": len(content),
                "sha256": _sha(content),
                "suggested_category": _suggest_category(path),
                "confirmed_category": None,
            }
        )
    return entries, sorted(set(excluded_paths))


def _schema_errors(data: Mapping[str, Any]) -> list[str]:
    """以唯一 Schema 验证计划结构，避免 CLI 与 Schema 规则漂移。"""
    schema = json.loads(PLAN_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}：{error.message}"
        for error in errors
    ]


def _read_plan(path: Path) -> dict[str, Any]:
    """读取并完整验证可编辑计划及其自校验摘要。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("比赛材料 plan 根节点必须为对象")
    errors = _schema_errors(value)
    if errors:
        raise ValueError("比赛材料 plan 格式无效：" + "；".join(errors))
    if value.get("plan_digest") != _plan_digest(value):
        raise ValueError("比赛材料 plan_digest 与内容不一致，必须重新 plan")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    """统一以 UTF-8 原子写入机器可读文件。"""
    atomic_write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def plan(problem: str, materials: Path, output: Path) -> dict[str, Any]:
    """扫描材料并生成待人工确认的、可漂移检测的计划。"""
    materials = materials.resolve()
    if not materials.is_dir():
        raise ValueError("材料目录不存在")
    output_relative = _relative_if_contained(output, materials)
    files, excluded_paths = _files(
        materials,
        explicit_exclusions=(() if output_relative is None else (output_relative,)),
    )
    if not files:
        raise ValueError("材料目录为空或只包含工具生成文件")
    result: dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "problem_id": problem,
        "material_root": materials.as_posix(),
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "excluded_paths": excluded_paths,
        "files": files,
    }
    result["plan_digest"] = _plan_digest(result)
    errors = _schema_errors(result)
    if errors:  # pragma: no cover - 防止实现与受版本控制 Schema 脱节
        raise ValueError("生成的比赛材料 plan 不符合 Schema：" + "；".join(errors))
    _write_json(output, result)
    return result


def _validated_categories(
    data: Mapping[str, Any], materials: Path, plan_path: Path
) -> dict[str, list[dict[str, str]]]:
    """重扫材料、检查漂移和人工分类，并构造材料清单分类。"""
    planned_files = data["files"]
    assert isinstance(planned_files, list)
    planned: dict[str, Mapping[str, Any]] = {}
    for item in planned_files:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise ValueError("比赛材料 plan 文件条目非法")
        path = str(item["path"])
        if path in planned:
            raise ValueError(f"比赛材料 plan 存在重复文件：{path}")
        planned[path] = item

    plan_relative = _relative_if_contained(plan_path, materials)
    current_files, _excluded = _files(
        materials,
        explicit_exclusions=(() if plan_relative is None else (plan_relative,)),
    )
    current = {item["path"]: item for item in current_files}
    if set(planned) != set(current):
        raise ValueError("材料发生新增、删除或重命名，必须重新 plan")

    categories: dict[str, list[dict[str, str]]] = {
        "problem": [],
        "attachments": [],
        "templates": [],
    }
    for path, item in planned.items():
        now = current[path]
        if item.get("size_bytes") != now["size_bytes"] or item.get("sha256") != now["sha256"]:
            raise ValueError(f"材料内容漂移：{path}")
        category = item.get("confirmed_category")
        if category not in CATEGORIES or category == "unknown":
            raise ValueError(f"材料未完成合法人工分类：{path}")
        assert isinstance(category, str)
        categories[category].append({"path": path, "sha256": str(now["sha256"])})
    if not categories["problem"]:
        raise ValueError("至少需要一个 problem 类题面")
    return categories


def _build_material_manifest(
    data: Mapping[str, Any], reviewer: str, categories: Mapping[str, list[dict[str, str]]]
) -> dict[str, Any]:
    """从已验证计划现场派生最终材料清单，不信任额外手填摘要。"""
    return {
        "manifest_version": "1.0.0",
        "problem_id": data["problem_id"],
        "material_root": ".",
        "source": {
            "kind": "user_provided",
            "reference": f"competition plan {data['plan_digest']} reviewed by {reviewer}",
        },
        "contains_answer_or_solution": False,
        "categories": {
            category: {"required": category == "problem", "files": files}
            for category, files in categories.items()
        },
    }


def _cleanup_staging(path: Path) -> None:
    """只清理本次创建的随机临时目录，避免影响其他 Run。"""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    parent = path.parent
    if parent.name == ".tmp":
        try:
            parent.rmdir()
        except OSError:
            pass


def apply(
    plan_path: Path,
    materials: Path,
    *,
    profile: str,
    mode: str,
    reviewer: str,
    confirm_no_solution: bool,
    output_root: str,
) -> dict[str, str]:
    """在材料未漂移且人工确认后，原子发布一个可进入 Gate 0 的比赛 Run。"""
    if not confirm_no_solution:
        raise ValueError("正式比赛 apply 必须显式提供 --confirm-no-solution")
    if not reviewer.strip():
        raise ValueError("--reviewer 不能为空")

    materials = materials.resolve()
    plan_path = plan_path.resolve()
    data = _read_plan(plan_path)
    if data["material_root"] != materials.as_posix():
        raise ValueError("plan.material_root 与 --materials 不一致")
    categories = _validated_categories(data, materials, plan_path)

    manifest_path = materials / "material_manifest.json"
    if manifest_path.exists():
        raise ValueError("material_manifest.json 已存在；当前 apply 不允许覆盖既有材料清单")
    material_manifest = _build_material_manifest(data, reviewer, categories)
    manifest_created = False
    output_path = Path(output_root).resolve()
    staging_root = output_path / ".tmp" / f"prepare-{secrets.token_hex(8)}"
    try:
        _write_json(manifest_path, material_manifest)
        manifest_created = True
        verification = verify_materials(materials, expected_problem_id=str(data["problem_id"]))
        if not verification.ready:
            raise ValueError("material_manifest 复核失败")

        staging_root.mkdir(parents=True, exist_ok=False)
        args = argparse.Namespace(
            run_id=None,
            output_root=str(staging_root),
            problem=data["problem_id"],
            profile=profile,
            gates="0-5",
            materials=str(materials),
            candidate_patch=[],
            exclude_patch=[],
            material_file=[],
            promotion_evidence=False,
            experiment_group_id=None,
            experiment_role=None,
            target_patch=None,
            workflow="new_problem",
            mode=mode,
        )
        staged_run, ready = create_new_problem_run(args)
        if not ready:
            raise ValueError("初始化的比赛 Run 未就绪")
        final_run = output_path / staged_run.name
        if final_run.exists():
            raise FileExistsError(f"运行目录已存在：{final_run}")
        staged_run.replace(final_run)
        _cleanup_staging(staging_root)

        runtime_manifest = json.loads(
            (final_run / "runtime_pack.manifest.json").read_text(encoding="utf-8")
        )
        return {
            "run_dir": str(final_run),
            "runtime_pack": str(final_run / "runtime_pack.md"),
            "runtime_pack_sha256": str(runtime_manifest["runtime_pack_sha256"]),
            "workflow_context": str(runtime_manifest["workflow_context"]),
            "profile": profile,
            "mode": mode,
            "gate_0_prompt": GATE_0_PROMPT,
        }
    except Exception:
        _cleanup_staging(staging_root)
        if manifest_created:
            manifest_path.unlink(missing_ok=True)
        raise


def main() -> None:
    """提供比赛材料 plan/apply 命令行入口。"""
    parser = argparse.ArgumentParser(description="比赛材料 plan/apply")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--problem", required=True)
    p.add_argument("--materials", required=True)
    p.add_argument("--output", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--plan", required=True)
    a.add_argument("--materials", required=True)
    a.add_argument("--profile", default="general")
    a.add_argument("--mode", default="standard", choices=["strict", "standard", "emergency"])
    a.add_argument("--reviewer", required=True)
    a.add_argument("--confirm-no-solution", action="store_true")
    a.add_argument("--output-root", default="runs")
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = plan(args.problem, Path(args.materials), Path(args.output))
        else:
            result = apply(
                Path(args.plan),
                Path(args.materials),
                profile=args.profile,
                mode=args.mode,
                reviewer=args.reviewer,
                confirm_no_solution=args.confirm_no_solution,
                output_root=args.output_root,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
