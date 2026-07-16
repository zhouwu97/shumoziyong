from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from template_registry import (  # noqa: E402
    DEFAULT_MANIFEST_PATH,
    DEFAULT_OVERLAY_PATH,
    DEFAULT_VENDOR_ROOT,
    TemplateRegistryError,
    generate_manifest,
    materialize_template,
    select_template,
    sha256_file,
    validate_registry,
)


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_committed_registry_is_deterministic_and_source_verified() -> None:
    if not DEFAULT_VENDOR_ROOT.is_dir():
        pytest.skip("本地只读 Source Asset 未同步")
    committed = _load(DEFAULT_MANIFEST_PATH)
    generated = generate_manifest(DEFAULT_VENDOR_ROOT)
    assert generated == committed
    validate_registry(committed, verify_source=True)


def test_registry_has_17_unique_keys_and_34_closed_template_trees() -> None:
    manifest = _load(DEFAULT_MANIFEST_PATH)
    logical_keys = manifest["logical_keys"]
    templates = manifest["templates"]
    assert isinstance(logical_keys, list)
    assert isinstance(templates, list)
    assert len(logical_keys) == 17
    assert len(templates) == 34
    assert len({item["key"] for item in logical_keys}) == 17
    assert len({item["template_id"] for item in templates}) == 34
    assert {item["engine"] for item in templates} == {"typst", "xelatex"}
    assert all(item["default_engine"] == "typst" for item in logical_keys)
    assert all(item["fallback_engine"] == "xelatex" for item in logical_keys)
    assert all(item["upstream_default_overridden"] is True for item in logical_keys)
    assert all(".vendor" not in item["source_dir"] for item in templates)


def test_registry_and_windows_overlay_match_schemas() -> None:
    registry_schema = _load(ROOT / "schemas" / "template_source_manifest.schema.json")
    overlay_schema = _load(ROOT / "schemas" / "template_overlay.schema.json")
    registry = _load(DEFAULT_MANIFEST_PATH)
    overlay = _load(DEFAULT_OVERLAY_PATH)
    assert not list(Draft202012Validator(registry_schema).iter_errors(registry))
    assert not list(Draft202012Validator(overlay_schema).iter_errors(overlay))
    assert overlay["materialization"]["source_asset_read_only"] is True
    assert overlay["materialization"]["verify_before_copy"] is True
    assert overlay["engines"]["typst"]["passes"] == 1
    assert overlay["engines"]["xelatex"]["passes"] == 2


def test_selection_precedence_and_engine_policy() -> None:
    manifest = _load(DEFAULT_MANIFEST_PATH)
    runtime_wins = select_template(
        manifest,
        language="zh",
        competition_family="cumcm",
        runtime_profile_template="zh/stats",
        run_template="en/mcm",
    )
    assert runtime_wins["logical_key"] == "zh/stats"
    assert runtime_wins["selection_source"] == "runtime_profile"

    run_wins = select_template(
        manifest,
        language="zh",
        competition_family="cumcm",
        run_template="en/mcm",
    )
    assert run_wins["logical_key"] == "en/mcm"
    assert run_wins["selection_source"] == "current_run"

    competition_wins = select_template(
        manifest,
        language="zh",
        competition_family="cumcm",
    )
    assert competition_wins["logical_key"] == "zh/cumcm"
    assert competition_wins["engine"] == "typst"
    assert competition_wins["upstream_default_overridden"] is True

    upstream_fallback = select_template(
        manifest,
        language="en",
        competition_family="unknown",
        requested_engine="xelatex",
    )
    assert upstream_fallback["logical_key"] == "en/default"
    assert upstream_fallback["selection_source"] == "upstream_default"
    assert upstream_fallback["upstream_default_overridden"] is False


def test_unknown_explicit_template_fails_closed() -> None:
    manifest = _load(DEFAULT_MANIFEST_PATH)
    with pytest.raises(TemplateRegistryError, match="未知模板逻辑键"):
        select_template(
            manifest,
            language="zh",
            competition_family="cumcm",
            run_template="zh/not-registered",
        )


def test_materialization_is_verified_copy_and_does_not_mutate_source(tmp_path: Path) -> None:
    if not DEFAULT_VENDOR_ROOT.is_dir():
        pytest.skip("本地只读 Source Asset 未同步")
    manifest = _load(DEFAULT_MANIFEST_PATH)
    selection = select_template(manifest, language="zh", competition_family="cumcm")
    template = next(
        item for item in manifest["templates"] if item["template_id"] == selection["template_id"]
    )
    source_dir = DEFAULT_VENDOR_ROOT / Path(template["source_dir"])
    before = {
        item["path"]: sha256_file(source_dir / Path(item["path"])) for item in template["files"]
    }

    target = tmp_path / "paper"
    materialize_template(manifest, selection, target_dir=target)

    after = {
        item["path"]: sha256_file(source_dir / Path(item["path"])) for item in template["files"]
    }
    copied = {
        item["path"]: sha256_file(target / Path(item["path"])) for item in template["files"]
    }
    assert before == after == copied


def test_windows_xelatex_overlay_changes_only_staged_copy(tmp_path: Path) -> None:
    if not DEFAULT_VENDOR_ROOT.is_dir():
        pytest.skip("本地只读 Source Asset 未同步")
    manifest = _load(DEFAULT_MANIFEST_PATH)
    selection = select_template(
        manifest,
        language="zh",
        competition_family="cumcm",
        requested_engine="xelatex",
    )
    template = next(
        item for item in manifest["templates"] if item["template_id"] == selection["template_id"]
    )
    source_main = DEFAULT_VENDOR_ROOT / Path(template["source_dir"]) / "main.tex"
    before = source_main.read_bytes()

    target = tmp_path / "paper"
    applied = materialize_template(
        manifest,
        selection,
        target_dir=target,
        platform_name="windows",
    )

    staged = (target / "main.tex").read_text(encoding="utf-8")
    assert "ctex_fontset_portability" in applied
    assert "fontset=windows" in staged
    assert "fontset=mac" not in staged
    assert source_main.read_bytes() == before
