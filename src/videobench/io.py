"""Artifact and configuration I/O."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

from videobench.canonical import seal_payload, verify_envelope
from videobench.types import ArtifactEnvelope

T = TypeVar("T", bound=BaseModel)


def load_data(path: Path) -> dict[str, Any]:
    """Load a JSON or YAML mapping."""

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        value = yaml.safe_load(text)
    elif suffix == ".json":
        value = json.loads(text)
    else:
        raise ValueError(f"Unsupported data file extension: {path.suffix}")
    if not isinstance(value, dict):
        raise ValueError(f"Expected a mapping in {path}")
    return value


def load_model(path: Path, model_type: type[T]) -> T:
    return model_type.model_validate(load_data(path))


def write_json(path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, BaseModel):
        payload: Any = value.model_dump(mode="json", exclude_none=False)
    else:
        payload = value
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_envelope(
    path: Path,
    kind: str,
    payload: BaseModel | dict[str, Any],
    producer: str = "videobench",
) -> ArtifactEnvelope:
    envelope = seal_payload(kind, payload, producer=producer)
    write_json(path, envelope)
    return envelope


def load_envelope(path: Path, *, expected_kind: str | None = None) -> ArtifactEnvelope:
    envelope = ArtifactEnvelope.model_validate(load_data(path))
    verify_envelope(envelope)
    if expected_kind is not None and envelope.kind != expected_kind:
        raise ValueError(f"Expected artifact kind {expected_kind!r}, got {envelope.kind!r}")
    return envelope


def payload_as(path: Path, model_type: type[T], *, expected_kind: str | None = None) -> T:
    envelope = load_envelope(path, expected_kind=expected_kind)
    return model_type.model_validate(envelope.payload)
