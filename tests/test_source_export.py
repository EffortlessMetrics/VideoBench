"""Exercise the workflow's archive boundary using synthetic private state."""

import subprocess
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_source_export_boundary(tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/export-source.yml").read_text())
    checkout, archive, upload = workflow["jobs"]["export"]["steps"]
    assert checkout["with"]["persist-credentials"] is False
    assert upload["with"]["path"] == "${{ runner.temp }}/videobench-source.zip"
    assert upload["with"]["if-no-files-found"] == "error"
    assert not upload["with"].get("include-hidden-files", False)
    assert archive["run"] == (
        'git archive --format=zip --output="$RUNNER_TEMP/videobench-source.zip" HEAD'
    )

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init")
    git("config", "core.autocrlf", "false")
    sources = {"pyproject.toml": "[project]\nname='fixture'\n", ".python-version": "3.11\n"}
    for name, content in sources.items():
        (repo / name).write_bytes(content.encode())
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    marker = "SYNTHETIC_PRIVATE_EXPORT_MARKER"
    for name in [".env", ".git/credentials", "build/private.txt", ".venv/private.txt"]:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(marker)
    git("config", "http.https://example.invalid/.extraheader", marker)
    # Dirty tracked files must also come from the committed tree.
    (repo / ".python-version").write_text(marker)
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    git("archive", "--format=zip", f"--output={first}", "HEAD")
    git("archive", "--format=zip", f"--output={second}", "HEAD")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as exported:
        assert set(exported.namelist()) == set(sources)
        for name, content in sources.items():
            assert exported.read(name).decode() == content
        assert all(marker.encode() not in exported.read(name) for name in exported.namelist())
