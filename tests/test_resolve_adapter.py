from __future__ import annotations

from typing import Any

import pytest

from videobench.adapters import resolve as adapter


class FakeMediaPoolItem:
    def GetClipProperty(self) -> dict[str, str]:
        return {"File Path": "/media/a.mov"}


class FakeItem:
    def GetName(self) -> str:
        return "A001"

    def GetStart(self) -> int:
        return 100

    def GetEnd(self) -> int:
        return 200

    def GetDuration(self) -> int:
        return 100

    def GetLeftOffset(self) -> int:
        return 0

    def GetRightOffset(self) -> int:
        return 0

    def GetClipEnabled(self) -> bool:
        return True

    def GetProperty(self) -> dict[str, Any]:
        return {"Opacity": 100}

    def GetMediaPoolItem(self) -> FakeMediaPoolItem:
        return FakeMediaPoolItem()


class FakeTimeline:
    def GetName(self) -> str:
        return "Main"

    def GetStartFrame(self) -> int:
        return 0

    def GetEndFrame(self) -> int:
        return 240

    def GetStartTimecode(self) -> str:
        return "01:00:00:00"

    def GetCurrentTimecode(self) -> str:
        return "01:00:05:00"

    def GetSetting(self) -> dict[str, str]:
        return {"timelineFrameRate": "24"}

    def GetTrackCount(self, track_type: str) -> int:
        return 1 if track_type in {"video", "audio"} else 0

    def GetItemListInTrack(self, track_type: str, index: int) -> list[FakeItem]:
        return [FakeItem()] if track_type == "video" else []

    def GetTrackName(self, track_type: str, index: int) -> str:
        return f"{track_type}-{index}"

    def GetIsTrackEnabled(self, track_type: str, index: int) -> bool:
        return True

    def GetIsTrackLocked(self, track_type: str, index: int) -> bool:
        return False


class FakeProject:
    def __init__(self) -> None:
        self.timeline = FakeTimeline()

    def GetName(self) -> str:
        return "Demo"

    def GetSetting(self) -> dict[str, str]:
        return {"timelineResolutionWidth": "1920"}

    def GetTimelineCount(self) -> int:
        return 1

    def GetTimelineByIndex(self, index: int) -> FakeTimeline:
        return self.timeline

    def GetCurrentTimeline(self) -> FakeTimeline:
        return self.timeline


class FakeProjectManager:
    def GetCurrentProject(self) -> FakeProject:
        return FakeProject()


class FakeResolve:
    def GetProjectManager(self) -> FakeProjectManager:
        return FakeProjectManager()

    def GetVersionString(self) -> str:
        return "21.1"

    def GetProductName(self) -> str:
        return "DaVinci Resolve Studio"

    def GetCurrentPage(self) -> str:
        return "edit"


def test_capture_resolve_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "connect_resolve", lambda: FakeResolve())
    snapshot = adapter.capture_resolve_snapshot()
    assert snapshot["resolve"]["version"] == "21.1"
    assert snapshot["project"]["name"] == "Demo"
    timeline = snapshot["project"]["timelines"][0]
    assert timeline["tracks"]["video"][0]["items"][0]["name"] == "A001"
    assert snapshot["unknowns"] == []


def test_safe_call_records_missing_method() -> None:
    unknowns: list[str] = []
    assert adapter._safe_call(object(), "Missing", unknowns=unknowns) is None
    assert unknowns and unknowns[0].startswith("missing_method")


def test_connect_rejects_missing_application(monkeypatch: pytest.MonkeyPatch) -> None:
    class Module:
        @staticmethod
        def scriptapp(name: str) -> None:
            return None

    monkeypatch.setattr(adapter, "load_resolve_module", lambda: Module())
    with pytest.raises(adapter.ResolveUnavailable, match="did not expose"):
        adapter.connect_resolve()


def test_candidate_module_paths_honors_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESOLVE_SCRIPT_API", "/custom/resolve")
    paths = adapter.candidate_module_paths()
    assert paths[0].as_posix() == "/custom/resolve"
    assert paths[1].as_posix() == "/custom/resolve/Modules"


def test_capture_rejects_missing_project_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoManager:
        def GetProjectManager(self) -> None:
            return None

    monkeypatch.setattr(adapter, "connect_resolve", lambda: NoManager())
    with pytest.raises(adapter.ResolveUnavailable, match="project manager"):
        adapter.capture_resolve_snapshot()
