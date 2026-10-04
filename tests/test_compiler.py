from __future__ import annotations

from pathlib import Path

import pytest

from videobench.compiler import compile_task, compile_task_file, validate_task_source
from videobench.contracts import ExecutionPack, JudgePack, TaskSource, VerifierPack
from videobench.io import load_envelope, load_model, payload_as


def test_compile_splits_candidate_verifier_and_judge_views(
    example_root: Path, tmp_path: Path
) -> None:
    paths = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(paths.execution_pack, ExecutionPack, expected_kind="execution_pack")
    verifier = payload_as(paths.verifier_pack, VerifierPack, expected_kind="verifier_pack")
    judge = payload_as(paths.judge_pack, JudgePack, expected_kind="judge_pack")

    assert execution.task_id == verifier.task_id == judge.task_id
    assert not hasattr(execution, "hidden_obligations")
    assert verifier.hidden_obligations
    assert judge.semantic_criteria
    assert "source_context" in judge.required_transform_capabilities
    assert "project_state" in judge.required_transform_capabilities
    assert load_envelope(paths.form_manifest, expected_kind="form_manifest")


def test_compile_rejects_exact_hidden_obligation_leak(example_root: Path, tmp_path: Path) -> None:
    task = load_model(example_root / "task.yaml", TaskSource)
    task.hidden_obligations = [task.brief]
    with pytest.raises(ValueError, match="leaks hidden obligations"):
        compile_task(task, tmp_path)


def test_task_validation_detects_missing_asset(example_root: Path, tmp_path: Path) -> None:
    task = load_model(example_root / "task.yaml", TaskSource)
    task.assets[0].path = "assets/does-not-exist.txt"
    with pytest.raises(ValueError, match="does not exist"):
        validate_task_source(task, example_root)


def test_task_validation_rejects_output_path_escape(example_root: Path) -> None:
    task = load_model(example_root / "task.yaml", TaskSource)
    task.output_contract.deliverables[0].path = "../outside.json"
    with pytest.raises(ValueError, match="root-contained relative path"):
        validate_task_source(task, example_root)
