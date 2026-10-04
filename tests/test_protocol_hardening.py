from __future__ import annotations

from pathlib import Path

import pytest

from videobench.analysis import score_result
from videobench.canonical import sha256_hex
from videobench.compiler import compile_task_file, validate_task_source
from videobench.contracts import (
    AcceptancePolicy,
    CriterionJudgment,
    ExecutionPack,
    JudgePack,
    JudgeStack,
    PricingPolicy,
    QualificationPack,
    QualificationRun,
    RunCondition,
    RunStack,
    ScoringPolicy,
    TaskSource,
    TrustReceipt,
    UsageRecord,
    VerifierPack,
)
from videobench.io import load_model, payload_as
from videobench.judge import (
    build_judgment_bundle,
    import_judgment_file,
    qualify_judge,
    validate_judge_stack,
)
from videobench.runner import capture_manual_result, run_mock_candidate
from videobench.types import (
    ArtifactValidity,
    ComparabilityStatus,
    JudgmentStatus,
    OutcomeStatus,
)
from videobench.verifier import verify_result


def _evidence(example_root: Path, tmp_path: Path):
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    verifier = payload_as(compiled.verifier_pack, VerifierPack, expected_kind="verifier_pack")
    judge_pack = payload_as(compiled.judge_pack, JudgePack, expected_kind="judge_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    result = run_mock_candidate(
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="hardening-1", clean_state_id="clean"),
        candidate_dir=example_root / "candidates/good",
        output_dir=tmp_path / "artifacts",
        usage=UsageRecord(model_calls=1, tool_calls=2, input_tokens=100, output_tokens=20),
    )
    verification = verify_result(
        verifier_pack=verifier,
        result=result,
        artifact_root=tmp_path / "artifacts",
    )
    qualification_pack = load_model(
        example_root / "policies/judge-qualification-pack.yaml", QualificationPack
    )
    qualification_run = load_model(
        example_root / "policies/judge-qualification-run.yaml", QualificationRun
    )
    receipt = qualify_judge(
        qualification_pack=qualification_pack,
        qualification_run=qualification_run,
    )
    judge_stack = load_model(example_root / "policies/judge-stack.yaml", JudgeStack)
    judge_stack.qualification_receipts = [receipt]
    judgment = import_judgment_file(
        path=example_root / "judgments/good.yaml",
        judge_pack=judge_pack,
        result=result,
        judge_stack=judge_stack,
    )
    return result, verification, judge_pack, judge_stack, judgment


def test_evidence_chain_records_all_upstream_digests(
    example_root: Path, tmp_path: Path
) -> None:
    result, verification, _, _, judgment = _evidence(example_root, tmp_path)
    scoring = load_model(example_root / "policies/scoring.yaml", ScoringPolicy)
    pricing = load_model(example_root / "policies/pricing.yaml", PricingPolicy)
    score = score_result(
        result=result,
        verification=verification,
        judgment=judgment,
        scoring_policy=scoring,
        pricing_policy=pricing,
    )
    assert verification.work_result_sha256 == sha256_hex(result)
    assert judgment.work_result_sha256 == sha256_hex(result)
    assert score.work_result_sha256 == sha256_hex(result)
    assert score.verification_sha256 == sha256_hex(verification)
    assert score.judgment_sha256 == sha256_hex(judgment)
    assert score.scoring_policy_sha256 == sha256_hex(scoring)
    assert score.pricing_policy_sha256 == sha256_hex(pricing)


def test_qualification_receipt_cannot_be_reused_for_changed_judge_stack(
    example_root: Path, tmp_path: Path
) -> None:
    _, _, judge_pack, judge_stack, _ = _evidence(example_root, tmp_path)
    judge_stack.panel_policy = "materially-different-panel"
    with pytest.raises(ValueError, match="does not bind"):
        validate_judge_stack(judge_pack, judge_stack)


def test_judgment_verdict_must_match_declared_threshold(
    example_root: Path, tmp_path: Path
) -> None:
    result, _, judge_pack, _, _ = _evidence(example_root, tmp_path)
    unqualified_stack = load_model(example_root / "policies/judge-stack.yaml", JudgeStack)
    criteria = [
        CriterionJudgment(
            criterion_id="brief-adherence",
            verdict="accept",
            score=2.0,
            confidence=1.0,
            explanation="Contradictory on purpose.",
        ),
        CriterionJudgment(
            criterion_id="editorial-coherence",
            verdict="accept",
            score=4.0,
            confidence=1.0,
            explanation="Control criterion.",
        ),
    ]
    with pytest.raises(ValueError, match="marked accept below"):
        build_judgment_bundle(
            judge_pack=judge_pack,
            result=result,
            judge_stack=unqualified_stack,
            criteria=criteria,
        )


def test_objective_only_instrument_scores_without_semantic_judgment(
    example_root: Path, tmp_path: Path
) -> None:
    result, verification, _, _, _ = _evidence(example_root, tmp_path)
    verification.acceptance_policy = AcceptancePolicy(require_semantic_acceptance=False)
    score = score_result(
        result=result,
        verification=verification,
        judgment=None,
        scoring_policy=load_model(example_root / "policies/scoring.yaml", ScoringPolicy),
        pricing_policy=load_model(example_root / "policies/pricing.yaml", PricingPolicy),
    )
    assert score.accepted_work
    assert score.semantic_acceptance is None
    assert score.trust.judgment_status == JudgmentStatus.UNJUDGED
    assert score.trust.comparability == ComparabilityStatus.VALID_NON_COMPARABLE


def test_required_semantic_judgment_cannot_be_omitted(
    example_root: Path, tmp_path: Path
) -> None:
    result, verification, _, _, _ = _evidence(example_root, tmp_path)
    score = score_result(
        result=result,
        verification=verification,
        judgment=None,
        scoring_policy=load_model(example_root / "policies/scoring.yaml", ScoringPolicy),
        pricing_policy=load_model(example_root / "policies/pricing.yaml", PricingPolicy),
    )
    assert not score.accepted_work
    assert "semantic_judgment_missing" in score.reason_codes


def test_score_rejects_tampered_evidence_link(example_root: Path, tmp_path: Path) -> None:
    result, verification, _, _, judgment = _evidence(example_root, tmp_path)
    verification.work_result_sha256 = "0" * 64
    with pytest.raises(ValueError, match="does not bind"):
        score_result(
            result=result,
            verification=verification,
            judgment=judgment,
            scoring_policy=load_model(example_root / "policies/scoring.yaml", ScoringPolicy),
            pricing_policy=load_model(example_root / "policies/pricing.yaml", PricingPolicy),
        )


def test_manual_capture_marks_resource_overage_as_budget_exhausted(
    example_root: Path, tmp_path: Path
) -> None:
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(compiled.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    stack.resource_envelope.max_tool_calls = 1
    artifact_root = tmp_path / "manual"
    artifact_root.mkdir()
    (artifact_root / "receipt.txt").write_text("evidence", encoding="utf-8")
    result = capture_manual_result(
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="budget", clean_state_id="clean"),
        output_dir=artifact_root,
        usage=UsageRecord(tool_calls=2),
    )
    assert result.outcome == OutcomeStatus.BUDGET_EXHAUSTED
    assert result.events[-1].event_type == "resource_budget_exceeded"


def test_task_asset_path_cannot_escape_fixture_root(
    example_root: Path,
) -> None:
    task = load_model(example_root / "task.yaml", TaskSource)
    task.assets[0].path = "../outside.txt"
    with pytest.raises(ValueError, match="root-contained relative path"):
        validate_task_source(task, example_root)


def test_verifier_and_judge_reject_result_from_another_execution_pack(
    example_root: Path, tmp_path: Path
) -> None:
    result, _, judge_pack, judge_stack, _ = _evidence(example_root, tmp_path)
    compiled = compile_task_file(example_root / "task.yaml", tmp_path / "second-compiled")
    verifier = payload_as(compiled.verifier_pack, VerifierPack, expected_kind="verifier_pack")
    result.execution_pack_sha256 = "f" * 64

    with pytest.raises(ValueError, match="ExecutionPack"):
        verify_result(
            verifier_pack=verifier,
            result=result,
            artifact_root=tmp_path / "artifacts",
        )
    with pytest.raises(ValueError, match="ExecutionPack"):
        import_judgment_file(
            path=example_root / "judgments/good.yaml",
            judge_pack=judge_pack,
            result=result,
            judge_stack=judge_stack,
        )


def test_trust_receipt_requires_basis_for_comparability_claim() -> None:
    with pytest.raises(ValueError, match="evidence_refs"):
        TrustReceipt(
            artifact_validity=ArtifactValidity.VALID,
            comparability=ComparabilityStatus.DIRECTLY_COMPARABLE,
        )


def test_score_rejects_unqualified_panel_claim(example_root: Path, tmp_path: Path) -> None:
    result, verification, _, _, judgment = _evidence(example_root, tmp_path)
    judgment.judge_stack.qualification_receipts = []
    trust = TrustReceipt(
        artifact_validity=ArtifactValidity.VALID,
        judgment_status=JudgmentStatus.QUALIFIED_PANEL_JUDGED,
    )
    with pytest.raises(ValueError, match="qualification receipts"):
        score_result(
            result=result,
            verification=verification,
            judgment=judgment,
            scoring_policy=load_model(
                example_root / "policies/scoring.yaml", ScoringPolicy
            ),
            pricing_policy=load_model(
                example_root / "policies/pricing.yaml", PricingPolicy
            ),
            trust_receipt=trust,
        )
