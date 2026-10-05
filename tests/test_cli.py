from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import videobench.cli as cli_module
from videobench.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_validate_compile_and_schema_commands(example_root: Path, tmp_path: Path) -> None:
    validate = runner.invoke(app, ["validate-task", str(example_root / "task.yaml")])
    assert validate.exit_code == 0, validate.stdout
    assert "valid" in validate.stdout

    compiled = tmp_path / "compiled"
    compile_result = runner.invoke(
        app, ["compile", str(example_root / "task.yaml"), "--out", str(compiled)]
    )
    assert compile_result.exit_code == 0, compile_result.stdout
    assert (compiled / "execution-pack.json").is_file()

    schemas = tmp_path / "schemas"
    schema_result = runner.invoke(app, ["export-schemas", "--out", str(schemas)])
    assert schema_result.exit_code == 0, schema_result.stdout
    assert len(list(schemas.glob("*.json"))) >= 10


def test_demo_command(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "demo"
    result = runner.invoke(app, ["demo", "--root", str(repo_root), "--out", str(output)])
    assert result.exit_code == 0, result.stdout
    assert "instrument valid" in result.stdout
    assert (output / "score-good.json").is_file()
    assert (output / "score-bad.json").is_file()


def test_cli_evidence_workflow(example_root: Path, tmp_path: Path) -> None:
    compiled = tmp_path / "compiled"
    assert (
        runner.invoke(
            app, ["compile", str(example_root / "task.yaml"), "--out", str(compiled)]
        ).exit_code
        == 0
    )

    condition = tmp_path / "run-condition.json"
    condition.write_text(
        json.dumps({"attempt_id": "cli-manual-1", "clean_state_id": "clean"}),
        encoding="utf-8",
    )
    usage = tmp_path / "usage.json"
    usage.write_text(json.dumps({"model_calls": 1, "tool_calls": 2}), encoding="utf-8")
    result_path = tmp_path / "result.json"
    captured = runner.invoke(
        app,
        [
            "capture",
            "--execution-pack",
            str(compiled / "execution-pack.json"),
            "--run-stack",
            str(example_root / "stacks/mock-good.yaml"),
            "--run-condition",
            str(condition),
            "--artifact-root",
            str(example_root / "candidates/good"),
            "--usage",
            str(usage),
            "--out",
            str(result_path),
        ],
    )
    assert captured.exit_code == 0, captured.stdout

    verification_path = tmp_path / "verification.json"
    verified = runner.invoke(
        app,
        [
            "verify",
            "--verifier-pack",
            str(compiled / "verifier-pack.json"),
            "--result",
            str(result_path),
            "--artifact-root",
            str(example_root / "candidates/good"),
            "--out",
            str(verification_path),
        ],
    )
    assert verified.exit_code == 0, verified.stdout

    receipt_path = tmp_path / "qualification.json"
    qualified = runner.invoke(
        app,
        [
            "qualify-judge",
            "--pack",
            str(example_root / "policies/judge-qualification-pack.yaml"),
            "--run",
            str(example_root / "policies/judge-qualification-run.yaml"),
            "--out",
            str(receipt_path),
        ],
    )
    assert qualified.exit_code == 0, qualified.stdout

    judgment_path = tmp_path / "judgment.json"
    judged = runner.invoke(
        app,
        [
            "judge-import",
            "--judge-pack",
            str(compiled / "judge-pack.json"),
            "--result",
            str(result_path),
            "--judge-stack",
            str(example_root / "policies/judge-stack.yaml"),
            "--qualification-receipt",
            str(receipt_path),
            "--judgment",
            str(example_root / "judgments/good.yaml"),
            "--out",
            str(judgment_path),
        ],
    )
    assert judged.exit_code == 0, judged.stdout

    score_path = tmp_path / "score.json"
    report_path = tmp_path / "report.md"
    scored = runner.invoke(
        app,
        [
            "score",
            "--result",
            str(result_path),
            "--verification",
            str(verification_path),
            "--judgment",
            str(judgment_path),
            "--scoring-policy",
            str(example_root / "policies/scoring.yaml"),
            "--pricing-policy",
            str(example_root / "policies/pricing.yaml"),
            "--judge-cost-usd",
            "0.01",
            "--report",
            str(report_path),
            "--out",
            str(score_path),
        ],
    )
    assert scored.exit_code == 0, scored.stdout
    assert report_path.is_file()
    score_payload = json.loads(score_path.read_text(encoding="utf-8"))["payload"]

    study_path = tmp_path / "study.json"
    study_path.write_text(
        json.dumps(
            {
                "study_id": "cli-study",
                "title": "CLI workflow",
                "instrument": "project_field",
                "forms": [
                    {
                        "task_id": "interview-cut-public-dev-v1",
                        "family_id": "interview-compression",
                        "form_id": "public-dev-v1",
                        "execution_pack_sha256": score_payload["execution_pack_sha256"],
                    }
                ],
                "stack_ids": ["mock-good"],
                "attempts_per_form": 1,
                "scoring_policy_id": "scoring-v1-gated",
                "pricing_policy_id": "synthetic-pricing-2026-10-04",
            }
        ),
        encoding="utf-8",
    )
    summarized = runner.invoke(
        app,
        [
            "study-summary",
            "--study",
            str(study_path),
            "--out",
            str(tmp_path / "summary.json"),
            str(score_path),
        ],
    )
    assert summarized.exit_code == 0, summarized.stdout


def test_run_command_cli(example_root: Path, tmp_path: Path) -> None:
    compiled = tmp_path / "compiled"
    assert (
        runner.invoke(
            app, ["compile", str(example_root / "task.yaml"), "--out", str(compiled)]
        ).exit_code
        == 0
    )
    condition = tmp_path / "condition.json"
    condition.write_text(
        json.dumps({"attempt_id": "cli-command-1", "clean_state_id": "clean"}),
        encoding="utf-8",
    )
    script = tmp_path / "candidate.py"
    script.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "out=Path(os.environ['VIDEOBENCH_OUTPUT_DIR'])\n"
        "(out/'receipt.txt').write_text(os.environ['VIDEOBENCH_ATTEMPT_ID'])\n",
        encoding="utf-8",
    )
    invoked = runner.invoke(
        app,
        [
            "run-command",
            "--execution-pack",
            str(compiled / "execution-pack.json"),
            "--run-stack",
            str(example_root / "stacks/mock-good.yaml"),
            "--run-condition",
            str(condition),
            "--workspace",
            str(tmp_path / "workspace"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--out",
            str(tmp_path / "result.json"),
            "--",
            sys.executable,
            str(script),
        ],
    )
    assert invoked.exit_code == 0, invoked.stdout
    assert (tmp_path / "artifacts/receipt.txt").read_text() == "cli-command-1"


def test_media_and_resolve_receipt_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    media_path = tmp_path / "sample.mp4"
    media_path.write_bytes(b"video")
    monkeypatch.setattr(cli_module, "ffprobe", lambda *_args, **_kwargs: {"format": {}})
    probed = runner.invoke(
        app,
        ["media-probe", str(media_path), "--out", str(tmp_path / "probe.json")],
    )
    assert probed.exit_code == 0, probed.stdout

    monkeypatch.setattr(
        cli_module,
        "capture_resolve_snapshot",
        lambda: {"resolve": {"version": "test"}, "project": {}, "unknowns": []},
    )
    snapshot = runner.invoke(app, ["resolve-snapshot", "--out", str(tmp_path / "resolve.json")])
    assert snapshot.exit_code == 0, snapshot.stdout
