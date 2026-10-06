from __future__ import annotations

import sys
from pathlib import Path

import pytest

from videobench.compiler import compile_task_file
from videobench.contracts import ExecutionPack, RunCondition, RunStack
from videobench.io import load_model, payload_as
from videobench.runner import run_command
from videobench.types import OutcomeStatus


def test_command_runner_exposes_paths_and_captures_outputs(
    example_root: Path, tmp_path: Path
) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    script = tmp_path / "candidate.py"
    script.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "out=Path(os.environ['VIDEOBENCH_OUTPUT_DIR'])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out/'receipt.txt').write_text(os.environ['VIDEOBENCH_ATTEMPT_ID'])\n",
        encoding="utf-8",
    )
    result = run_command(
        execution_pack_path=compiled.execution_pack,
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="cmd-1", clean_state_id="clean"),
        command=[sys.executable, str(script)],
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
    )
    assert result.outcome == OutcomeStatus.PASS
    assert [item.path for item in result.artifacts] == ["receipt.txt"]
    assert (tmp_path / "output/receipt.txt").read_text() == "cmd-1"


def test_command_runner_records_nonzero_exit(example_root: Path, tmp_path: Path) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    result = run_command(
        execution_pack_path=compiled.execution_pack,
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="cmd-fail", clean_state_id="clean"),
        command=[sys.executable, "-c", "import sys; print('nope'); sys.exit(3)"],
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
    )
    assert result.outcome == OutcomeStatus.TOOL_FAILURE
    assert "nope" in result.stdout


def test_command_runner_records_timeout(example_root: Path, tmp_path: Path) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    stack.resource_envelope.max_wall_seconds = 0.01
    result = run_command(
        execution_pack_path=compiled.execution_pack,
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="cmd-timeout", clean_state_id="clean"),
        command=[sys.executable, "-c", "import time; time.sleep(1)"],
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
    )
    assert result.outcome == OutcomeStatus.TIMED_OUT


def test_command_runner_rejects_stale_output_directory(example_root: Path, tmp_path: Path) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    output = tmp_path / "output"
    output.mkdir()
    (output / "stale.txt").write_text("stale", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        run_command(
            execution_pack_path=compiled.execution_pack,
            execution_pack=execution,
            run_stack=stack,
            run_condition=RunCondition(attempt_id="cmd-stale", clean_state_id="clean"),
            command=[sys.executable, "-c", "print('unused')"],
            workspace=tmp_path / "workspace",
            output_dir=output,
        )


def test_command_runner_rejects_stale_usage_receipt(example_root: Path, tmp_path: Path) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    usage = tmp_path / "usage.json"
    usage.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Usage path must not exist"):
        run_command(
            execution_pack_path=compiled.execution_pack,
            execution_pack=execution,
            run_stack=stack,
            run_condition=RunCondition(attempt_id="cmd-stale-usage", clean_state_id="clean"),
            command=[sys.executable, "-c", "print('unused')"],
            workspace=tmp_path / "workspace",
            output_dir=tmp_path / "output",
            usage_path=usage,
        )


def test_command_runner_rejects_reserved_environment_override(
    example_root: Path, tmp_path: Path
) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    with pytest.raises(ValueError, match="protocol variables"):
        run_command(
            execution_pack_path=compiled.execution_pack,
            execution_pack=execution,
            run_stack=stack,
            run_condition=RunCondition(attempt_id="cmd-env", clean_state_id="clean"),
            command=[sys.executable, "-c", "print('unused')"],
            workspace=tmp_path / "workspace",
            output_dir=tmp_path / "output",
            extra_env={"VIDEOBENCH_OUTPUT_DIR": str(tmp_path / "elsewhere")},
        )


def test_command_runner_records_invalid_usage_receipt(example_root: Path, tmp_path: Path) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    script = tmp_path / "candidate.py"
    script.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "out=Path(os.environ['VIDEOBENCH_OUTPUT_DIR'])\n"
        "(out/'artifact.txt').write_text('evidence')\n"
        "Path(os.environ['VIDEOBENCH_USAGE_PATH']).write_text('{bad json')\n",
        encoding="utf-8",
    )
    result = run_command(
        execution_pack_path=compiled.execution_pack,
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="cmd-usage", clean_state_id="clean"),
        command=[sys.executable, str(script)],
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        usage_path=tmp_path / "usage.json",
    )
    assert result.outcome == OutcomeStatus.PROTOCOL_INVALID
    assert "valid_usage_receipt" in result.known_missing_evidence
    assert result.events[-1].event_type == "usage_receipt_invalid"
    assert [artifact.path for artifact in result.artifacts] == ["artifact.txt"]


def test_command_runner_records_failure_to_start(example_root: Path, tmp_path: Path) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    result = run_command(
        execution_pack_path=compiled.execution_pack,
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="cmd-missing", clean_state_id="clean"),
        command=["__videobench_missing_executable__"],
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
    )
    assert result.outcome == OutcomeStatus.TOOL_FAILURE
    assert result.events[-1].event_type == "run_failed_to_start"


def test_command_runner_marks_unreported_usage_unknown(example_root: Path, tmp_path: Path) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    result = run_command(
        execution_pack_path=compiled.execution_pack,
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="cmd-no-usage", clean_state_id="clean"),
        command=[sys.executable, "-c", "print('done')"],
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
    )
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert "input_tokens_not_reported" in result.known_missing_evidence
    assert "candidate_cost_not_reported" in result.known_missing_evidence


def test_command_runner_rejects_missing_expected_usage_receipt(
    example_root: Path, tmp_path: Path
) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    result = run_command(
        execution_pack_path=compiled.execution_pack,
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="cmd-missing-usage", clean_state_id="clean"),
        command=[sys.executable, "-c", "print('done')"],
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        usage_path=tmp_path / "usage.json",
    )
    assert result.outcome == OutcomeStatus.PROTOCOL_INVALID
    assert "valid_usage_receipt" in result.known_missing_evidence
