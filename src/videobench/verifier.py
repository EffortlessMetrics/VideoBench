"""Independent deterministic verification of candidate artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videobench.canonical import path_sha256, resolve_under_root, sha256_hex
from videobench.contracts import (
    CheckResult,
    ObjectiveCheckSpec,
    VerificationBundle,
    VerifierPack,
    WorkResultBundle,
)
from videobench.types import ArtifactValidity, CheckSeverity, CheckStatus


def _resolve_json_path(value: Any, path: str) -> Any:
    current = value
    for token in path.split("."):
        if token == "":
            continue
        if isinstance(current, list):
            try:
                index = int(token)
            except ValueError as error:
                raise KeyError(f"Expected a list index at {token!r}") from error
            current = current[index]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(f"Cannot resolve {token!r} through {type(current).__name__}")
    return current


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _result(
    check: ObjectiveCheckSpec,
    status: CheckStatus,
    *,
    actual: Any = None,
    expected: Any = None,
    evidence_paths: list[str] | None = None,
    description: str | None = None,
) -> CheckResult:
    return CheckResult(
        check_id=check.check_id,
        status=status,
        severity=check.severity,
        reason_code=check.reason_code,
        description=description or check.description,
        expected=check.expected if expected is None else expected,
        actual=actual,
        evidence_paths=evidence_paths
        or ([] if check.artifact_path is None else [check.artifact_path]),
    )


def _checked_path(artifact_root: Path, relative: str | None) -> Path | None:
    if relative is None:
        return None
    return resolve_under_root(artifact_root, relative)


def evaluate_check(check: ObjectiveCheckSpec, artifact_root: Path) -> CheckResult:
    """Evaluate one declarative check against captured output files."""

    try:
        if artifact_root.is_symlink() or not artifact_root.is_dir():
            raise ValueError(f"Artifact root must be a real directory: {artifact_root}")
        path = _checked_path(artifact_root, check.artifact_path)

        if check.check_type.value == "artifact_exists":
            exists = bool(path and path.exists() and not path.is_symlink())
            return _result(check, CheckStatus.PASS if exists else CheckStatus.FAIL, actual=exists)

        if check.check_type.value == "artifact_count_at_least":
            count = 0
            for item in artifact_root.rglob("*"):
                if item.is_symlink():
                    raise ValueError(f"Symbolic links are not valid evidence: {item}")
                if item.is_file():
                    count += 1
            expected = int(check.expected)
            return _result(
                check,
                CheckStatus.PASS if count >= expected else CheckStatus.FAIL,
                actual=count,
                expected=expected,
                evidence_paths=[],
            )

        if path is None or not path.exists() or path.is_symlink():
            return _result(
                check,
                CheckStatus.NOT_OBSERVABLE,
                actual="artifact missing",
                description=f"{check.description} Required artifact is unavailable.",
            )

        if check.check_type.value == "file_sha256_equals":
            actual = path_sha256(path)
            return _result(
                check,
                CheckStatus.PASS if actual == check.expected else CheckStatus.FAIL,
                actual=actual,
            )

        if not path.is_file():
            return _result(
                check,
                CheckStatus.NOT_OBSERVABLE,
                actual="expected a regular file",
                description=f"{check.description} The declared evidence path is not a file.",
            )

        if check.check_type.value == "text_contains":
            text = path.read_text(encoding="utf-8")
            expected = str(check.expected)
            return _result(
                check,
                CheckStatus.PASS if expected in text else CheckStatus.FAIL,
                actual=expected in text,
            )

        if (
            check.check_type.value.startswith("json_path_")
            or check.check_type.value == "media_property_equals"
        ):
            value = _read_json(path)
            actual = _resolve_json_path(value, check.json_path or "")
            if check.check_type.value in {"json_path_equals", "media_property_equals"}:
                passed = actual == check.expected
            elif check.check_type.value == "json_path_in":
                passed = actual in check.expected
            elif check.check_type.value == "json_path_at_least":
                passed = actual >= check.expected
            elif check.check_type.value == "json_path_at_most":
                passed = actual <= check.expected
            else:
                raise ValueError(f"Unsupported JSON check type: {check.check_type.value}")
            return _result(check, CheckStatus.PASS if passed else CheckStatus.FAIL, actual=actual)

        return _result(
            check,
            CheckStatus.INSTRUMENT_FAILURE,
            actual=f"unsupported check type {check.check_type.value}",
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as error:
        return _result(
            check,
            CheckStatus.INSTRUMENT_FAILURE,
            actual=f"{type(error).__name__}: {error}",
            description=f"{check.description} The verifier could not establish the result.",
        )


def verify_capture_integrity(
    result: WorkResultBundle, artifact_root: Path
) -> tuple[ArtifactValidity, list[CheckResult]]:
    """Verify that captured artifacts still exist and match their recorded hashes."""

    checks: list[CheckResult] = []
    valid = True
    for artifact in result.artifacts:
        check = ObjectiveCheckSpec(
            check_id=f"capture-integrity:{artifact.artifact_id}",
            check_type="file_sha256_equals",
            artifact_path=artifact.path,
            expected=artifact.sha256,
            severity=CheckSeverity.FATAL,
            description="Captured artifact bytes must match the run receipt.",
            reason_code="capture_integrity_mismatch",
        )
        evaluated = evaluate_check(check, artifact_root)
        if evaluated.status != CheckStatus.PASS:
            valid = False
        checks.append(evaluated)
    if not result.artifacts:
        valid = False
        checks.append(
            CheckResult(
                check_id="capture-integrity:no-artifacts",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.FATAL,
                reason_code="no_artifacts_captured",
                description="The candidate run produced no captured artifacts.",
                expected="at least one artifact",
                actual=0,
            )
        )
    return (ArtifactValidity.VALID if valid else ArtifactValidity.INVALID), checks


def verify_result(
    *,
    verifier_pack: VerifierPack,
    result: WorkResultBundle,
    artifact_root: Path,
) -> VerificationBundle:
    if (
        verifier_pack.task_id != result.task_id
        or verifier_pack.family_id != result.family_id
        or verifier_pack.form_id != result.form_id
        or verifier_pack.instrument != result.instrument
    ):
        raise ValueError("VerifierPack and WorkResultBundle identify different task forms")
    if verifier_pack.confidentiality != result.confidentiality:
        raise ValueError("VerifierPack and WorkResultBundle have different confidentiality states")
    if verifier_pack.execution_pack_sha256 != result.execution_pack_sha256:
        raise ValueError("VerifierPack does not bind to the result's ExecutionPack")

    artifact_validity, integrity_results = verify_capture_integrity(result, artifact_root)
    results = integrity_results + [
        evaluate_check(check, artifact_root) for check in verifier_pack.objective_checks
    ]

    fatal_failures = [
        item.check_id
        for item in results
        if item.severity == CheckSeverity.FATAL and item.status != CheckStatus.PASS
    ]
    reason_codes = sorted(
        {item.reason_code for item in results if item.status != CheckStatus.PASS}
    )

    return VerificationBundle(
        task_id=result.task_id,
        family_id=result.family_id,
        form_id=result.form_id,
        instrument=result.instrument,
        attempt_id=result.run_condition.attempt_id,
        work_result_sha256=sha256_hex(result),
        verifier_pack_sha256=sha256_hex(verifier_pack),
        acceptance_policy=verifier_pack.acceptance_policy,
        hard_contract_pass=not fatal_failures,
        artifact_validity=artifact_validity,
        results=results,
        fatal_failures=fatal_failures,
        reason_codes=reason_codes,
    )
