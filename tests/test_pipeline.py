from __future__ import annotations

from pathlib import Path

from videobench.analysis import score_result
from videobench.compiler import compile_task_file
from videobench.contracts import (
    ExecutionPack,
    JudgePack,
    JudgeStack,
    PricingPolicy,
    QualificationPack,
    QualificationRun,
    RunCondition,
    RunStack,
    ScoringPolicy,
    UsageRecord,
    VerifierPack,
)
from videobench.io import load_model, payload_as
from videobench.judge import import_judgment_file, qualify_judge
from videobench.runner import run_mock_candidate
from videobench.types import ArtifactValidity
from videobench.verifier import verify_result


def _evaluate(example_root: Path, tmp_path: Path, candidate: str):
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    verifier = payload_as(compiled.verifier_pack, VerifierPack, expected_kind="verifier_pack")
    judge_pack = payload_as(compiled.judge_pack, JudgePack, expected_kind="judge_pack")
    stack = load_model(example_root / f"stacks/mock-{candidate}.yaml", RunStack)
    condition = RunCondition(attempt_id=f"test-{candidate}", clean_state_id="clean", seed=1)
    output = tmp_path / "artifacts" / candidate
    result = run_mock_candidate(
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        candidate_dir=example_root / "candidates" / candidate,
        output_dir=output,
        usage=UsageRecord(
            input_tokens=1000,
            reasoning_tokens=200,
            output_tokens=100,
            model_calls=1,
            tool_calls=4,
            actual_candidate_cost_usd=0.01,
        ),
    )
    verification = verify_result(verifier_pack=verifier, result=result, artifact_root=output)
    judge_stack = load_model(example_root / "policies/judge-stack.yaml", JudgeStack)
    qualification_pack = load_model(
        example_root / "policies/judge-qualification-pack.yaml", QualificationPack
    )
    qualification_run = load_model(
        example_root / "policies/judge-qualification-run.yaml", QualificationRun
    )
    judge_stack.qualification_receipts = [
        qualify_judge(qualification_pack=qualification_pack, qualification_run=qualification_run)
    ]
    judgment = import_judgment_file(
        path=example_root / f"judgments/{candidate}.yaml",
        judge_pack=judge_pack,
        result=result,
        judge_stack=judge_stack,
    )
    score = score_result(
        result=result,
        verification=verification,
        judgment=judgment,
        scoring_policy=load_model(example_root / "policies/scoring.yaml", ScoringPolicy),
        pricing_policy=load_model(example_root / "policies/pricing.yaml", PricingPolicy),
    )
    return output, result, verification, score


def test_vertical_slice_accepts_good_and_rejects_bad(example_root: Path, tmp_path: Path) -> None:
    _, _, good_verification, good_score = _evaluate(example_root, tmp_path / "good", "good")
    _, _, bad_verification, bad_score = _evaluate(example_root, tmp_path / "bad", "bad")
    assert good_verification.hard_contract_pass
    assert good_score.accepted_work
    assert not bad_verification.hard_contract_pass
    assert not bad_score.accepted_work
    assert "wrong_aspect_ratio" in bad_score.reason_codes
    assert "audio_clipping" in bad_score.reason_codes


def test_capture_integrity_detects_post_run_mutation(example_root: Path, tmp_path: Path) -> None:
    output, result, _, _ = _evaluate(example_root, tmp_path, "good")
    (output / "timeline.json").write_text("{}", encoding="utf-8")
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled-again")
    verifier = payload_as(compiled.verifier_pack, VerifierPack, expected_kind="verifier_pack")
    verification = verify_result(verifier_pack=verifier, result=result, artifact_root=output)
    assert verification.artifact_validity == ArtifactValidity.INVALID
    assert "capture_integrity_mismatch" in verification.reason_codes
