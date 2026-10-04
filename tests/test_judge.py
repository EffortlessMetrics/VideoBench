from __future__ import annotations

from pathlib import Path

import pytest

from videobench.compiler import compile_task_file
from videobench.contracts import (
    JudgePack,
    JudgeStack,
    QualificationPack,
    QualificationRun,
)
from videobench.io import load_model, payload_as
from videobench.judge import qualify_judge, validate_judge_stack


def test_qualification_authorizes_only_demonstrated_criteria(example_root: Path) -> None:
    pack = load_model(example_root / "policies/judge-qualification-pack.yaml", QualificationPack)
    run = load_model(example_root / "policies/judge-qualification-run.yaml", QualificationRun)
    receipt = qualify_judge(qualification_pack=pack, qualification_run=run)
    assert receipt.anchor_accuracy == 1.0
    assert receipt.mutant_discrimination == 1.0
    assert receipt.prompt_injection_failure_rate == 0.0
    assert set(receipt.eligible_criteria) == set(pack.criterion_ids)


def test_failed_qualification_grants_no_eligibility(example_root: Path) -> None:
    pack = load_model(example_root / "policies/judge-qualification-pack.yaml", QualificationPack)
    run = load_model(example_root / "policies/judge-qualification-run.yaml", QualificationRun)
    run.observations[0].verdict = "reject"
    receipt = qualify_judge(qualification_pack=pack, qualification_run=run)
    assert receipt.eligible_criteria == []


def test_judge_transform_must_support_required_evidence(
    example_root: Path, tmp_path: Path
) -> None:
    paths = compile_task_file(example_root / "task.yaml", tmp_path)
    pack = payload_as(paths.judge_pack, JudgePack, expected_kind="judge_pack")
    stack = load_model(example_root / "policies/judge-stack.yaml", JudgeStack)
    validate_judge_stack(pack, stack)
    stack.evidence_transform.source_context_policy = {}
    with pytest.raises(ValueError, match="lacks required evidence capabilities"):
        validate_judge_stack(pack, stack)
