"""Media probing through ffprobe when available."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def ffprobe(path: Path, *, executable: str = "ffprobe") -> dict[str, Any]:
    resolved = shutil.which(executable)
    if resolved is None:
        raise RuntimeError(
            "ffprobe is not available. Install FFmpeg or pass the path to an ffprobe executable."
        )
    completed = subprocess.run(
        [
            resolved,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-print_format",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {completed.stderr.strip()}")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("ffprobe returned a non-object JSON payload")
    return value
