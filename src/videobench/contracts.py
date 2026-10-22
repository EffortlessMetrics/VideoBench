"""Versioned domain contracts for VideoBench.

The contracts encode information boundaries. Candidate-facing execution artifacts are
separate from verifier-facing and judge-facing artifacts by construction.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from videobench.types import (
    ArtifactValidity,
    CheckSeverity,
    CheckStatus,
    ComparabilityStatus,
    Confidentiality,
    Instrument,
    JudgmentStatus,
    JudgmentVerdict,
    OperatorPolicy,
    OutcomeStatus,
    ProvenanceStatus,
    RecoveryPolicy,
    StrictModel,
    SurfaceKind,
    utc_now,
)


class MediaType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    PROJECT = "project"
    TIMELINE = "timeline"
    TRANSCRIPT = "transcript"
    CAPTION = "caption"
    DATA = "data"
    OTHER = "other"


class CheckType(str, Enum):
    ARTIFACT_EXISTS = "artifact_exists"
    ARTIFACT_COUNT_AT_LEAST = "artifact_count_at_least"
    FILE_SHA256_EQUALS = "file_sha256_equals"
    TEXT_CONTAINS = "text_contains"
    JSON_PATH_EQUALS = "json_path_equals"
    JSON_PATH_IN = "json_path_in"
    JSON_PATH_AT_LEAST = "json_path_at_least"
    JSON_PATH_AT_MOST = "json_path_at_most"
    MEDIA_PROPERTY_EQUALS = "media_property_equals"


class AssetSpec(StrictModel):
    asset_id: str
    path: str
    media_type: MediaType
    role: str
    sha256: str | None = None
    public_eligible: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeliverableSpec(StrictModel):
    deliverable_id: str
    path: str
    media_type: MediaType
    required: bool = True
    editable: bool = False
    description: str


class OutputContract(StrictModel):
    deliverables: list[DeliverableSpec]
    requirements: list[str] = Field(default_factory=list)
    protected_invariants: list[str] = Field(default_factory=list)
    prohibited_shortcuts: list[str] = Field(default_factory=list)


class ObjectiveCheckSpec(StrictModel):
    check_id: str
    check_type: CheckType
    description: str
    severity: CheckSeverity = CheckSeverity.FATAL
    artifact_path: str | None = None
    json_path: str | None = None
    expected: Any = None
    reason_code: str

    @model_validator(mode="after")
    def validate_check_shape(self) -> ObjectiveCheckSpec:
        path_checks = {
            CheckType.ARTIFACT_EXISTS,
            CheckType.FILE_SHA256_EQUALS,
            CheckType.TEXT_CONTAINS,
            CheckType.JSON_PATH_EQUALS,
            CheckType.JSON_PATH_IN,
            CheckType.JSON_PATH_AT_LEAST,
            CheckType.JSON_PATH_AT_MOST,
            CheckType.MEDIA_PROPERTY_EQUALS,
        }
        if self.check_type in path_checks and not self.artifact_path:
            raise ValueError(f"{self.check_type.value} requires artifact_path")
        json_checks = {
            CheckType.JSON_PATH_EQUALS,
            CheckType.JSON_PATH_IN,
            CheckType.JSON_PATH_AT_LEAST,
            CheckType.JSON_PATH_AT_MOST,
            CheckType.MEDIA_PROPERTY_EQUALS,
        }
        if self.check_type in json_checks and not self.json_path:
            raise ValueError(f"{self.check_type.value} requires json_path")
        return self


class EvidenceRequirement(StrictModel):
    evidence_id: str
    description: str
    artifact_paths: list[str] = Field(default_factory=list)
    needs_continuous_video: bool = False
    needs_audio: bool = False
    needs_source_context: bool = False
    needs_project_state: bool = False


class SemanticCriterion(StrictModel):
    criterion_id: str
    description: str
    min_score: float = 0.0
    max_score: float = 5.0
    acceptance_threshold: float = 3.0
    fatal_below_threshold: bool = False
    evidence_requirements: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scale(self) -> SemanticCriterion:
        if self.min_score >= self.max_score:
            raise ValueError("min_score must be less than max_score")
        if not self.min_score <= self.acceptance_threshold <= self.max_score:
            raise ValueError("acceptance_threshold must be within the criterion scale")
        return self


class AcceptancePolicy(StrictModel):
    require_valid_artifact: bool = True
    require_all_fatal_checks: bool = True
    require_semantic_acceptance: bool = True
    reject_on_fatal_semantic_failure: bool = True


class MutantRef(StrictModel):
    mutant_id: str
    description: str
    changed_dimension: str
    expected_relation: Literal["better", "worse", "equivalent", "unjudgeable"]
    artifact_ref: str


class TaskSource(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    title: str
    instrument: Instrument
    brief: str
    assets: list[AssetSpec]
    output_contract: OutputContract
    public_constraints: list[str] = Field(default_factory=list)
    hidden_obligations: list[str] = Field(default_factory=list)
    objective_checks: list[ObjectiveCheckSpec]
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)
    semantic_criteria: list[SemanticCriterion] = Field(default_factory=list)
    acceptable_variation: list[str] = Field(default_factory=list)
    prohibited_outcomes: list[str] = Field(default_factory=list)
    mutants: list[MutantRef] = Field(default_factory=list)
    acceptance_policy: AcceptancePolicy = Field(default_factory=AcceptancePolicy)
    confidentiality: Confidentiality = Confidentiality.PUBLIC
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionPack(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    title: str
    instrument: Instrument
    brief: str
    assets: list[AssetSpec]
    output_contract: OutputContract
    public_constraints: list[str]
    confidentiality: Confidentiality = Confidentiality.PUBLIC
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerifierPack(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    instrument: Instrument
    execution_pack_sha256: str
    hidden_obligations: list[str]
    objective_checks: list[ObjectiveCheckSpec]
    acceptance_policy: AcceptancePolicy
    confidentiality: Confidentiality = Confidentiality.PUBLIC


class JudgeEvidenceTransform(StrictModel):
    transform_id: str
    description: str
    video_proxy: dict[str, Any] = Field(default_factory=dict)
    audio_policy: dict[str, Any] = Field(default_factory=dict)
    frame_sampling: dict[str, Any] = Field(default_factory=dict)
    chunking: dict[str, Any] = Field(default_factory=dict)
    transcript_policy: dict[str, Any] = Field(default_factory=dict)
    source_context_policy: dict[str, Any] = Field(default_factory=dict)
    known_blind_spots: list[str] = Field(default_factory=list)


class JudgePack(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    instrument: Instrument
    execution_pack_sha256: str
    evidence_requirements: list[EvidenceRequirement]
    semantic_criteria: list[SemanticCriterion]
    acceptable_variation: list[str]
    prohibited_outcomes: list[str]
    mutants: list[MutantRef]
    acceptance_policy: AcceptancePolicy
    confidentiality: Confidentiality = Confidentiality.PUBLIC
    required_transform_capabilities: list[str] = Field(default_factory=list)


class FormManifest(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    instrument: Instrument
    source_sha256: str
    execution_pack_sha256: str
    verifier_pack_sha256: str
    judge_pack_sha256: str
    compiler_version: str


class SurfaceProfile(StrictModel):
    observation_surface: SurfaceKind
    action_surface: SurfaceKind
    media_analysis_surface: SurfaceKind = SurfaceKind.NONE
    verification_access: SurfaceKind = SurfaceKind.NONE
    tool_granularity: str = "unspecified"
    allowed_external_tools: list[str] = Field(default_factory=list)
    network_policy: str = "declared"


class ModelIdentity(StrictModel):
    provider: str
    model: str
    snapshot: str | None = None
    product_surface: str | None = None


class HarnessPolicy(StrictModel):
    harness: str
    version: str | None = None
    prompt_policy: str = "default"
    context_policy: str = "default"
    memory_policy: str = "none"
    orchestration_policy: str = "single_agent"
    scaffold_hash: str | None = None


class ResourceEnvelope(StrictModel):
    max_wall_seconds: float | None = Field(default=None, ge=0.0)
    max_model_calls: int | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    max_candidate_cost_usd: float | None = Field(default=None, ge=0.0)


class ResolveEnvironment(StrictModel):
    operating_system: str
    resolve_version: str
    resolve_edition: str = "unknown"
    machine_id: str = "unknown"
    gpu: str | None = None
    display_profile: str | None = None
    color_management: str | None = None
    plugins: list[str] = Field(default_factory=list)
    fonts: list[str] = Field(default_factory=list)
    codecs: list[str] = Field(default_factory=list)
    environment_digest: str | None = None


class RunStack(StrictModel):
    stack_id: str
    system: ModelIdentity
    surface: SurfaceProfile
    harness: HarnessPolicy
    resource_envelope: ResourceEnvelope = Field(default_factory=ResourceEnvelope)
    operator_policy: OperatorPolicy = OperatorPolicy.AUTONOMOUS
    environment: ResolveEnvironment
    known_unknowns: list[str] = Field(default_factory=list)


class RunCondition(StrictModel):
    attempt_id: str
    clean_state_id: str
    seed: int | None = None
    recovery_policy: RecoveryPolicy = RecoveryPolicy.NONE
    started_at: datetime = Field(default_factory=utc_now)
    tags: list[str] = Field(default_factory=list)


class RunEvent(StrictModel):
    sequence: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)
    event_type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class UsageRecord(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    image_units: float = Field(default=0.0, ge=0.0)
    video_units: float = Field(default=0.0, ge=0.0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    compaction_events: int = Field(default=0, ge=0)
    model_retries: int = Field(default=0, ge=0)
    transport_retries: int = Field(default=0, ge=0)
    wall_seconds: float = Field(default=0.0, ge=0.0)
    active_agent_seconds: float = Field(default=0.0, ge=0.0)
    resolve_processing_seconds: float = Field(default=0.0, ge=0.0)
    render_seconds: float = Field(default=0.0, ge=0.0)
    human_interventions: int = Field(default=0, ge=0)
    human_seconds: float = Field(default=0.0, ge=0.0)
    actual_candidate_cost_usd: float | None = Field(default=None, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceArtifact(StrictModel):
    artifact_id: str
    path: str
    media_type: MediaType
    sha256: str
    size_bytes: int = Field(ge=0)
    semantic_sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkResultBundle(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    instrument: Instrument
    execution_pack_sha256: str
    confidentiality: Confidentiality = Confidentiality.PUBLIC
    run_stack: RunStack
    run_condition: RunCondition
    outcome: OutcomeStatus
    events: list[RunEvent]
    artifacts: list[EvidenceArtifact]
    usage: UsageRecord
    stdout: str = ""
    stderr: str = ""
    known_missing_evidence: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_journal_and_artifacts(self) -> WorkResultBundle:
        sequences = [event.sequence for event in self.events]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("RunEvent sequence values must be unique and increasing")
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("EvidenceArtifact paths must be unique within a result")
        return self


class CheckResult(StrictModel):
    check_id: str
    status: CheckStatus
    severity: CheckSeverity
    reason_code: str
    description: str
    expected: Any = None
    actual: Any = None
    evidence_paths: list[str] = Field(default_factory=list)


class VerificationBundle(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    instrument: Instrument
    attempt_id: str
    work_result_sha256: str
    verifier_pack_sha256: str
    acceptance_policy: AcceptancePolicy
    hard_contract_pass: bool
    artifact_validity: ArtifactValidity
    results: list[CheckResult]
    fatal_failures: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class JudgeIdentity(StrictModel):
    provider: str
    model: str
    snapshot: str | None = None
    prompt_version: str


class QualificationReceipt(StrictModel):
    qualification_id: str
    qualification_pack_sha256: str
    judge_stack_id: str
    judge_configuration_sha256: str
    eligible_criteria: list[str]
    anchor_accuracy: float = Field(ge=0.0, le=1.0)
    mutant_discrimination: float = Field(ge=0.0, le=1.0)
    order_bias_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    prompt_injection_failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    valid_from: datetime = Field(default_factory=utc_now)
    valid_until: datetime | None = None
    notes: list[str] = Field(default_factory=list)


class JudgeStack(StrictModel):
    judge_stack_id: str
    judges: list[JudgeIdentity] = Field(min_length=1)
    evidence_transform: JudgeEvidenceTransform
    panel_policy: str
    qualification_receipts: list[QualificationReceipt] = Field(default_factory=list)
    known_unknowns: list[str] = Field(default_factory=list)


class CriterionJudgment(StrictModel):
    criterion_id: str
    verdict: JudgmentVerdict
    score: float | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str
    candidate_time_ranges: list[str] = Field(default_factory=list)
    source_time_ranges: list[str] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)


class JudgmentSubmission(StrictModel):
    """Portable untrusted input submitted by a manual or external judge adapter."""

    criteria: list[CriterionJudgment]
    panel_disagreement: dict[str, Any] = Field(default_factory=dict)
    raw_judgments: list[dict[str, Any]] = Field(default_factory=list)


class JudgmentBundle(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    instrument: Instrument
    attempt_id: str
    work_result_sha256: str
    judge_pack_sha256: str
    acceptance_policy: AcceptancePolicy
    judge_stack: JudgeStack
    criteria: list[CriterionJudgment]
    overall_verdict: JudgmentVerdict
    fatal_semantic_failure: bool = False
    panel_disagreement: dict[str, Any] = Field(default_factory=dict)
    raw_judgments: list[dict[str, Any]] = Field(default_factory=list)


class TokenPricing(StrictModel):
    input_per_million_usd: float = Field(default=0.0, ge=0.0)
    cached_input_per_million_usd: float = Field(default=0.0, ge=0.0)
    cache_write_per_million_usd: float = Field(default=0.0, ge=0.0)
    reasoning_per_million_usd: float = Field(default=0.0, ge=0.0)
    output_per_million_usd: float = Field(default=0.0, ge=0.0)
    image_unit_usd: float = Field(default=0.0, ge=0.0)
    video_unit_usd: float = Field(default=0.0, ge=0.0)
    per_call_usd: float = Field(default=0.0, ge=0.0)


class PricingPolicy(StrictModel):
    policy_id: str
    effective_date: str
    currency: str = "USD"
    provider: str
    model: str
    pricing: TokenPricing
    source_note: str


class ScoringPolicy(StrictModel):
    policy_id: str
    semantic_aggregation: Literal["all_thresholds", "mean_threshold"] = "all_thresholds"
    mean_acceptance_threshold: float = 3.0


class TrustReceipt(StrictModel):
    provenance: ProvenanceStatus = ProvenanceStatus.SELF_SUBMITTED
    judgment_status: JudgmentStatus = JudgmentStatus.UNJUDGED
    artifact_validity: ArtifactValidity = ArtifactValidity.NOT_PROVEN
    comparability: ComparabilityStatus = ComparabilityStatus.VALID_NON_COMPARABLE
    confidentiality: Confidentiality = Confidentiality.PUBLIC
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_claim_basis(self) -> TrustReceipt:
        needs_basis = (
            self.provenance != ProvenanceStatus.SELF_SUBMITTED
            or self.comparability != ComparabilityStatus.VALID_NON_COMPARABLE
            or self.judgment_status == JudgmentStatus.HUMAN_ADJUDICATED
        )
        if needs_basis and not self.evidence_refs:
            raise ValueError(
                "Elevated provenance, comparability, or human-adjudication claims require "
                "evidence_refs"
            )
        return self


class ScoreView(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    instrument: Instrument
    execution_pack_sha256: str
    attempt_id: str
    stack_id: str
    work_result_sha256: str
    verification_sha256: str
    judgment_sha256: str | None = None
    scoring_policy_sha256: str
    pricing_policy_sha256: str
    accepted_work: bool
    artifact_valid: bool
    hard_contract_pass: bool
    semantic_acceptance: bool | None
    criterion_scores: dict[str, float | None]
    criterion_verdicts: dict[str, JudgmentVerdict]
    reason_codes: list[str]
    candidate_metered_cost_usd: float | None
    candidate_list_equivalent_cost_usd: float = Field(ge=0.0)
    judge_cost_usd: float | None = Field(default=None, ge=0.0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    wall_seconds: float = Field(ge=0.0)
    human_seconds: float = Field(ge=0.0)
    trust: TrustReceipt
    scoring_policy_id: str
    pricing_policy_id: str


class TreatmentSpec(StrictModel):
    factor: str
    control: str
    treatment: str
    hold_fixed: list[str]
    permitted_claim: str
    excluded_claims: list[str] = Field(default_factory=list)


class StudyFormRef(StrictModel):
    task_id: str
    family_id: str
    form_id: str
    execution_pack_sha256: str


class StudySpec(StrictModel):
    study_id: str
    title: str
    instrument: Instrument
    forms: list[StudyFormRef] = Field(min_length=1)
    stack_ids: list[str] = Field(min_length=1)
    attempts_per_form: int = Field(ge=1)
    treatment: TreatmentSpec | None = None
    scoring_policy_id: str
    pricing_policy_id: str
    analysis_policy: dict[str, Any] = Field(default_factory=dict)
    preregistered_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_study_identity(self) -> StudySpec:
        form_keys = [
            (item.task_id, item.family_id, item.form_id, item.execution_pack_sha256)
            for item in self.forms
        ]
        if len(form_keys) != len(set(form_keys)):
            raise ValueError("StudySpec form references must be unique")
        if len(self.stack_ids) != len(set(self.stack_ids)):
            raise ValueError("StudySpec stack IDs must be unique")
        return self


class StackSummary(StrictModel):
    stack_id: str
    attempts: int
    families: int
    accepted_work_rate: float
    family_macro_acceptance: float
    mean_list_equivalent_cost_usd: float
    mean_wall_seconds: float
    mean_human_seconds: float
    indeterminate_rate: float


class StudySummary(StrictModel):
    study_id: str
    summaries: list[StackSummary]
    notes: list[str] = Field(default_factory=list)


class QualificationCase(StrictModel):
    case_id: str
    criterion_id: str
    expected_verdict: JudgmentVerdict
    expected_score_relation: Literal["higher", "lower", "equal", "not_applicable"] = (
        "not_applicable"
    )
    pair_id: str | None = None
    injection_sentinel: bool = False


class QualificationPack(StrictModel):
    qualification_pack_id: str
    criterion_ids: list[str]
    cases: list[QualificationCase]
    minimum_anchor_accuracy: float = Field(default=0.9, ge=0.0, le=1.0)
    minimum_mutant_discrimination: float = Field(default=0.9, ge=0.0, le=1.0)


class QualificationObservation(StrictModel):
    case_id: str
    verdict: JudgmentVerdict
    score: float | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class QualificationRun(StrictModel):
    judge_stack: JudgeStack
    observations: list[QualificationObservation]
