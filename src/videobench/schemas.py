"""JSON Schema export for public protocol contracts."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from videobench.contracts import (
    ExecutionPack,
    FormManifest,
    JudgePack,
    JudgeStack,
    JudgmentBundle,
    JudgmentSubmission,
    PricingPolicy,
    QualificationPack,
    QualificationReceipt,
    QualificationRun,
    RunCondition,
    RunStack,
    ScoreView,
    ScoringPolicy,
    StudySpec,
    StudySummary,
    TaskSource,
    TrustReceipt,
    UsageRecord,
    VerificationBundle,
    VerifierPack,
    WorkResultBundle,
)
from videobench.io import write_json

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "task-source": TaskSource,
    "execution-pack": ExecutionPack,
    "verifier-pack": VerifierPack,
    "judge-pack": JudgePack,
    "form-manifest": FormManifest,
    "run-stack": RunStack,
    "run-condition": RunCondition,
    "usage-record": UsageRecord,
    "work-result-bundle": WorkResultBundle,
    "verification-bundle": VerificationBundle,
    "judge-stack": JudgeStack,
    "judgment-submission": JudgmentSubmission,
    "judgment-bundle": JudgmentBundle,
    "qualification-pack": QualificationPack,
    "qualification-run": QualificationRun,
    "qualification-receipt": QualificationReceipt,
    "pricing-policy": PricingPolicy,
    "scoring-policy": ScoringPolicy,
    "score-view": ScoreView,
    "trust-receipt": TrustReceipt,
    "study-spec": StudySpec,
    "study-summary": StudySummary,
}


def export_schemas(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in sorted(SCHEMA_MODELS.items()):
        path = output_dir / f"{name}.schema.json"
        write_json(path, model.model_json_schema())
        written.append(path)
    return written
