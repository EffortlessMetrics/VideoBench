#!/usr/bin/env python3
"""Instrument-validation candidate used by the documented command-run example.

This is not an editing agent. It copies the frozen known-good artifact set and writes a
synthetic usage receipt so the command adapter can be exercised without Resolve.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def main() -> None:
    example_root = Path(__file__).resolve().parents[1]
    source = example_root / "candidates" / "good"
    output = Path(os.environ["VIDEOBENCH_OUTPUT_DIR"])
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError(f"VideoBench output directory is not empty: {output}")

    for item in source.iterdir():
        destination = output / item.name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)

    usage_path_value = os.environ.get("VIDEOBENCH_USAGE_PATH")
    if usage_path_value:
        usage_path = Path(usage_path_value)
        usage_path.parent.mkdir(parents=True, exist_ok=True)
        usage_path.write_text(
            json.dumps(
                {
                    "input_tokens": 1000,
                    "reasoning_tokens": 300,
                    "output_tokens": 500,
                    "model_calls": 1,
                    "tool_calls": 4,
                    "actual_candidate_cost_usd": 0.01,
                    "metadata": {
                        "fixture": "known-good command-adapter proof",
                        "attempt_id": os.environ["VIDEOBENCH_ATTEMPT_ID"],
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
