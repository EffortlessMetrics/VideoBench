"""Canonical serialization and content-addressed artifact helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import BaseModel

from videobench.types import ArtifactEnvelope


def to_primitive(value: Any) -> Any:
    """Convert supported values into deterministic JSON primitives."""

    if isinstance(value, BaseModel):
        return to_primitive(value.model_dump(mode="python", exclude_none=False))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_primitive(item) for item in value]
    if isinstance(value, set):
        return sorted(to_primitive(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported canonical value: {type(value)!r}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return UTF-8 canonical JSON bytes."""

    primitive = to_primitive(value)
    return json.dumps(
        primitive,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    """Return the SHA-256 digest of canonical JSON-compatible content."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def path_sha256(path: Path) -> str:
    """Hash a file or a directory tree without following symbolic links.

    Directory identities are semantic manifests over relative path, byte digest, and
    size. This supports portable project directories such as Resolve archives while
    keeping individual files independently auditable.
    """

    if path.is_symlink():
        raise ValueError(f"Symbolic links are not valid evidence paths: {path}")
    if path.is_file():
        return file_sha256(path)
    if not path.is_dir():
        raise ValueError(f"Evidence path is neither a file nor a directory: {path}")

    manifest: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"Symbolic links are not valid evidence paths: {item}")
        if not item.is_file():
            continue
        manifest.append(
            {
                "path": item.relative_to(path).as_posix(),
                "sha256": file_sha256(item),
                "size_bytes": item.stat().st_size,
            }
        )
    return sha256_hex(manifest)


def validate_relative_evidence_path(relative: str) -> PurePosixPath:
    """Validate a portable, root-contained evidence path.

    Protocol paths always use POSIX separators, even on Windows. Rejecting native
    backslashes and Windows drive-relative paths prevents a manifest authored on one
    operating system from changing meaning on another.
    """

    if not relative or "\x00" in relative:
        raise ValueError(f"Evidence paths must be non-empty text: {relative!r}")
    if "\\" in relative:
        raise ValueError(f"Evidence paths must use POSIX separators: {relative!r}")
    raw_parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(
            f"Evidence paths may not contain empty, current, or parent segments: {relative!r}"
        )
    candidate = PurePosixPath(relative)
    windows_candidate = PureWindowsPath(relative)
    if candidate.is_absolute() or windows_candidate.is_absolute() or windows_candidate.drive:
        raise ValueError(f"Evidence paths must be relative and drive-free: {relative!r}")
    return candidate


def resolve_under_root(root: Path, relative: str) -> Path:
    """Resolve a portable relative evidence path and reject root escape."""

    candidate = validate_relative_evidence_path(relative)
    if root.is_symlink():
        raise ValueError(f"Evidence roots may not be symbolic links: {root}")
    root_resolved = root.resolve()
    unresolved = root_resolved
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        unresolved = unresolved / part
        if unresolved.is_symlink():
            raise ValueError(f"Evidence paths may not traverse symbolic links: {relative}")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as error:
        raise ValueError(f"Evidence path escapes its declared root: {relative}") from error
    return resolved


def seal_payload(
    kind: str,
    payload: BaseModel | dict[str, Any],
    producer: str = "videobench",
) -> ArtifactEnvelope:
    """Wrap a payload in a content-addressed envelope."""

    payload_dict = to_primitive(payload)
    if not isinstance(payload_dict, dict):
        raise TypeError("Artifact payloads must serialize to a JSON object")
    digest = sha256_hex(payload_dict)
    return ArtifactEnvelope(
        kind=kind,
        artifact_id=f"{kind}:{digest[:16]}",
        producer=producer,
        payload_sha256=digest,
        payload=payload_dict,
    )


def verify_envelope(envelope: ArtifactEnvelope) -> None:
    """Raise ``ValueError`` if an envelope's payload digest is invalid."""

    actual = sha256_hex(envelope.payload)
    if actual != envelope.payload_sha256:
        raise ValueError(
            f"Artifact digest mismatch for {envelope.artifact_id}: "
            f"expected {envelope.payload_sha256}, got {actual}"
        )
