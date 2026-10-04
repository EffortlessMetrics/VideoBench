"""Task compilation and information-boundary validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from videobench.canonical import (
    path_sha256,
    resolve_under_root,
    sha256_hex,
    validate_relative_evidence_path,
)
from videobench.contracts import (
    ExecutionPack,
    FormManifest,
    JudgePack,
    TaskSource,
    VerifierPack,
)
from videobench.io import load_model, write_envelope
from videobench.version import __version__


@dataclass(frozen=True)
class CompiledPaths:
    execution_pack: Path
    verifier_pack: Path
    judge_pack: Path
    form_manifest: Path


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _validate_relative_path(label: str, value: str, errors: list[str]) -> None:
    try:
        validate_relative_evidence_path(value)
    except ValueError as error:
        errors.append(f"{label} must be a portable root-contained relative path: {error}")


def validate_task_source(task: TaskSource, base_dir: Path | None = None) -> None:
    """Validate cross-object references and optional source asset hashes."""

    duplicate_sets = {
        "asset IDs": _duplicates(asset.asset_id for asset in task.assets),
        "deliverable IDs": _duplicates(
            item.deliverable_id for item in task.output_contract.deliverables
        ),
        "check IDs": _duplicates(check.check_id for check in task.objective_checks),
        "evidence IDs": _duplicates(item.evidence_id for item in task.evidence_requirements),
        "criterion IDs": _duplicates(item.criterion_id for item in task.semantic_criteria),
        "mutant IDs": _duplicates(item.mutant_id for item in task.mutants),
    }
    errors = [
        f"Duplicate {label}: {sorted(values)}"
        for label, values in duplicate_sets.items()
        if values
    ]

    for asset in task.assets:
        _validate_relative_path(f"Asset {asset.asset_id!r} path", asset.path, errors)
    for deliverable in task.output_contract.deliverables:
        _validate_relative_path(
            f"Deliverable {deliverable.deliverable_id!r} path", deliverable.path, errors
        )
    for check in task.objective_checks:
        if check.artifact_path is not None:
            _validate_relative_path(
                f"Check {check.check_id!r} artifact_path", check.artifact_path, errors
            )
    for requirement in task.evidence_requirements:
        for path in requirement.artifact_paths:
            _validate_relative_path(
                f"Evidence requirement {requirement.evidence_id!r} path", path, errors
            )
    for mutant in task.mutants:
        _validate_relative_path(
            f"Mutant {mutant.mutant_id!r} reference",
            mutant.artifact_ref,
            errors,
        )

    evidence_ids = {item.evidence_id for item in task.evidence_requirements}
    for criterion in task.semantic_criteria:
        missing = set(criterion.evidence_requirements) - evidence_ids
        if missing:
            errors.append(
                f"Criterion {criterion.criterion_id!r} references missing evidence requirements: "
                f"{sorted(missing)}"
            )

    if task.acceptance_policy.require_semantic_acceptance and not task.semantic_criteria:
        errors.append("Acceptance policy requires semantic acceptance but no criteria are declared")

    if base_dir is not None:
        for asset in task.assets:
            try:
                validate_relative_evidence_path(asset.path)
                asset_path = resolve_under_root(base_dir, asset.path)
            except ValueError as error:
                errors.append(f"Asset {asset.asset_id!r} has an invalid path: {error}")
                continue
            if not asset_path.exists():
                errors.append(f"Asset {asset.asset_id!r} does not exist: {asset_path}")
                continue
            if asset.sha256:
                try:
                    actual = path_sha256(asset_path)
                except ValueError as error:
                    errors.append(f"Asset {asset.asset_id!r} is not valid evidence: {error}")
                    continue
                if actual != asset.sha256:
                    errors.append(
                        f"Asset hash mismatch for {asset.asset_id!r}: "
                        f"expected {asset.sha256}, got {actual}"
                    )

    if errors:
        raise ValueError("Task source validation failed:\n- " + "\n- ".join(errors))


def compile_task(task: TaskSource, output_dir: Path) -> CompiledPaths:
    """Compile a task into candidate, verifier, and judge views."""

    validate_task_source(task)

    execution_pack = ExecutionPack(
        task_id=task.task_id,
        family_id=task.family_id,
        form_id=task.form_id,
        title=task.title,
        instrument=task.instrument,
        brief=task.brief,
        assets=task.assets,
        output_contract=task.output_contract,
        public_constraints=task.public_constraints,
        confidentiality=task.confidentiality,
        metadata=task.metadata,
    )
    execution_pack_sha256 = sha256_hex(execution_pack)
    verifier_pack = VerifierPack(
        task_id=task.task_id,
        family_id=task.family_id,
        form_id=task.form_id,
        instrument=task.instrument,
        execution_pack_sha256=execution_pack_sha256,
        hidden_obligations=task.hidden_obligations,
        objective_checks=task.objective_checks,
        acceptance_policy=task.acceptance_policy,
        confidentiality=task.confidentiality,
    )
    judge_pack = JudgePack(
        task_id=task.task_id,
        family_id=task.family_id,
        form_id=task.form_id,
        instrument=task.instrument,
        execution_pack_sha256=execution_pack_sha256,
        evidence_requirements=task.evidence_requirements,
        semantic_criteria=task.semantic_criteria,
        acceptable_variation=task.acceptable_variation,
        prohibited_outcomes=task.prohibited_outcomes,
        mutants=task.mutants,
        acceptance_policy=task.acceptance_policy,
        confidentiality=task.confidentiality,
        required_transform_capabilities=sorted(
            {
                capability
                for requirement in task.evidence_requirements
                for capability, required in {
                    "continuous_video": requirement.needs_continuous_video,
                    "audio": requirement.needs_audio,
                    "source_context": requirement.needs_source_context,
                    "project_state": requirement.needs_project_state,
                }.items()
                if required
            }
        ),
    )

    execution_primitive = execution_pack.model_dump(mode="json")
    execution_text = str(execution_primitive)
    leaked = [item for item in task.hidden_obligations if item and item in execution_text]
    if leaked:
        raise ValueError(
            "ExecutionPack leaks hidden obligations; move shared requirements into the public "
            f"contract or rewrite the hidden oracle: {leaked}"
        )

    manifest = FormManifest(
        task_id=task.task_id,
        family_id=task.family_id,
        form_id=task.form_id,
        instrument=task.instrument,
        source_sha256=sha256_hex(task),
        execution_pack_sha256=execution_pack_sha256,
        verifier_pack_sha256=sha256_hex(verifier_pack),
        judge_pack_sha256=sha256_hex(judge_pack),
        compiler_version=__version__,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = CompiledPaths(
        execution_pack=output_dir / "execution-pack.json",
        verifier_pack=output_dir / "verifier-pack.json",
        judge_pack=output_dir / "judge-pack.json",
        form_manifest=output_dir / "form-manifest.json",
    )
    write_envelope(paths.execution_pack, "execution_pack", execution_pack)
    write_envelope(paths.verifier_pack, "verifier_pack", verifier_pack)
    write_envelope(paths.judge_pack, "judge_pack", judge_pack)
    write_envelope(paths.form_manifest, "form_manifest", manifest)
    return paths


def compile_task_file(
    task_path: Path,
    output_dir: Path,
    *,
    verify_assets: bool = True,
) -> CompiledPaths:
    task = load_model(task_path, TaskSource)
    validate_task_source(task, task_path.parent if verify_assets else None)
    return compile_task(task, output_dir)
