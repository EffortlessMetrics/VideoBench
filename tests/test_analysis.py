from __future__ import annotations

import pytest

from videobench.analysis import calculate_list_equivalent_cost, summarize_study
from videobench.contracts import (
    HarnessPolicy,
    ModelIdentity,
    PricingPolicy,
    ResolveEnvironment,
    RunCondition,
    RunStack,
    ScoreView,
    StudyFormRef,
    StudySpec,
    SurfaceProfile,
    TokenPricing,
    TrustReceipt,
    UsageRecord,
    WorkResultBundle,
)
from videobench.types import Instrument, JudgmentVerdict, OutcomeStatus, SurfaceKind


def _result(usage: UsageRecord) -> WorkResultBundle:
    stack = RunStack(
        stack_id="s",
        system=ModelIdentity(provider="p", model="m"),
        surface=SurfaceProfile(
            observation_surface=SurfaceKind.COMMAND,
            action_surface=SurfaceKind.COMMAND,
        ),
        harness=HarnessPolicy(harness="h"),
        environment=ResolveEnvironment(operating_system="x", resolve_version="1"),
    )
    return WorkResultBundle(
        task_id="t",
        family_id="f",
        form_id="form",
        instrument=Instrument.EXECUTION_CORE,
        execution_pack_sha256="0" * 64,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="a", clean_state_id="c"),
        outcome=OutcomeStatus.PASS,
        events=[],
        artifacts=[],
        usage=usage,
    )


def test_pricing_preserves_token_categories() -> None:
    policy = PricingPolicy(
        policy_id="p",
        effective_date="2026-01-01",
        provider="p",
        model="m",
        pricing=TokenPricing(
            input_per_million_usd=1,
            cached_input_per_million_usd=0.1,
            reasoning_per_million_usd=4,
            output_per_million_usd=2,
            per_call_usd=0.5,
        ),
        source_note="test",
    )
    usage = UsageRecord(
        input_tokens=1_000_000,
        cached_input_tokens=1_000_000,
        reasoning_tokens=1_000_000,
        output_tokens=1_000_000,
        model_calls=2,
    )
    assert calculate_list_equivalent_cost(_result(usage), policy) == 8.1


def _score(stack: str, family: str, accepted: bool, attempt: int = 1) -> ScoreView:
    return ScoreView(
        task_id=f"task-{family}",
        family_id=family,
        form_id="form",
        instrument=Instrument.PROJECT_FIELD,
        execution_pack_sha256="0" * 64,
        attempt_id=f"{stack}-{family}-{attempt}",
        stack_id=stack,
        work_result_sha256="1" * 64,
        verification_sha256="2" * 64,
        judgment_sha256="3" * 64,
        scoring_policy_sha256="4" * 64,
        pricing_policy_sha256="5" * 64,
        accepted_work=accepted,
        artifact_valid=True,
        hard_contract_pass=accepted,
        semantic_acceptance=accepted,
        criterion_scores={"c": 4.0 if accepted else 1.0},
        criterion_verdicts={
            "c": JudgmentVerdict.ACCEPT if accepted else JudgmentVerdict.REJECT
        },
        reason_codes=[],
        candidate_metered_cost_usd=None,
        candidate_list_equivalent_cost_usd=1.0,
        input_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        model_calls=1,
        tool_calls=1,
        wall_seconds=1.0,
        human_seconds=0.0,
        trust=TrustReceipt(),
        scoring_policy_id="s",
        pricing_policy_id="p",
    )


def test_study_macro_averages_by_family_not_attempt_count() -> None:
    study = StudySpec(
        study_id="study",
        title="test",
        instrument=Instrument.PROJECT_FIELD,
        forms=[
            StudyFormRef(
                task_id="task-a",
                family_id="a",
                form_id="form",
                execution_pack_sha256="0" * 64,
            ),
            StudyFormRef(
                task_id="task-b",
                family_id="b",
                form_id="form",
                execution_pack_sha256="0" * 64,
            ),
        ],
        stack_ids=["stack"],
        attempts_per_form=3,
        scoring_policy_id="s",
        pricing_policy_id="p",
    )
    scores = [
        _score("stack", "a", True, 1),
        _score("stack", "a", True, 2),
        _score("stack", "a", True, 3),
        _score("stack", "b", False, 1),
    ]
    summary = summarize_study(study, scores).summaries[0]
    assert summary.accepted_work_rate == 0.75
    assert summary.family_macro_acceptance == 0.5


def test_study_excludes_scores_outside_exact_frozen_form() -> None:
    study = StudySpec(
        study_id="study",
        title="exact form",
        instrument=Instrument.PROJECT_FIELD,
        forms=[
            StudyFormRef(
                task_id="task-a",
                family_id="a",
                form_id="form",
                execution_pack_sha256="0" * 64,
            )
        ],
        stack_ids=["stack"],
        attempts_per_form=1,
        scoring_policy_id="s",
        pricing_policy_id="p",
    )
    wrong = _score("stack", "a", True)
    wrong.execution_pack_sha256 = "9" * 64
    summary = summarize_study(study, [wrong])
    assert summary.summaries[0].attempts == 0
    assert any("Excluded 1" in note for note in summary.notes)


def test_study_rejects_duplicate_attempt_evidence() -> None:
    study = StudySpec(
        study_id="study",
        title="duplicates",
        instrument=Instrument.PROJECT_FIELD,
        forms=[
            StudyFormRef(
                task_id="task-a",
                family_id="a",
                form_id="form",
                execution_pack_sha256="0" * 64,
            )
        ],
        stack_ids=["stack"],
        attempts_per_form=2,
        scoring_policy_id="s",
        pricing_policy_id="p",
    )
    score = _score("stack", "a", True)

    with pytest.raises(ValueError, match="duplicate score views"):
        summarize_study(study, [score, score])
