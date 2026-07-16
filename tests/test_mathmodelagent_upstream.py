from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from upstream import sync_mathmodelagent as sync


def _load_committed_metadata() -> tuple[dict[str, object], dict[str, object], bytes]:
    lock = json.loads((ROOT / "UPSTREAM.lock.json").read_text(encoding="utf-8"))
    manifest_bytes = (ROOT / "upstream" / "mathmodelagent.sha256.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    return lock, manifest, manifest_bytes


def test_committed_lock_and_manifest_match_all_pins() -> None:
    lock, manifest, manifest_bytes = _load_committed_metadata()

    sync.validate_repository_metadata(lock, manifest, manifest_bytes)

    files = manifest["files"]
    assert isinstance(files, list)
    assert len(files) == 389
    assert not any(
        str(entry["path"]).startswith("skills/1start-mathmodel/") for entry in files
    )


def test_vendor_source_asset_is_not_tracked() -> None:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", ".vendor/mathmodelagent"],
        stdout=subprocess.PIPE,
        check=True,
        text=True,
    )

    assert completed.stdout == ""


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("url", "https://example.invalid/MathModelAgent.git"),
        ("commit", "0" * 40),
        ("license_sha256", "0" * 64),
    ],
)
def test_repository_pin_drift_fails(field: str, bad_value: str) -> None:
    lock, manifest, manifest_bytes = _load_committed_metadata()
    tampered = copy.deepcopy(lock)
    repository = tampered["repository"]
    assert isinstance(repository, dict)
    repository[field] = bad_value

    with pytest.raises(sync.UpstreamIntegrityError):
        sync.validate_repository_metadata(tampered, manifest, manifest_bytes)


def test_allowlist_drift_fails() -> None:
    lock, manifest, manifest_bytes = _load_committed_metadata()
    tampered = copy.deepcopy(lock)
    allowed_paths = tampered["allowed_paths"]
    assert isinstance(allowed_paths, list)
    allowed_paths.append(
        {
            "path": "skills/1start-mathmodel",
            "object_type": "tree",
            "git_object": "0" * 40,
        }
    )

    with pytest.raises(sync.UpstreamIntegrityError):
        sync.validate_repository_metadata(tampered, manifest, manifest_bytes)


def test_manifest_tampering_fails_before_materialization() -> None:
    lock, manifest, manifest_bytes = _load_committed_metadata()
    tampered = copy.deepcopy(manifest)
    files = tampered["files"]
    assert isinstance(files, list)
    first = files[0]
    assert isinstance(first, dict)
    first["sha256"] = "0" * 64
    tampered_bytes = (json.dumps(tampered, ensure_ascii=False, indent=2) + "\n").encode()

    with pytest.raises(sync.UpstreamIntegrityError):
        sync.validate_repository_metadata(lock, tampered, tampered_bytes)


def test_fetch_uses_only_fixed_remote_and_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[list[str]] = []

    def fake_run_git(_repository: Path, args: list[str]) -> bytes:
        observed.append(args)
        if args == ["remote", "get-url", "origin"]:
            return f"{sync.PINNED_REPOSITORY}\n".encode()
        if args == ["rev-parse", "FETCH_HEAD"]:
            return f"{sync.PINNED_COMMIT}\n".encode()
        if args == ["cat-file", "-t", sync.PINNED_COMMIT]:
            return b"commit\n"
        return b""

    monkeypatch.setattr(sync, "_run_git", fake_run_git)
    sync._fetch_pinned_repository(tmp_path)

    assert ["remote", "add", "origin", sync.PINNED_REPOSITORY] in observed
    assert ["fetch", "--depth=1", "origin", sync.PINNED_COMMIT] in observed
    assert not any("checkout" in command for command in observed)


def test_vendor_verification_rejects_changed_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vendor = tmp_path / ".vendor" / "mathmodelagent"
    license_path = vendor / "docs" / "md" / "License.md"
    license_path.parent.mkdir(parents=True)
    original = b"fixed upstream bytes"
    license_path.write_bytes(original)
    provenance = {
        "schema_version": "mathmodelagent_source_asset_v1",
        "repository_url": sync.PINNED_REPOSITORY,
        "commit": sync.PINNED_COMMIT,
        "manifest_sha256": sync.PINNED_MANIFEST_SHA256,
        "upstream_content_executed": False,
    }
    (vendor / "SOURCE.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "files": [
            {
                "path": "docs/md/License.md",
                "size": len(original),
                "sha256": hashlib.sha256(original).hexdigest(),
            }
        ]
    }
    monkeypatch.setattr(sync, "VENDOR_PATH", vendor)
    sync.verify_vendor(manifest)

    license_path.write_bytes(b"changed")
    with pytest.raises(sync.UpstreamIntegrityError, match="文件哈希不匹配"):
        sync.verify_vendor(manifest)


def test_recursive_operations_reject_workspace_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"

    with pytest.raises(sync.UpstreamIntegrityError, match="工作区外"):
        sync._safe_managed_path(outside)
