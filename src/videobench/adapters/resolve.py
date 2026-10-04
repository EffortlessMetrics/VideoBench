"""Read-only DaVinci Resolve state probe.

The probe intentionally does not perform benchmarked edits. It provides one independent
observation channel for project and timeline state after a candidate run. Resolve API
availability varies by version and edition; every missing call is recorded rather than
silently treated as an empty value.
"""

from __future__ import annotations

import importlib
import os
import platform
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ResolveUnavailable(RuntimeError):
    """Raised when the Resolve scripting module or application cannot be reached."""


def candidate_module_paths() -> list[Path]:
    paths: list[Path] = []
    configured = os.environ.get("RESOLVE_SCRIPT_API")
    if configured:
        root = Path(configured)
        paths.extend([root, root / "Modules"])

    system = platform.system()
    if system == "Windows":
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        paths.append(
            program_data
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Support"
            / "Developer"
            / "Scripting"
            / "Modules"
        )
    elif system == "Darwin":
        paths.append(
            Path(
                "/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
                "Developer/Scripting/Modules"
            )
        )
    else:
        paths.append(Path("/opt/resolve/Developer/Scripting/Modules"))
    return paths


def load_resolve_module() -> Any:
    try:
        return importlib.import_module("DaVinciResolveScript")
    except ImportError:
        pass

    for directory in candidate_module_paths():
        module_file = directory / "DaVinciResolveScript.py"
        if not module_file.is_file():
            continue
        sys.path.insert(0, str(directory))
        try:
            return importlib.import_module("DaVinciResolveScript")
        except ImportError:
            continue
    searched = ", ".join(str(path) for path in candidate_module_paths())
    raise ResolveUnavailable(
        "Could not import DaVinciResolveScript. Set RESOLVE_SCRIPT_API or install the "
        f"Resolve scripting modules. Searched: {searched}"
    )


def connect_resolve() -> Any:
    module = load_resolve_module()
    resolve = module.scriptapp("Resolve")
    if resolve is None:
        raise ResolveUnavailable(
            "DaVinci Resolve did not expose a scripting connection. Ensure Resolve is running "
            "and external scripting is permitted."
        )
    return resolve


def _safe_call(
    target: Any,
    method: str,
    *args: Any,
    unknowns: list[str],
    default: Any = None,
) -> Any:
    function: Callable[..., Any] | None = getattr(target, method, None)
    if function is None:
        unknowns.append(f"missing_method:{type(target).__name__}.{method}")
        return default
    try:
        return function(*args)
    except Exception as error:  # Resolve's embedded API raises implementation-specific errors.
        unknowns.append(f"call_failed:{method}:{type(error).__name__}:{error}")
        return default


def _item_snapshot(item: Any, unknowns: list[str]) -> dict[str, Any]:
    media_pool_item = _safe_call(item, "GetMediaPoolItem", unknowns=unknowns)
    clip_properties = (
        _safe_call(media_pool_item, "GetClipProperty", unknowns=unknowns, default={})
        if media_pool_item is not None
        else {}
    )
    return {
        "name": _safe_call(item, "GetName", unknowns=unknowns),
        "start": _safe_call(item, "GetStart", unknowns=unknowns),
        "end": _safe_call(item, "GetEnd", unknowns=unknowns),
        "duration": _safe_call(item, "GetDuration", unknowns=unknowns),
        "left_offset": _safe_call(item, "GetLeftOffset", unknowns=unknowns),
        "right_offset": _safe_call(item, "GetRightOffset", unknowns=unknowns),
        "enabled": _safe_call(item, "GetClipEnabled", unknowns=unknowns),
        "properties": _safe_call(item, "GetProperty", unknowns=unknowns, default={}),
        "clip_properties": clip_properties or {},
    }


def _timeline_snapshot(timeline: Any, unknowns: list[str]) -> dict[str, Any]:
    tracks: dict[str, list[dict[str, Any]]] = {}
    for track_type in ("video", "audio", "subtitle"):
        count = _safe_call(timeline, "GetTrackCount", track_type, unknowns=unknowns, default=0)
        track_rows: list[dict[str, Any]] = []
        for index in range(1, int(count or 0) + 1):
            items = _safe_call(
                timeline,
                "GetItemListInTrack",
                track_type,
                index,
                unknowns=unknowns,
                default=[],
            )
            track_rows.append(
                {
                    "index": index,
                    "name": _safe_call(
                        timeline, "GetTrackName", track_type, index, unknowns=unknowns
                    ),
                    "enabled": _safe_call(
                        timeline,
                        "GetIsTrackEnabled",
                        track_type,
                        index,
                        unknowns=unknowns,
                    ),
                    "locked": _safe_call(
                        timeline,
                        "GetIsTrackLocked",
                        track_type,
                        index,
                        unknowns=unknowns,
                    ),
                    "items": [_item_snapshot(item, unknowns) for item in (items or [])],
                }
            )
        tracks[track_type] = track_rows

    return {
        "name": _safe_call(timeline, "GetName", unknowns=unknowns),
        "start_frame": _safe_call(timeline, "GetStartFrame", unknowns=unknowns),
        "end_frame": _safe_call(timeline, "GetEndFrame", unknowns=unknowns),
        "start_timecode": _safe_call(timeline, "GetStartTimecode", unknowns=unknowns),
        "current_timecode": _safe_call(timeline, "GetCurrentTimecode", unknowns=unknowns),
        "settings": _safe_call(timeline, "GetSetting", unknowns=unknowns, default={}) or {},
        "tracks": tracks,
    }


def capture_resolve_snapshot() -> dict[str, Any]:
    resolve = connect_resolve()
    unknowns: list[str] = []
    project_manager = _safe_call(resolve, "GetProjectManager", unknowns=unknowns)
    if project_manager is None:
        raise ResolveUnavailable("Resolve returned no project manager")
    project = _safe_call(project_manager, "GetCurrentProject", unknowns=unknowns)
    if project is None:
        raise ResolveUnavailable("Resolve has no current project")

    timeline_count = _safe_call(project, "GetTimelineCount", unknowns=unknowns, default=0)
    timelines: list[dict[str, Any]] = []
    for index in range(1, int(timeline_count or 0) + 1):
        timeline = _safe_call(project, "GetTimelineByIndex", index, unknowns=unknowns)
        if timeline is not None:
            timelines.append(_timeline_snapshot(timeline, unknowns))

    current = _safe_call(project, "GetCurrentTimeline", unknowns=unknowns)
    return {
        "resolve": {
            "version": _safe_call(resolve, "GetVersionString", unknowns=unknowns),
            "product_name": _safe_call(resolve, "GetProductName", unknowns=unknowns),
            "page": _safe_call(resolve, "GetCurrentPage", unknowns=unknowns),
        },
        "project": {
            "name": _safe_call(project, "GetName", unknowns=unknowns),
            "settings": _safe_call(project, "GetSetting", unknowns=unknowns, default={}) or {},
            "timeline_count": timeline_count,
            "current_timeline": (
                _safe_call(current, "GetName", unknowns=unknowns) if current is not None else None
            ),
            "timelines": timelines,
        },
        "unknowns": sorted(set(unknowns)),
    }
