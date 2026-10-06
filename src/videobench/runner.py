"""Execution and capture for candidate systems.

The runner sees only an :class:`ExecutionPack`. It never imports verifier or judge
artifacts, and it does not decide whether the produced work is correct.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from videobench.canonical import path_sha256, sha256_hex
from videobench.contracts import (
    EvidenceArtifact,
    ExecutionPack,
    MediaType,
    ResourceEnvelope,
    RunCondition,
    RunEvent,
    RunStack,
    UsageRecord,
    WorkResultBundle,
)
from videobench.io import load_envelope
from videobench.types import OutcomeStatus

if TYPE_CHECKING:
    from videobench.adapters.openai_compatible import HTTPTransport, OpenAICompatibleConfig


_MEDIA_BY_SUFFIX: dict[str, MediaType] = {
    ".mp4": MediaType.VIDEO,
    ".mov": MediaType.VIDEO,
    ".mxf": MediaType.VIDEO,
    ".mkv": MediaType.VIDEO,
    ".wav": MediaType.AUDIO,
    ".aif": MediaType.AUDIO,
    ".aiff": MediaType.AUDIO,
    ".flac": MediaType.AUDIO,
    ".png": MediaType.IMAGE,
    ".jpg": MediaType.IMAGE,
    ".jpeg": MediaType.IMAGE,
    ".webp": MediaType.IMAGE,
    ".drp": MediaType.PROJECT,
    ".dra": MediaType.PROJECT,
    ".drt": MediaType.TIMELINE,
    ".xml": MediaType.TIMELINE,
    ".edl": MediaType.TIMELINE,
    ".srt": MediaType.CAPTION,
    ".vtt": MediaType.CAPTION,
    ".json": MediaType.DATA,
    ".yaml": MediaType.DATA,
    ".yml": MediaType.DATA,
    ".txt": MediaType.OTHER,
    ".md": MediaType.OTHER,
}


def infer_media_type(path: Path) -> MediaType:
    return _MEDIA_BY_SUFFIX.get(path.suffix.lower(), MediaType.OTHER)


def _semantic_digest(path: Path) -> str | None:
    if path.suffix.lower() != ".json":
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return sha256_hex(value)


def capture_artifacts(root: Path, *, exclude: Iterable[str] = ()) -> list[EvidenceArtifact]:
    """Capture every regular file below ``root`` in deterministic path order.

    Symbolic links are rejected. Evidence must identify the bytes inside the declared
    output root rather than an external target whose contents can change independently.
    """

    excluded = {Path(item).as_posix() for item in exclude}
    artifacts: list[EvidenceArtifact] = []
    if not root.exists():
        return artifacts
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Artifact root must be a real directory: {root}")

    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"Symbolic links are not valid captured evidence: {item}")
        if not item.is_file():
            continue
        relative = item.relative_to(root).as_posix()
        if relative in excluded:
            continue
        digest = path_sha256(item)
        artifacts.append(
            EvidenceArtifact(
                artifact_id=f"artifact:{digest[:16]}",
                path=relative,
                media_type=infer_media_type(item),
                sha256=digest,
                semantic_sha256=_semantic_digest(item),
                size_bytes=item.stat().st_size,
            )
        )
    return artifacts


def load_usage(path: Path | None) -> UsageRecord:
    if path is None:
        return UsageRecord()
    if not path.exists():
        raise FileNotFoundError(f"Usage receipt was not produced: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    return UsageRecord.model_validate(value)


def _budget_failures(
    envelope: ResourceEnvelope, usage: UsageRecord
) -> tuple[list[dict[str, str | float | int]], list[str]]:
    comparisons: list[tuple[str, float | int | None, float | int | None]] = [
        ("wall_seconds", envelope.max_wall_seconds, usage.wall_seconds),
        ("model_calls", envelope.max_model_calls, usage.model_calls),
        ("tool_calls", envelope.max_tool_calls, usage.tool_calls),
        ("input_tokens", envelope.max_input_tokens, usage.input_tokens),
        ("output_tokens", envelope.max_output_tokens, usage.output_tokens),
    ]
    failures: list[dict[str, str | float | int]] = []
    missing: list[str] = []
    for name, limit, actual in comparisons:
        if limit is None:
            continue
        if actual is None:
            missing.append(f"{name}_not_reported")
        elif actual > limit:
            failures.append({"resource": name, "limit": limit, "actual": actual})
    if envelope.max_candidate_cost_usd is not None:
        if usage.actual_candidate_cost_usd is None:
            missing.append("candidate_cost_not_reported")
        elif usage.actual_candidate_cost_usd > envelope.max_candidate_cost_usd:
            failures.append(
                {
                    "resource": "candidate_cost_usd",
                    "limit": envelope.max_candidate_cost_usd,
                    "actual": usage.actual_candidate_cost_usd,
                }
            )
    return failures, missing


def _apply_resource_envelope(
    *,
    outcome: OutcomeStatus,
    run_stack: RunStack,
    usage: UsageRecord,
    events: list[RunEvent],
) -> tuple[OutcomeStatus, list[str]]:
    failures, missing = _budget_failures(run_stack.resource_envelope, usage)
    if failures:
        events.append(
            RunEvent(
                sequence=(events[-1].sequence + 1 if events else 0),
                event_type="resource_budget_exceeded",
                message="Candidate use exceeded the declared resource envelope.",
                data={"failures": failures},
            )
        )
        if outcome == OutcomeStatus.PASS:
            outcome = OutcomeStatus.BUDGET_EXHAUSTED
    if missing:
        events.append(
            RunEvent(
                sequence=(events[-1].sequence + 1 if events else 0),
                event_type="resource_budget_unverified",
                message=(
                    "A configured resource limit could not be checked because the "
                    "candidate surface did not report the required usage evidence."
                ),
                data={"missing": missing},
            )
        )
        if outcome == OutcomeStatus.PASS:
            outcome = OutcomeStatus.NOT_PROVEN
    return outcome, missing


def _build_result(
    *,
    execution_pack: ExecutionPack,
    run_stack: RunStack,
    run_condition: RunCondition,
    output_dir: Path,
    usage: UsageRecord,
    outcome: OutcomeStatus,
    events: list[RunEvent],
    stdout: str = "",
    stderr: str = "",
    known_missing_evidence: list[str] | None = None,
    notes: list[str] | None = None,
    exclude: Iterable[str] = (),
) -> WorkResultBundle:
    outcome, budget_missing = _apply_resource_envelope(
        outcome=outcome,
        run_stack=run_stack,
        usage=usage,
        events=events,
    )
    missing = list(known_missing_evidence or [])
    missing.extend(item for item in budget_missing if item not in missing)
    return WorkResultBundle(
        task_id=execution_pack.task_id,
        family_id=execution_pack.family_id,
        form_id=execution_pack.form_id,
        instrument=execution_pack.instrument,
        execution_pack_sha256=sha256_hex(execution_pack),
        confidentiality=execution_pack.confidentiality,
        run_stack=run_stack,
        run_condition=run_condition,
        outcome=outcome,
        events=events,
        artifacts=capture_artifacts(output_dir, exclude=exclude),
        usage=usage,
        stdout=stdout,
        stderr=stderr,
        known_missing_evidence=missing,
        notes=notes or [],
    )


def capture_manual_result(
    *,
    execution_pack: ExecutionPack,
    run_stack: RunStack,
    run_condition: RunCondition,
    output_dir: Path,
    usage: UsageRecord | None = None,
    outcome: OutcomeStatus = OutcomeStatus.PASS,
    notes: list[str] | None = None,
) -> WorkResultBundle:
    events = [
        RunEvent(
            sequence=0,
            event_type="manual_capture",
            message="Captured an externally produced candidate result.",
            data={"output_dir": str(output_dir)},
        )
    ]
    return _build_result(
        execution_pack=execution_pack,
        run_stack=run_stack,
        run_condition=run_condition,
        output_dir=output_dir,
        usage=usage or UsageRecord(),
        outcome=outcome,
        events=events,
        notes=notes,
    )


def _text_from_timeout(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _require_empty_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise ValueError(f"Output path must be a real directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise ValueError(f"Output directory must be empty before a command run: {output_dir}")
    else:
        output_dir.mkdir(parents=True)


def run_command(
    *,
    execution_pack_path: Path,
    execution_pack: ExecutionPack,
    run_stack: RunStack,
    run_condition: RunCondition,
    command: Sequence[str],
    workspace: Path,
    output_dir: Path,
    usage_path: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> WorkResultBundle:
    """Run an agent or adapter command and capture its durable outputs.

    The command is executed without a shell. The candidate receives paths through
    environment variables and may write its own detailed event or usage receipts.
    """

    if not command:
        raise ValueError("command must not be empty")
    if not execution_pack_path.is_file():
        raise ValueError(f"ExecutionPack path does not exist: {execution_pack_path}")
    execution_envelope = load_envelope(
        execution_pack_path,
        expected_kind="execution_pack",
    )
    if execution_envelope.payload_sha256 != sha256_hex(execution_pack):
        raise ValueError("ExecutionPack path and in-memory ExecutionPack do not match")
    if usage_path is not None and usage_path.exists():
        raise ValueError(f"Usage path must not exist before a command run: {usage_path}")

    workspace.mkdir(parents=True, exist_ok=True)
    _require_empty_output_dir(output_dir)
    events: list[RunEvent] = [
        RunEvent(
            sequence=0,
            event_type="run_started",
            message="Candidate command started.",
            data={"command": list(command)},
        )
    ]

    reserved_env = {
        "VIDEOBENCH_EXECUTION_PACK",
        "VIDEOBENCH_WORKSPACE",
        "VIDEOBENCH_OUTPUT_DIR",
        "VIDEOBENCH_ATTEMPT_ID",
        "VIDEOBENCH_STACK_ID",
        "VIDEOBENCH_USAGE_PATH",
    }
    overridden = reserved_env.intersection(extra_env or {})
    if overridden:
        raise ValueError(
            f"extra_env may not override VideoBench protocol variables: {sorted(overridden)}"
        )

    env = os.environ.copy()
    env.update(
        {
            "VIDEOBENCH_EXECUTION_PACK": str(execution_pack_path.resolve()),
            "VIDEOBENCH_WORKSPACE": str(workspace.resolve()),
            "VIDEOBENCH_OUTPUT_DIR": str(output_dir.resolve()),
            "VIDEOBENCH_ATTEMPT_ID": run_condition.attempt_id,
            "VIDEOBENCH_STACK_ID": run_stack.stack_id,
        }
    )
    if usage_path is not None:
        env["VIDEOBENCH_USAGE_PATH"] = str(usage_path.resolve())
    if extra_env:
        env.update(extra_env)

    timeout = run_stack.resource_envelope.max_wall_seconds
    start = time.perf_counter()
    stdout = ""
    stderr = ""
    outcome = OutcomeStatus.PASS
    try:
        completed = subprocess.run(
            list(command),
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        if completed.returncode != 0:
            outcome = OutcomeStatus.TOOL_FAILURE
        events.append(
            RunEvent(
                sequence=1,
                event_type="run_finished",
                message="Candidate command finished.",
                data={"returncode": completed.returncode},
            )
        )
    except subprocess.TimeoutExpired as error:
        stdout = _text_from_timeout(error.stdout)
        stderr = _text_from_timeout(error.stderr)
        outcome = OutcomeStatus.TIMED_OUT
        events.append(
            RunEvent(
                sequence=1,
                event_type="run_timed_out",
                message="Candidate command exceeded its declared wall-time budget.",
                data={"timeout_seconds": timeout},
            )
        )
    except OSError as error:
        outcome = OutcomeStatus.TOOL_FAILURE
        stderr = f"{type(error).__name__}: {error}"
        events.append(
            RunEvent(
                sequence=1,
                event_type="run_failed_to_start",
                message="Candidate command could not be started.",
                data={"error": stderr},
            )
        )

    elapsed = time.perf_counter() - start
    known_missing: list[str] = []
    if usage_path is None:
        known_missing.extend(
            [
                "input_tokens_not_reported",
                "output_tokens_not_reported",
                "reasoning_tokens_not_reported",
                "candidate_cost_not_reported",
            ]
        )
    try:
        usage = load_usage(usage_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        usage = UsageRecord()
        outcome = OutcomeStatus.PROTOCOL_INVALID
        known_missing.append("valid_usage_receipt")
        events.append(
            RunEvent(
                sequence=(events[-1].sequence + 1 if events else 0),
                event_type="usage_receipt_invalid",
                message="Candidate usage receipt could not be validated.",
                data={"error": f"{type(error).__name__}: {error}"},
            )
        )
    usage.wall_seconds = elapsed

    excluded: list[str] = []
    if usage_path is not None:
        with contextlib.suppress(ValueError):
            excluded.append(usage_path.resolve().relative_to(output_dir.resolve()).as_posix())

    return _build_result(
        execution_pack=execution_pack,
        run_stack=run_stack,
        run_condition=run_condition,
        output_dir=output_dir,
        usage=usage,
        outcome=outcome,
        events=events,
        stdout=stdout,
        stderr=stderr,
        known_missing_evidence=known_missing,
        exclude=excluded,
    )


def run_openai_compatible(
    *,
    execution_pack_path: Path,
    execution_pack: ExecutionPack,
    run_stack: RunStack,
    run_condition: RunCondition,
    config: OpenAICompatibleConfig,
    asset_root: Path,
    workspace: Path,
    output_dir: Path,
    transport: HTTPTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    cancellation_check: Callable[[], bool] | None = None,
) -> WorkResultBundle:
    """Run the first-party OpenAI-compatible provider/harness adapter."""

    from videobench.adapters.openai_compatible import execute_openai_compatible

    if not execution_pack_path.is_file():
        raise ValueError(f"ExecutionPack path does not exist: {execution_pack_path}")
    execution_envelope = load_envelope(
        execution_pack_path,
        expected_kind="execution_pack",
    )
    if execution_envelope.payload_sha256 != sha256_hex(execution_pack):
        raise ValueError("ExecutionPack path and in-memory ExecutionPack do not match")
    if asset_root.is_symlink() or not asset_root.is_dir():
        raise ValueError(f"Asset root must be a real directory: {asset_root}")
    workspace.mkdir(parents=True, exist_ok=True)
    _require_empty_output_dir(output_dir)
    adapter_result = execute_openai_compatible(
        execution_pack=execution_pack,
        run_stack=run_stack,
        run_condition=run_condition,
        config=config,
        asset_root=asset_root,
        workspace=workspace,
        output_dir=output_dir,
        transport=transport,
        sleep=sleep,
        cancellation_check=cancellation_check,
    )
    return _build_result(
        execution_pack=execution_pack,
        run_stack=run_stack,
        run_condition=run_condition,
        output_dir=output_dir,
        usage=adapter_result.usage,
        outcome=adapter_result.outcome,
        events=adapter_result.events,
        stdout=adapter_result.stdout,
        stderr=adapter_result.stderr,
        known_missing_evidence=adapter_result.known_missing_evidence,
        notes=adapter_result.notes,
    )


def run_mock_candidate(
    *,
    execution_pack: ExecutionPack,
    run_stack: RunStack,
    run_condition: RunCondition,
    candidate_dir: Path,
    output_dir: Path,
    usage: UsageRecord | None = None,
) -> WorkResultBundle:
    """Copy a frozen candidate artifact set into a clean output directory."""

    if candidate_dir.is_symlink() or not candidate_dir.is_dir():
        raise ValueError(f"Candidate directory does not exist or is a symlink: {candidate_dir}")
    for item in candidate_dir.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"Frozen candidate artifacts may not contain symlinks: {item}")
    _require_empty_output_dir(output_dir)
    for item in candidate_dir.iterdir():
        destination = output_dir / item.name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)
    events = [
        RunEvent(
            sequence=0,
            event_type="mock_candidate_materialized",
            message="Materialized a frozen candidate output for instrument validation.",
            data={"candidate_dir": str(candidate_dir)},
        )
    ]
    return _build_result(
        execution_pack=execution_pack,
        run_stack=run_stack,
        run_condition=run_condition,
        output_dir=output_dir,
        usage=usage or UsageRecord(model_calls=1, tool_calls=4, wall_seconds=1.0),
        outcome=OutcomeStatus.PASS,
        events=events,
    )
