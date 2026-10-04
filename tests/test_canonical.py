from __future__ import annotations

import json
from pathlib import Path

import pytest

from videobench.canonical import (
    canonical_json_bytes,
    path_sha256,
    resolve_under_root,
    seal_payload,
    sha256_hex,
    verify_envelope,
)
from videobench.contracts import RunCondition


def test_canonical_digest_ignores_mapping_order() -> None:
    assert sha256_hex({"b": 2, "a": 1}) == sha256_hex({"a": 1, "b": 2})


def test_envelope_detects_payload_mutation() -> None:
    envelope = seal_payload("run_condition", RunCondition(attempt_id="a", clean_state_id="s"))
    envelope.payload["attempt_id"] = "tampered"
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_envelope(envelope)


def test_canonical_json_is_compact_and_stable(tmp_path: Path) -> None:
    value = {"z": [3, 2, 1], "a": {"ok": True}}
    first = canonical_json_bytes(value)
    second = canonical_json_bytes(json.loads(first))
    assert first == second
    assert first == b'{"a":{"ok":true},"z":[3,2,1]}'


def test_directory_digest_is_order_independent_and_path_sensitive(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")
    first = path_sha256(root)
    (root / "a.txt").rename(root / "c.txt")
    assert path_sha256(root) != first


def test_resolve_under_root_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="parent segments"):
        resolve_under_root(tmp_path, "../outside")


def test_path_digest_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are not available in this environment")
    with pytest.raises(ValueError, match="Symbolic links"):
        path_sha256(link)
    with pytest.raises(ValueError, match="symbolic links"):
        resolve_under_root(tmp_path, "link.txt")


def test_relative_evidence_paths_are_cross_platform_safe(tmp_path: Path) -> None:
    for value in (r"..\outside", r"C:\outside", "C:outside", "/outside", "a//b"):
        with pytest.raises(ValueError):
            resolve_under_root(tmp_path, value)

    resolved = resolve_under_root(tmp_path, "nested/evidence.json")
    assert resolved == tmp_path / "nested" / "evidence.json"
