#!/usr/bin/env python3
"""Run the repository's complete local verification chain."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from videobench.schemas import export_schemas  # noqa: E402


def run(*command: str) -> None:
    print("+", " ".join(command), flush=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SRC)
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def check_schema_drift() -> None:
    print("+ check JSON Schema drift", flush=True)
    with tempfile.TemporaryDirectory(prefix="videobench-schemas-") as temporary:
        generated_root = Path(temporary)
        export_schemas(generated_root)
        expected_root = ROOT / "contracts" / "schemas"
        expected = {path.name for path in expected_root.glob("*.json")}
        generated = {path.name for path in generated_root.glob("*.json")}
        if expected != generated:
            raise SystemExit(
                f"Schema file set drift: expected={sorted(expected)}, generated={sorted(generated)}"
            )
        changed = [
            name
            for name in sorted(expected)
            if (expected_root / name).read_bytes() != (generated_root / name).read_bytes()
        ]
        if changed:
            raise SystemExit(
                "Checked-in schemas are stale: "
                + ", ".join(changed)
                + ". Run `videobench export-schemas --out contracts/schemas`."
            )


def main() -> None:
    check_schema_drift()
    run(sys.executable, "-m", "ruff", "format", "--check", ".")
    run(sys.executable, "-m", "ruff", "check", ".")
    run(sys.executable, "-m", "mypy", "src/videobench")
    run(
        sys.executable,
        "-m",
        "pytest",
        "--cov=videobench",
        "--cov-branch",
        "--cov-report=term-missing",
        "-q",
    )
    with tempfile.TemporaryDirectory(prefix="videobench-demo-") as temporary:
        run(
            sys.executable,
            "-m",
            "videobench.cli",
            "demo",
            "--root",
            str(ROOT),
            "--out",
            temporary,
        )
    print("VideoBench verification complete.")


if __name__ == "__main__":
    main()
