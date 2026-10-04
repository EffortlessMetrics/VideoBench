"""Shared wire types and status enums.

These types are intentionally small. Domain logic belongs in the compiler, runner,
verifier, judge, and analysis modules rather than in a generic core namespace.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Base model for durable protocol artifacts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)


class Instrument(str, Enum):
    SURFACE_CONFORMANCE = "surface_conformance"
    EXECUTION_CORE = "execution_core"
    EDITORIAL_CORE = "editorial_core"
    PROJECT_FIELD = "project_field"
    REVISION_RECOVERY = "revision_recovery"
    JUDGE_QUALIFICATION = "judge_qualification"


class SurfaceKind(str, Enum):
    NONE = "none"
    MCP_COMPOUND = "mcp_compound"
    MCP_GRANULAR = "mcp_granular"
    RESOLVE_SCRIPTING = "resolve_scripting"
    GUI = "gui"
    COMMAND = "command"
    MANUAL = "manual"
    HYBRID = "hybrid"


class OperatorPolicy(str, Enum):
    AUTONOMOUS = "autonomous"
    SCRIPTED_COLLABORATION = "scripted_collaboration"
    EXPERT_OPERATED = "expert_operated"


class RecoveryPolicy(str, Enum):
    NONE = "none"
    SCRIPTED = "scripted"
    ADAPTIVE = "adaptive"


class OutcomeStatus(str, Enum):
    PASS = "pass"
    FAIL_CANDIDATE = "fail_candidate"
    UNSUPPORTED_SURFACE = "unsupported_surface"
    ENVIRONMENT_BLOCKED = "environment_blocked"
    TOOL_FAILURE = "tool_failure"
    PROTOCOL_INVALID = "protocol_invalid"
    VERIFIER_FAILURE = "verifier_failure"
    NOT_OBSERVABLE = "not_observable"
    NOT_PROVEN = "not_proven"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMED_OUT = "timed_out"
    HUMAN_ABORT = "human_abort"


class CheckSeverity(str, Enum):
    FATAL = "fatal"
    MAJOR = "major"
    ADVISORY = "advisory"


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_OBSERVABLE = "not_observable"
    INSTRUMENT_FAILURE = "instrument_failure"


class JudgmentVerdict(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    INDETERMINATE = "indeterminate"
    INSUFFICIENT_BASIS = "insufficient_basis"


class ProvenanceStatus(str, Enum):
    SELF_SUBMITTED = "self_submitted"
    PEER_REPRODUCED = "peer_reproduced"
    OFFICIAL_REPRODUCED = "official_reproduced"
    OFFICIAL_HOSTED = "official_hosted"
    ATTESTED_ENVIRONMENT = "attested_environment"


class JudgmentStatus(str, Enum):
    UNJUDGED = "unjudged"
    SELF_JUDGED = "self_judged"
    QUALIFIED_PANEL_JUDGED = "qualified_panel_judged"
    HUMAN_ADJUDICATED = "human_adjudicated"


class ArtifactValidity(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    CONTESTED = "contested"
    INSTRUMENT_FAILURE = "instrument_failure"
    NOT_PROVEN = "not_proven"


class ComparabilityStatus(str, Enum):
    DIRECTLY_COMPARABLE = "directly_comparable"
    DIAGNOSTICALLY_COMPARABLE = "diagnostically_comparable"
    VALID_NON_COMPARABLE = "valid_non_comparable"


class Confidentiality(str, Enum):
    PUBLIC = "public"
    CONTROLLED = "controlled"
    PRIVATE_CANARY = "private_canary"
    RETIRED_AUDIT = "retired_audit"


class ArtifactEnvelope(StrictModel):
    """Immutable envelope around a protocol payload.

    ``payload_sha256`` covers the canonical payload only. This keeps an artifact identity
    stable when transport metadata such as ``created_at`` changes.
    """

    schema_version: str = SCHEMA_VERSION
    kind: str
    artifact_id: str
    created_at: datetime = Field(default_factory=utc_now)
    producer: str = "videobench"
    payload_sha256: str
    payload: dict[str, Any]
