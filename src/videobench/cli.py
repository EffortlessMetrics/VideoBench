"""VideoBench command-line interface."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from videobench import __version__
from videobench.adapters.media import ffprobe
from videobench.adapters.resolve import ResolveUnavailable, capture_resolve_snapshot
from videobench.analysis import render_score_markdown, score_result, summarize_study
from videobench.compiler import compile_task_file, validate_task_source
from videobench.contracts import (
    ExecutionPack,
    JudgePack,
    JudgeStack,
    JudgmentBundle,
    PricingPolicy,
    QualificationPack,
    QualificationReceipt,
    QualificationRun,
    RunCondition,
    RunStack,
    ScoreView,
    ScoringPolicy,
    StudySpec,
    TaskSource,
    TrustReceipt,
    UsageRecord,
    VerificationBundle,
    VerifierPack,
    WorkResultBundle,
)
from videobench.io import load_model, payload_as, write_envelope, write_json
from videobench.judge import import_judgment_file, qualify_judge
from videobench.runner import capture_manual_result, run_command, run_mock_candidate
from videobench.schemas import export_schemas
from videobench.types import OutcomeStatus
from videobench.verifier import verify_result

app = typer.Typer(
    name="videobench",
    help="Evidence-first evaluation instruments for agentic professional video editing.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Print the VideoBench package version."""

    console.print(__version__)


@app.command("validate-task")
def validate_task(
    task_path: Annotated[Path, typer.Argument(exists=True, readable=True)],
    verify_assets: Annotated[bool, typer.Option("--verify-assets/--no-verify-assets")] = True,
) -> None:
    """Validate a task source and its local asset hashes."""

    task = load_model(task_path, TaskSource)
    validate_task_source(task, task_path.parent if verify_assets else None)
    console.print(f"[green]valid[/green] {task.task_id} ({task.family_id}/{task.form_id})")


@app.command("compile")
def compile_command(
    task_path: Annotated[Path, typer.Argument(exists=True, readable=True)],
    output_dir: Annotated[Path, typer.Option("--out", "-o")],
    verify_assets: Annotated[bool, typer.Option("--verify-assets/--no-verify-assets")] = True,
) -> None:
    """Compile a task into separate execution, verifier, and judge artifacts."""

    paths = compile_task_file(task_path, output_dir, verify_assets=verify_assets)
    table = Table(title="Compiled task form")
    table.add_column("Artifact")
    table.add_column("Path")
    for name, path in paths.__dict__.items():
        table.add_row(name, str(path))
    console.print(table)


@app.command("capture")
def capture_command(
    execution_pack_path: Annotated[Path, typer.Option("--execution-pack", exists=True)],
    run_stack_path: Annotated[Path, typer.Option("--run-stack", exists=True)],
    run_condition_path: Annotated[Path, typer.Option("--run-condition", exists=True)],
    artifact_root: Annotated[Path, typer.Option("--artifact-root", exists=True, file_okay=False)],
    output_path: Annotated[Path, typer.Option("--out", "-o")],
    usage_path: Annotated[Path | None, typer.Option("--usage", exists=True)] = None,
    outcome: Annotated[OutcomeStatus, typer.Option("--outcome")] = OutcomeStatus.PASS,
) -> None:
    """Capture an externally produced edit into a WorkResultBundle."""

    execution = payload_as(execution_pack_path, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(run_stack_path, RunStack)
    condition = load_model(run_condition_path, RunCondition)
    usage = load_model(usage_path, UsageRecord) if usage_path else UsageRecord()
    result = capture_manual_result(
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        output_dir=artifact_root,
        usage=usage,
        outcome=outcome,
    )
    write_envelope(output_path, "work_result_bundle", result)
    console.print(f"[green]captured[/green] {len(result.artifacts)} artifacts")


@app.command(
    "run-command",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_command_cli(
    ctx: typer.Context,
    execution_pack_path: Annotated[Path, typer.Option("--execution-pack", exists=True)],
    run_stack_path: Annotated[Path, typer.Option("--run-stack", exists=True)],
    run_condition_path: Annotated[Path, typer.Option("--run-condition", exists=True)],
    workspace: Annotated[Path, typer.Option("--workspace")],
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
    output_path: Annotated[Path, typer.Option("--out", "-o")],
    usage_path: Annotated[Path | None, typer.Option("--usage")] = None,
) -> None:
    """Run a candidate command after ``--`` and capture its outputs."""

    command = list(ctx.args)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise typer.BadParameter("Provide a candidate command after --")
    execution = payload_as(execution_pack_path, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(run_stack_path, RunStack)
    condition = load_model(run_condition_path, RunCondition)
    result = run_command(
        execution_pack_path=execution_pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        command=command,
        workspace=workspace,
        output_dir=artifact_root,
        usage_path=usage_path,
    )
    write_envelope(output_path, "work_result_bundle", result)
    console.print(f"[bold]{result.outcome.value}[/bold] {len(result.artifacts)} captured artifacts")


@app.command("verify")
def verify_command(
    verifier_pack_path: Annotated[Path, typer.Option("--verifier-pack", exists=True)],
    result_path: Annotated[Path, typer.Option("--result", exists=True)],
    artifact_root: Annotated[Path, typer.Option("--artifact-root", exists=True, file_okay=False)],
    output_path: Annotated[Path, typer.Option("--out", "-o")],
) -> None:
    """Independently verify a captured result."""

    verifier = payload_as(verifier_pack_path, VerifierPack, expected_kind="verifier_pack")
    result = payload_as(result_path, WorkResultBundle, expected_kind="work_result_bundle")
    bundle = verify_result(verifier_pack=verifier, result=result, artifact_root=artifact_root)
    write_envelope(output_path, "verification_bundle", bundle)
    style = "green" if bundle.hard_contract_pass else "red"
    console.print(f"[{style}]hard_contract_pass={bundle.hard_contract_pass}[/{style}]")


@app.command("qualify-judge")
def qualify_judge_command(
    qualification_pack_path: Annotated[Path, typer.Option("--pack", exists=True)],
    qualification_run_path: Annotated[Path, typer.Option("--run", exists=True)],
    output_path: Annotated[Path, typer.Option("--out", "-o")],
) -> None:
    """Produce a judge qualification receipt from known anchors and mutants."""

    pack = load_model(qualification_pack_path, QualificationPack)
    run = load_model(qualification_run_path, QualificationRun)
    receipt = qualify_judge(qualification_pack=pack, qualification_run=run)
    write_envelope(output_path, "qualification_receipt", receipt)
    console.print(
        f"anchor_accuracy={receipt.anchor_accuracy:.3f} "
        f"mutant_discrimination={receipt.mutant_discrimination:.3f} "
        f"eligible={bool(receipt.eligible_criteria)}"
    )


@app.command("judge-import")
def judge_import_command(
    judge_pack_path: Annotated[Path, typer.Option("--judge-pack", exists=True)],
    result_path: Annotated[Path, typer.Option("--result", exists=True)],
    judge_stack_path: Annotated[Path, typer.Option("--judge-stack", exists=True)],
    judgment_path: Annotated[Path, typer.Option("--judgment", exists=True)],
    output_path: Annotated[Path, typer.Option("--out", "-o")],
    qualification_receipt_paths: Annotated[
        list[Path] | None,
        typer.Option("--qualification-receipt", exists=True),
    ] = None,
) -> None:
    """Validate and import a manual or external judge result."""

    judge_pack = payload_as(judge_pack_path, JudgePack, expected_kind="judge_pack")
    result = payload_as(result_path, WorkResultBundle, expected_kind="work_result_bundle")
    judge_stack = load_model(judge_stack_path, JudgeStack)
    for receipt_path in qualification_receipt_paths or []:
        receipt = payload_as(
            receipt_path,
            QualificationReceipt,
            expected_kind="qualification_receipt",
        )
        judge_stack.qualification_receipts.append(receipt)
    judgment = import_judgment_file(
        path=judgment_path,
        judge_pack=judge_pack,
        result=result,
        judge_stack=judge_stack,
    )
    write_envelope(output_path, "judgment_bundle", judgment)
    console.print(f"overall_verdict={judgment.overall_verdict.value}")


@app.command("score")
def score_command(
    result_path: Annotated[Path, typer.Option("--result", exists=True)],
    verification_path: Annotated[Path, typer.Option("--verification", exists=True)],
    scoring_policy_path: Annotated[Path, typer.Option("--scoring-policy", exists=True)],
    pricing_policy_path: Annotated[Path, typer.Option("--pricing-policy", exists=True)],
    output_path: Annotated[Path, typer.Option("--out", "-o")],
    judgment_path: Annotated[Path | None, typer.Option("--judgment", exists=True)] = None,
    report_path: Annotated[Path | None, typer.Option("--report")] = None,
    judge_cost_usd: Annotated[float | None, typer.Option("--judge-cost-usd")] = None,
    trust_path: Annotated[Path | None, typer.Option("--trust", exists=True)] = None,
) -> None:
    """Project immutable evidence into a versioned score view."""

    result = payload_as(result_path, WorkResultBundle, expected_kind="work_result_bundle")
    verification = payload_as(
        verification_path, VerificationBundle, expected_kind="verification_bundle"
    )
    judgment = (
        payload_as(judgment_path, JudgmentBundle, expected_kind="judgment_bundle")
        if judgment_path
        else None
    )
    scoring = load_model(scoring_policy_path, ScoringPolicy)
    pricing = load_model(pricing_policy_path, PricingPolicy)
    trust = load_model(trust_path, TrustReceipt) if trust_path else None
    score = score_result(
        result=result,
        verification=verification,
        judgment=judgment,
        scoring_policy=scoring,
        pricing_policy=pricing,
        judge_cost_usd=judge_cost_usd,
        trust_receipt=trust,
    )
    write_envelope(output_path, "score_view", score)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_score_markdown(score), encoding="utf-8")
    style = "green" if score.accepted_work else "red"
    console.print(f"[{style}]accepted_work={score.accepted_work}[/{style}]")


@app.command("study-summary")
def study_summary_command(
    study_path: Annotated[Path, typer.Option("--study", exists=True)],
    score_paths: Annotated[list[Path], typer.Argument(exists=True)],
    output_path: Annotated[Path, typer.Option("--out", "-o")],
) -> None:
    """Aggregate attempts at the family level for each RunStack."""

    study = load_model(study_path, StudySpec)
    scores = [payload_as(path, ScoreView, expected_kind="score_view") for path in score_paths]
    summary = summarize_study(study, scores)
    write_envelope(output_path, "study_summary", summary)
    console.print(f"summarized {len(scores)} score views across {len(summary.summaries)} stacks")


@app.command("export-schemas")
def export_schemas_command(
    output_dir: Annotated[Path, typer.Option("--out", "-o")] = Path("contracts/schemas"),
) -> None:
    """Regenerate the checked-in JSON Schema contracts."""

    written = export_schemas(output_dir)
    console.print(f"[green]wrote[/green] {len(written)} schemas to {output_dir}")


@app.command("resolve-snapshot")
def resolve_snapshot_command(
    output_path: Annotated[Path, typer.Option("--out", "-o")],
) -> None:
    """Capture a read-only snapshot of the current Resolve project."""

    try:
        snapshot = capture_resolve_snapshot()
    except ResolveUnavailable as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=2) from error
    write_json(output_path, snapshot)
    console.print(f"[green]wrote[/green] {output_path}")


@app.command("media-probe")
def media_probe_command(
    media_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output_path: Annotated[Path, typer.Option("--out", "-o")],
    executable: Annotated[str, typer.Option("--ffprobe")] = "ffprobe",
) -> None:
    """Capture a deterministic ffprobe JSON receipt for a media artifact."""

    write_json(output_path, ffprobe(media_path, executable=executable))
    console.print(f"[green]wrote[/green] {output_path}")


@app.command("demo")
def demo_command(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output_dir: Annotated[Path, typer.Option("--out", "-o")] = Path(".videobench/demo"),
) -> None:
    """Run the complete instrument-validation vertical slice."""

    root = root.resolve()
    example = root / "examples" / "interview-cut"
    if not example.is_dir():
        raise typer.BadParameter(
            f"Could not find examples/interview-cut under {root}. Run from the repository root "
            "or pass --root."
        )
    if output_dir.exists():
        shutil.rmtree(output_dir)
    compiled_dir = output_dir / "compiled"
    paths = compile_task_file(example / "task.yaml", compiled_dir, verify_assets=True)
    execution = payload_as(paths.execution_pack, ExecutionPack, expected_kind="execution_pack")
    verifier = payload_as(paths.verifier_pack, VerifierPack, expected_kind="verifier_pack")
    judge_pack = payload_as(paths.judge_pack, JudgePack, expected_kind="judge_pack")
    scoring = load_model(example / "policies" / "scoring.yaml", ScoringPolicy)
    pricing = load_model(example / "policies" / "pricing.yaml", PricingPolicy)

    qualification_pack = load_model(
        example / "policies" / "judge-qualification-pack.yaml", QualificationPack
    )
    qualification_run = load_model(
        example / "policies" / "judge-qualification-run.yaml", QualificationRun
    )
    receipt = qualify_judge(
        qualification_pack=qualification_pack, qualification_run=qualification_run
    )
    write_envelope(output_dir / "qualification-receipt.json", "qualification_receipt", receipt)

    outcomes: list[ScoreView] = []
    for candidate in ("good", "bad"):
        candidate_root = output_dir / "artifacts" / candidate
        stack = load_model(example / "stacks" / f"mock-{candidate}.yaml", RunStack)
        stack.known_unknowns.append("Synthetic artifact set used for instrument validation.")
        judge_stack = load_model(example / "policies" / "judge-stack.yaml", JudgeStack)
        judge_stack.qualification_receipts = [receipt]
        condition = RunCondition(
            attempt_id=f"demo-{candidate}-001",
            clean_state_id="demo-clean-state-v1",
            seed=1,
            tags=["instrument-validation", candidate],
        )
        usage = UsageRecord(
            input_tokens=1000 if candidate == "good" else 1200,
            reasoning_tokens=300 if candidate == "good" else 500,
            output_tokens=200,
            model_calls=1,
            tool_calls=4 if candidate == "good" else 7,
            wall_seconds=2.0 if candidate == "good" else 3.5,
            actual_candidate_cost_usd=0.01 if candidate == "good" else 0.02,
        )
        result = run_mock_candidate(
            execution_pack=execution,
            run_stack=stack,
            run_condition=condition,
            candidate_dir=example / "candidates" / candidate,
            output_dir=candidate_root,
            usage=usage,
        )
        result_path = output_dir / f"work-result-{candidate}.json"
        write_envelope(result_path, "work_result_bundle", result)

        verification = verify_result(
            verifier_pack=verifier, result=result, artifact_root=candidate_root
        )
        verification_path = output_dir / f"verification-{candidate}.json"
        write_envelope(verification_path, "verification_bundle", verification)

        judgment = import_judgment_file(
            path=example / "judgments" / f"{candidate}.yaml",
            judge_pack=judge_pack,
            result=result,
            judge_stack=judge_stack,
        )
        judgment_path = output_dir / f"judgment-{candidate}.json"
        write_envelope(judgment_path, "judgment_bundle", judgment)

        score = score_result(
            result=result,
            verification=verification,
            judgment=judgment,
            scoring_policy=scoring,
            pricing_policy=pricing,
            judge_cost_usd=0.005,
        )
        outcomes.append(score)
        write_envelope(output_dir / f"score-{candidate}.json", "score_view", score)
        (output_dir / f"report-{candidate}.md").write_text(
            render_score_markdown(score), encoding="utf-8"
        )

    study = load_model(example / "study.yaml", StudySpec)
    study_summary = summarize_study(study, outcomes)
    if study_summary.notes:
        raise RuntimeError(
            "Instrument validation study is incomplete or stale: "
            + "; ".join(study_summary.notes)
        )
    write_envelope(output_dir / "study-summary.json", "study_summary", study_summary)

    good = next(item for item in outcomes if item.stack_id == "mock-good")
    bad = next(item for item in outcomes if item.stack_id == "mock-bad")
    if not good.accepted_work or bad.accepted_work:
        raise RuntimeError("Instrument validation failed: mock-good/mock-bad ordering is wrong")
    console.print(
        "[green]instrument valid[/green] mock-good accepted; "
        f"mock-bad rejected; output={output_dir}"
    )


if __name__ == "__main__":
    app()
