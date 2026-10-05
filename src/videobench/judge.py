"""Judgment import, validation, and judge qualification."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from videobench.canonical import sha256_hex
from videobench.contracts import (
    CriterionJudgment,
    JudgePack,
    JudgeStack,
    JudgmentBundle,
    JudgmentSubmission,
    QualificationPack,
    QualificationReceipt,
    QualificationRun,
    WorkResultBundle,
)
from videobench.io import load_data
from videobench.types import JudgmentVerdict, utc_now


def judge_configuration_digest(judge_stack: JudgeStack) -> str:
    """Hash the judge configuration without its qualification receipts.

    Receipts attest to a configuration and therefore cannot be part of the configuration
    identity they sign. The remaining fields capture the model panel, evidence transform,
    panel policy, and disclosed unknowns that materially shape a judgment.
    """

    return sha256_hex(
        {
            "judge_stack_id": judge_stack.judge_stack_id,
            "judges": judge_stack.judges,
            "evidence_transform": judge_stack.evidence_transform,
            "panel_policy": judge_stack.panel_policy,
            "known_unknowns": judge_stack.known_unknowns,
        }
    )


def evidence_transform_capabilities(judge_stack: JudgeStack) -> set[str]:
    transform = judge_stack.evidence_transform
    capabilities: set[str] = set()
    if transform.video_proxy.get("continuous", False):
        capabilities.add("continuous_video")
    if transform.audio_policy.get("included", False):
        capabilities.add("audio")
    if transform.source_context_policy.get("included", False):
        capabilities.add("source_context")
    if transform.source_context_policy.get("project_state", False):
        capabilities.add("project_state")
    return capabilities


def validate_judge_stack(judge_pack: JudgePack, judge_stack: JudgeStack) -> None:
    """Validate evidence visibility and any attached qualification authority."""

    available = evidence_transform_capabilities(judge_stack)
    missing = set(judge_pack.required_transform_capabilities) - available
    if missing:
        raise ValueError(
            f"JudgeStack {judge_stack.judge_stack_id!r} lacks required evidence capabilities: "
            f"{sorted(missing)}"
        )

    if not judge_stack.qualification_receipts:
        return

    now = utc_now()
    configuration_sha256 = judge_configuration_digest(judge_stack)
    eligible: set[str] = set()
    for receipt in judge_stack.qualification_receipts:
        if receipt.judge_stack_id != judge_stack.judge_stack_id:
            raise ValueError(
                "Qualification receipt belongs to a different JudgeStack: "
                f"{receipt.judge_stack_id!r}"
            )
        if receipt.judge_configuration_sha256 != configuration_sha256:
            raise ValueError(
                "Qualification receipt does not bind to the current JudgeStack configuration"
            )
        if receipt.valid_from > now:
            raise ValueError("Qualification receipt is not yet valid")
        if receipt.valid_until is not None and receipt.valid_until < now:
            raise ValueError("Qualification receipt has expired")
        eligible.update(receipt.eligible_criteria)

    required = {criterion.criterion_id for criterion in judge_pack.semantic_criteria}
    missing_eligibility = required - eligible
    if missing_eligibility:
        raise ValueError(
            "JudgeStack qualification receipts do not authorize all task criteria: "
            f"{sorted(missing_eligibility)}"
        )


def _validate_criterion_judgment(
    criterion_id: str,
    judgment: CriterionJudgment,
    *,
    min_score: float,
    max_score: float,
    acceptance_threshold: float,
) -> None:
    if judgment.verdict in {
        JudgmentVerdict.INDETERMINATE,
        JudgmentVerdict.INSUFFICIENT_BASIS,
    }:
        if judgment.score is not None:
            raise ValueError(
                f"Criterion {criterion_id!r} cannot carry a numeric score when its verdict is "
                f"{judgment.verdict.value!r}"
            )
        return

    if judgment.score is None:
        raise ValueError(
            f"Criterion {criterion_id!r} requires a numeric score for verdict "
            f"{judgment.verdict.value!r}"
        )
    if not min_score <= judgment.score <= max_score:
        raise ValueError(
            f"Criterion {criterion_id!r} score {judgment.score} is outside "
            f"[{min_score}, {max_score}]"
        )
    if judgment.verdict == JudgmentVerdict.ACCEPT and judgment.score < acceptance_threshold:
        raise ValueError(
            f"Criterion {criterion_id!r} is marked accept below its declared threshold "
            f"{acceptance_threshold}"
        )
    if judgment.verdict == JudgmentVerdict.REJECT and judgment.score >= acceptance_threshold:
        raise ValueError(
            f"Criterion {criterion_id!r} is marked reject at or above its declared threshold "
            f"{acceptance_threshold}"
        )


def build_judgment_bundle(
    *,
    judge_pack: JudgePack,
    result: WorkResultBundle,
    judge_stack: JudgeStack,
    criteria: list[CriterionJudgment],
    raw_judgments: list[dict[str, Any]] | None = None,
    panel_disagreement: dict[str, Any] | None = None,
) -> JudgmentBundle:
    if (
        judge_pack.task_id != result.task_id
        or judge_pack.family_id != result.family_id
        or judge_pack.form_id != result.form_id
        or judge_pack.instrument != result.instrument
    ):
        raise ValueError("JudgePack and WorkResultBundle identify different task forms")
    if judge_pack.confidentiality != result.confidentiality:
        raise ValueError("JudgePack and WorkResultBundle have different confidentiality states")
    if judge_pack.execution_pack_sha256 != result.execution_pack_sha256:
        raise ValueError("JudgePack does not bind to the result's ExecutionPack")
    validate_judge_stack(judge_pack, judge_stack)

    expected = {item.criterion_id: item for item in judge_pack.semantic_criteria}
    supplied = {item.criterion_id: item for item in criteria}
    if len(supplied) != len(criteria):
        raise ValueError("Duplicate criterion judgments are not allowed")
    missing = set(expected) - set(supplied)
    unknown = set(supplied) - set(expected)
    if missing or unknown:
        raise ValueError(
            f"Criterion judgment mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )

    fatal_semantic_failure = False
    for criterion_id, judgment in supplied.items():
        spec = expected[criterion_id]
        _validate_criterion_judgment(
            criterion_id,
            judgment,
            min_score=spec.min_score,
            max_score=spec.max_score,
            acceptance_threshold=spec.acceptance_threshold,
        )
        unknown_reason_codes = set(judgment.reason_codes) - set(spec.reason_codes)
        if unknown_reason_codes:
            raise ValueError(
                f"Criterion {criterion_id!r} uses undeclared reason codes: "
                f"{sorted(unknown_reason_codes)}"
            )
        if spec.fatal_below_threshold and judgment.verdict == JudgmentVerdict.REJECT:
            fatal_semantic_failure = True

    verdicts = {item.verdict for item in criteria}
    if JudgmentVerdict.REJECT in verdicts:
        overall = JudgmentVerdict.REJECT
    elif JudgmentVerdict.INSUFFICIENT_BASIS in verdicts:
        overall = JudgmentVerdict.INSUFFICIENT_BASIS
    elif JudgmentVerdict.INDETERMINATE in verdicts:
        overall = JudgmentVerdict.INDETERMINATE
    else:
        overall = JudgmentVerdict.ACCEPT

    return JudgmentBundle(
        task_id=result.task_id,
        family_id=result.family_id,
        form_id=result.form_id,
        instrument=result.instrument,
        attempt_id=result.run_condition.attempt_id,
        work_result_sha256=sha256_hex(result),
        judge_pack_sha256=sha256_hex(judge_pack),
        acceptance_policy=judge_pack.acceptance_policy,
        judge_stack=judge_stack,
        criteria=criteria,
        overall_verdict=overall,
        fatal_semantic_failure=fatal_semantic_failure,
        panel_disagreement=panel_disagreement or {},
        raw_judgments=raw_judgments or [],
    )


def import_judgment_file(
    *,
    path: Path,
    judge_pack: JudgePack,
    result: WorkResultBundle,
    judge_stack: JudgeStack,
) -> JudgmentBundle:
    submission = JudgmentSubmission.model_validate(load_data(path))
    return build_judgment_bundle(
        judge_pack=judge_pack,
        result=result,
        judge_stack=judge_stack,
        criteria=submission.criteria,
        raw_judgments=submission.raw_judgments,
        panel_disagreement=submission.panel_disagreement,
    )


def qualify_judge(
    *,
    qualification_pack: QualificationPack,
    qualification_run: QualificationRun,
) -> QualificationReceipt:
    observations = {item.case_id: item for item in qualification_run.observations}
    if len(observations) != len(qualification_run.observations):
        raise ValueError("Duplicate qualification observations are not allowed")

    case_ids = {case.case_id for case in qualification_pack.cases}
    if len(case_ids) != len(qualification_pack.cases):
        raise ValueError("Duplicate qualification case IDs are not allowed")
    declared_criteria = set(qualification_pack.criterion_ids)
    unknown_case_criteria = {
        case.criterion_id
        for case in qualification_pack.cases
        if case.criterion_id not in declared_criteria
    }
    if unknown_case_criteria:
        raise ValueError(
            f"Qualification cases reference undeclared criteria: {sorted(unknown_case_criteria)}"
        )
    if set(observations) != case_ids:
        raise ValueError(
            "Qualification observations do not match cases; "
            f"missing={sorted(case_ids - set(observations))}, "
            f"unknown={sorted(set(observations) - case_ids)}"
        )

    correct = 0
    injection_cases = 0
    injection_failures = 0
    by_pair: dict[str, list[tuple[str, float | None]]] = defaultdict(list)
    for case in qualification_pack.cases:
        observation = observations[case.case_id]
        if observation.verdict == case.expected_verdict:
            correct += 1
        if case.injection_sentinel:
            injection_cases += 1
            if observation.verdict != case.expected_verdict:
                injection_failures += 1
        if case.pair_id:
            by_pair[case.pair_id].append((case.expected_score_relation, observation.score))

    anchor_accuracy = correct / len(qualification_pack.cases) if qualification_pack.cases else 0.0
    discriminated = 0
    pair_count = 0
    for pair in by_pair.values():
        if len(pair) != 2 or any(score is None for _, score in pair):
            continue
        pair_count += 1
        relation_a, score_a = pair[0]
        relation_b, score_b = pair[1]
        assert score_a is not None and score_b is not None
        if relation_a == "higher" and relation_b == "lower" and score_a > score_b:
            discriminated += 1
        elif relation_b == "higher" and relation_a == "lower" and score_b > score_a:
            discriminated += 1
        elif relation_a == relation_b == "equal" and score_a == score_b:
            discriminated += 1
    mutant_discrimination = discriminated / pair_count if pair_count else 0.0

    eligible = (
        qualification_pack.criterion_ids
        if anchor_accuracy >= qualification_pack.minimum_anchor_accuracy
        and mutant_discrimination >= qualification_pack.minimum_mutant_discrimination
        else []
    )
    injection_failure_rate = injection_failures / injection_cases if injection_cases else None
    judge_stack = qualification_run.judge_stack
    configuration_sha256 = judge_configuration_digest(judge_stack)
    qualification_identity = {
        "pack": qualification_pack,
        "judge_configuration_sha256": configuration_sha256,
        "observations": qualification_run.observations,
    }
    return QualificationReceipt(
        qualification_id=f"qualification:{sha256_hex(qualification_identity)[:16]}",
        qualification_pack_sha256=sha256_hex(qualification_pack),
        judge_stack_id=judge_stack.judge_stack_id,
        judge_configuration_sha256=configuration_sha256,
        eligible_criteria=eligible,
        anchor_accuracy=anchor_accuracy,
        mutant_discrimination=mutant_discrimination,
        prompt_injection_failure_rate=injection_failure_rate,
        notes=[] if eligible else ["Judge did not meet the qualification thresholds."],
    )
