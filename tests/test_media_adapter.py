from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from videobench.adapters import media


def test_ffprobe_requires_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="not available"):
        media.ffprobe(tmp_path / "x.mp4")


def test_ffprobe_parses_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        media.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout='{"format":{"duration":"1.0"}}', stderr=""
        ),
    )
    assert media.ffprobe(tmp_path / "x.mp4")["format"]["duration"] == "1.0"


def test_ffprobe_reports_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        media.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="bad file"),
    )
    with pytest.raises(RuntimeError, match="bad file"):
        media.ffprobe(tmp_path / "x.mp4")


def test_ffprobe_rejects_non_object_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        media.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="[]", stderr=""),
    )
    with pytest.raises(RuntimeError, match="non-object"):
        media.ffprobe(tmp_path / "x.mp4")
