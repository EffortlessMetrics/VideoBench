"""Versioned scoring, pricing, aggregation, and report projections."""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from videobench.canonical import sha256_hex
from videobench.contracts import (
    JudgmentBundle,
    PricingPolicy,
    ScoreView,
    ScoringPolicy,
    StackSummary,
    StudySpec,
    StudySummary,
    TrustReceipt,
    VerificationBundle,
    WorkResultBundle,
)
from videobench.types import (
    ArtifactValidity,
    ComparabilityStatus,
    JudgmentStatus,
    JudgmentVerdict,
    OutcomeStatus,
    ProvenanceStatus,
)


def calculate_list_equivalent_cost(result: WorkResultBundle, policy: PricingPolicy) -> float | None:
    """Reprice raw usage under a frozen list-price policy.

    A priced dimension whose usage is unknown makes the total unknown. Unpriced
    dimensions may remain unavailable without blocking a total because they contribute
    exactly zero under the frozen policy.
    """

    usage = result.usage
    pricing = policy.pricing
    million = 1_000_000

    def inclusive_partition_cost(
        *,
        total_value: int | None,
        subset_value: int | None,
        total_rate: float,
        subset_rate: float,
    ) -> float | None:
        if total_rate == 0 and subset_rate == 0:
            return 0.0
        if total_value is None:
            if total_rate == 0 and subset_value is not None:
                return subset_value / million * subset_rate
            return None
        if subset_value is None:
            if total_rate == subset_rate:
                return total_value / million * total_rate
            return None
        if subset_value > total_value:
            raise ValueError("priced token subset exceeds its inclusive total")
        return (
            (total_value - subset_value) / million * total_rate
            + subset_value / million * subset_rate
        )

    input_cost = inclusive_partition_cost(
        total_value=usage.input_tokens,
        subset_value=usage.cached_input_tokens,
        total_rate=pricing.input_per_million_usd,
        subset_rate=pricing.cached_input_per_million_usd,
    )
    output_cost = inclusive_partition_cost(
        total_value=usage.output_tokens,
        subset_value=usage.reasoning_tokens,
        total_rate=pricing.output_per_million_usd,
        subset_rate=pricing.reasoning_per_million_usd,
    )
    if input_cost is None or output_cost is None:
        return None

    total = usage.model_calls * pricing.per_call_usd + input_cost + output_cost
    for value, rate, divisor in (
        (usage.cache_write_tokens, pricing.cache_write_per_million_usd, million),
        (usage.image_units, pricing.image_unit_usd, 1.0),
        (usage.video_units, pricing.video_unit_usd, 1.0),
    ):
        if rate == 0:
            continue
        if value is None:
            return None
        total += value / divisor * rate
    return total


def _semantic_acceptance(judgment: JudgmentBundle, scoring: ScoringPolicy) -> bool:
    if judgment.fatal_semantic_failure:
        return False
    if any(
        item.verdict in {JudgmentVerdict.INDETERMINATE, JudgmentVerdict.INSUFFICIENT_BASIS}
        for item in judgment.criteria
    ):
        return False
    if not judgment.criteria:
        return False
    if scoring.semantic_aggregation == "mean_threshold":
        scores = [item.score for item in judgment.criteria]
        if any(score is None for score in scores):
            return False
        return (
            fmean(score for score in scores if score is not None)
            >= scoring.mean_acceptance_threshold
        )
    return all(item.verdict == JudgmentVerdict.ACCEPT for item in judgment.criteria)


def _validate_evidence_links(
    *,
    result: WorkResultBundle,
    verification: VerificationBundle,
    judgment: JudgmentBundle | None,
) -> None:
    identity = (result.task_id, result.family_id, result.form_id, result.instrument)
    verification_identity = (
        verification.task_id,
        verification.family_id,
        verification.form_id,
        verification.instrument,
    )
    if identity != verification_identity:
        raise ValueError("VerificationBundle belongs to a different task form")
    if result.run_condition.attempt_id != verification.attempt_id:
        raise ValueError("VerificationBundle belongs to a different attempt")

    result_sha256 = sha256_hex(result)
    if verification.work_result_sha256 != result_sha256:
        raise ValueError("VerificationBundle does not bind to this WorkResultBundle")

    if judgment is None:
        return
    judgment_identity = (
        judgment.task_id,
        judgment.family_id,
        judgment.form_id,
        judgment.instrument,
    )
    if identity != judgment_identity:
        raise ValueError("JudgmentBundle belongs to a different task form")
    if result.run_condition.attempt_id != judgment.attempt_id:
        raise ValueError("JudgmentBundle belongs to a different attempt")
    if judgment.work_result_sha256 != result_sha256:
        raise ValueError("JudgmentBundle does not bind to this WorkResultBundle")
    if judgment.acceptance_policy != verification.acceptance_policy:
        raise ValueError("Verification and judgment use different task acceptance policies")


def _default_trust(
    *,
    result: WorkResultBundle,
    verification: VerificationBundle,
    judgment: JudgmentBundle | None,
) -> TrustReceipt:
    if judgment is None:
        judgment_status = JudgmentStatus.UNJUDGED
    elif judgment.judge_stack.qualification_receipts:
        judgment_status = JudgmentStatus.QUALIFIED_PANEL_JUDGED
    else:
        judgment_status = JudgmentStatus.SELF_JUDGED
    return TrustReceipt(
        provenance=ProvenanceStatus.SELF_SUBMITTED,
        judgment_status=judgment_status,
        artifact_validity=verification.artifact_validity,
        comparability=ComparabilityStatus.VALID_NON_COMPARABLE,
        confidentiality=result.confidentiality,
    )


def score_result(
    *,
    result: WorkResultBundle,
    verification: VerificationBundle,
    judgment: JudgmentBundle | None,
    scoring_policy: ScoringPolicy,
    pricing_policy: PricingPolicy,
    judge_cost_usd: float | None = None,
    trust_receipt: TrustReceipt | None = None,
) -> ScoreView:
    """Project immutable run, verification, and judgment evidence into one score view."""

    if judge_cost_usd is not None and judge_cost_usd < 0:
        raise ValueError("judge_cost_usd must be nonnegative")
    _validate_evidence_links(
        result=result,
        verification=verification,
        judgment=judgment,
    )

    acceptance_policy = verification.acceptance_policy
    artifact_valid = verification.artifact_validity == ArtifactValidity.VALID
    semantic_acceptance = (
        _semantic_acceptance(judgment, scoring_policy) if judgment is not None else None
    )
    run_succeeded = result.outcome == OutcomeStatus.PASS

    accepted_work = run_succeeded
    if acceptance_policy.require_valid_artifact:
        accepted_work = accepted_work and artifact_valid
    if acceptance_policy.require_all_fatal_checks:
        accepted_work = accepted_work and verification.hard_contract_pass
    if acceptance_policy.require_semantic_acceptance:
        accepted_work = accepted_work and semantic_acceptance is True
    if (
        acceptance_policy.reject_on_fatal_semantic_failure
        and judgment is not None
        and judgment.fatal_semantic_failure
    ):
        accepted_work = False

    reason_codes = set(verification.reason_codes)
    if judgment is not None:
        for criterion in judgment.criteria:
            if criterion.verdict != JudgmentVerdict.ACCEPT:
                reason_codes.update(criterion.reason_codes)
    elif acceptance_policy.require_semantic_acceptance:
        reason_codes.add("semantic_judgment_missing")
    if not run_succeeded:
        reason_codes.add(f"run_outcome_{result.outcome.value}")

    trust = trust_receipt or _default_trust(
        result=result,
        verification=verification,
        judgment=judgment,
    )
    if trust.artifact_validity != verification.artifact_validity:
        raise ValueError("TrustReceipt artifact validity contradicts verification evidence")
    if trust.confidentiality != result.confidentiality:
        raise ValueError("TrustReceipt confidentiality contradicts the WorkResultBundle")
    if judgment is None and trust.judgment_status != JudgmentStatus.UNJUDGED:
        raise ValueError("TrustReceipt claims judgment authority without a JudgmentBundle")
    if judgment is not None and trust.judgment_status == JudgmentStatus.UNJUDGED:
        raise ValueError("TrustReceipt marks attached judgment evidence as unjudged")
    if (
        trust.judgment_status == JudgmentStatus.QUALIFIED_PANEL_JUDGED
        and judgment is not None
        and not judgment.judge_stack.qualification_receipts
    ):
        raise ValueError("Qualified-panel status requires qualification receipts")

    list_equivalent_cost = calculate_list_equivalent_cost(result, pricing_policy)
    if list_equivalent_cost is None:
        reason_codes.add("usage_evidence_incomplete")

    criteria = judgment.criteria if judgment is not None else []
    return ScoreView(
        task_id=result.task_id,
        family_id=result.family_id,
        form_id=result.form_id,
        instrument=result.instrument,
        execution_pack_sha256=result.execution_pack_sha256,
        attempt_id=result.run_condition.attempt_id,
        stack_id=result.run_stack.stack_id,
        work_result_sha256=sha256_hex(result),
        verification_sha256=sha256_hex(verification),
        judgment_sha256=sha256_hex(judgment) if judgment is not None else None,
        scoring_policy_sha256=sha256_hex(scoring_policy),
        pricing_policy_sha256=sha256_hex(pricing_policy),
        accepted_work=accepted_work,
        artifact_valid=artifact_valid,
        hard_contract_pass=verification.hard_contract_pass,
        semantic_acceptance=semantic_acceptance,
        criterion_scores={item.criterion_id: item.score for item in criteria},
        criterion_verdicts={item.criterion_id: item.verdict for item in criteria},
        reason_codes=sorted(reason_codes),
        candidate_metered_cost_usd=result.usage.actual_candidate_cost_usd,
        candidate_list_equivalent_cost_usd=list_equivalent_cost,
        judge_cost_usd=judge_cost_usd,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        reasoning_tokens=result.usage.reasoning_tokens,
        model_calls=result.usage.model_calls,
        tool_calls=result.usage.tool_calls,
        wall_seconds=result.usage.wall_seconds,
        human_seconds=result.usage.human_seconds,
        trust=trust,
        scoring_policy_id=scoring_policy.policy_id,
        pricing_policy_id=pricing_policy.policy_id,
    )


def summarize_study(study: StudySpec, scores: list[ScoreView]) -> StudySummary:
    """Produce stack summaries from the exact frozen forms named by a study."""

    allowed_forms = {
        (item.task_id, item.family_id, item.form_id, item.execution_pack_sha256)
        for item in study.forms
    }
    eligible = [
        item
        for item in scores
        if item.instrument == study.instrument
        and (
            item.task_id,
            item.family_id,
            item.form_id,
            item.execution_pack_sha256,
        )
        in allowed_forms
        and item.stack_id in study.stack_ids
        and item.scoring_policy_id == study.scoring_policy_id
        and item.pricing_policy_id == study.pricing_policy_id
    ]

    attempt_keys = [
        (item.stack_id, item.task_id, item.form_id, item.attempt_id) for item in eligible
    ]
    if len(attempt_keys) != len(set(attempt_keys)):
        raise ValueError("Study input contains duplicate score views for the same attempt")

    notes: list[str] = []
    excluded = len(scores) - len(eligible)
    if excluded:
        notes.append(
            f"Excluded {excluded} score view(s) outside the frozen forms, stacks, "
            "instrument, or analysis policies."
        )

    by_form_and_stack: dict[tuple[str, str, str, str], int] = defaultdict(int)
    for item in eligible:
        by_form_and_stack[(item.stack_id, item.task_id, item.family_id, item.form_id)] += 1
    for stack_id in study.stack_ids:
        for form in study.forms:
            key = (stack_id, form.task_id, form.family_id, form.form_id)
            attempts = by_form_and_stack.get(key, 0)
            if attempts > study.attempts_per_form:
                raise ValueError(
                    f"Study has {attempts} attempts for {key}, exceeding the declared "
                    f"{study.attempts_per_form}"
                )
            if attempts < study.attempts_per_form:
                notes.append(
                    f"Incomplete: {stack_id}/{form.task_id}/{form.form_id} has {attempts} "
                    f"of {study.attempts_per_form} declared attempts."
                )

    summaries: list[StackSummary] = []
    by_stack: dict[str, list[ScoreView]] = defaultdict(list)
    for item in eligible:
        by_stack[item.stack_id].append(item)

    for stack_id in study.stack_ids:
        stack_scores = by_stack.get(stack_id, [])
        by_family: dict[str, list[ScoreView]] = defaultdict(list)
        for item in stack_scores:
            by_family[item.family_id].append(item)
        family_rates = [
            fmean(1.0 if item.accepted_work else 0.0 for item in family_scores)
            for family_scores in by_family.values()
        ]
        indeterminate = sum(
            1
            for item in stack_scores
            if any(
                verdict in {JudgmentVerdict.INDETERMINATE, JudgmentVerdict.INSUFFICIENT_BASIS}
                for verdict in item.criterion_verdicts.values()
            )
        )
        priced_costs = [
            item.candidate_list_equivalent_cost_usd
            for item in stack_scores
            if item.candidate_list_equivalent_cost_usd is not None
        ]
        if stack_scores and len(priced_costs) != len(stack_scores):
            notes.append(
                f"Incomplete economics: {stack_id} has list-equivalent cost for "
                f"{len(priced_costs)} of {len(stack_scores)} eligible attempts."
            )
        summaries.append(
            StackSummary(
                stack_id=stack_id,
                attempts=len(stack_scores),
                families=len(by_family),
                accepted_work_rate=(
                    fmean(1.0 if item.accepted_work else 0.0 for item in stack_scores)
                    if stack_scores
                    else 0.0
                ),
                family_macro_acceptance=fmean(family_rates) if family_rates else 0.0,
                priced_attempts=len(priced_costs),
                mean_list_equivalent_cost_usd=(fmean(priced_costs) if priced_costs else None),
                mean_wall_seconds=(
                    fmean(item.wall_seconds for item in stack_scores) if stack_scores else 0.0
                ),
                mean_human_seconds=(
                    fmean(item.human_seconds for item in stack_scores) if stack_scores else 0.0
                ),
                indeterminate_rate=indeterminate / len(stack_scores) if stack_scores else 0.0,
            )
        )
    return StudySummary(study_id=study.study_id, summaries=summaries, notes=notes)


def render_score_markdown(score: ScoreView) -> str:
    verdict = "ACCEPTED" if score.accepted_work else "REJECTED"
    lines = [
        f"# VideoBench result: {verdict}",
        "",
        f"- **Task:** `{score.task_id}`",
        f"- **Family:** `{score.family_id}`",
        f"- **Form:** `{score.form_id}`",
        f"- **Attempt:** `{score.attempt_id}`",
        f"- **RunStack:** `{score.stack_id}`",
        "",
        "## Gates",
        "",
        f"- Artifact valid: **{score.artifact_valid}**",
        f"- Hard contract: **{score.hard_contract_pass}**",
        f"- Semantic acceptance: **{score.semantic_acceptance}**",
        "",
        "## Criteria",
        "",
        "| Criterion | Verdict | Score |",
        "|---|---:|---:|",
    ]
    for criterion_id in sorted(score.criterion_verdicts):
        value = score.criterion_scores.get(criterion_id)
        rendered = "—" if value is None else f"{value:.2f}"
        lines.append(
            f"| `{criterion_id}` | {score.criterion_verdicts[criterion_id].value} | {rendered} |"
        )
    if not score.criterion_verdicts:
        lines.append("| — | unjudged | — |")
    lines.extend(
        [
            "",
            "## Economics",
            "",
            f"- Metered candidate cost: {score.candidate_metered_cost_usd}",
            "- List-equivalent candidate cost: "
            + (
                f"${score.candidate_list_equivalent_cost_usd:.6f}"
                if score.candidate_list_equivalent_cost_usd is not None
                else "unknown"
            ),
            f"- Judge cost: {score.judge_cost_usd}",
            f"- Wall time: {score.wall_seconds:.3f}s",
            f"- Human time: {score.human_seconds:.3f}s",
            "",
            "## Evidence links",
            "",
            f"- Work result: `{score.work_result_sha256}`",
            f"- Verification: `{score.verification_sha256}`",
            f"- Judgment: `{score.judgment_sha256}`",
            f"- Scoring policy: `{score.scoring_policy_sha256}`",
            f"- Pricing policy: `{score.pricing_policy_sha256}`",
            "",
            "## Reason codes",
            "",
        ]
    )
    if score.reason_codes:
        lines.extend(f"- `{reason}`" for reason in score.reason_codes)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)
