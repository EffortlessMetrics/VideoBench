# Running VideoBench

## Install

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate

python -m pip install -e ".[dev]"
```

The package supports Python 3.11–3.13. The repository does not require Resolve for its synthetic instrument-validation demo.

## Verify the repository

```bash
python scripts/check.py
```

The check script runs:

1. schema drift check;
2. Ruff formatting and lint;
3. strict mypy;
4. pytest with branch coverage;
5. the end-to-end demo.

## End-to-end demo

```bash
videobench demo --root . --out .videobench/demo
```

Important outputs:

```text
compiled/execution-pack.json
compiled/verifier-pack.json
compiled/judge-pack.json
compiled/form-manifest.json
qualification-receipt.json
work-result-good.json
verification-good.json
judgment-good.json
score-good.json
report-good.md
... equivalent bad-candidate artifacts
```

## Author and compile a form

Validate source and assets:

```bash
videobench validate-task path/to/task.yaml
```

Compile blind views:

```bash
videobench compile path/to/task.yaml --out .videobench/forms/form-id
```

Compilation fails on duplicate IDs, missing evidence references, absent or hash-mismatched assets, missing semantic criteria under a semantic gate, or exact hidden-obligation leakage into the execution view.

Asset paths must remain below the task directory. Symbolic links are rejected as evidence
because their target can change independently of the frozen form.

## Candidate execution through a command

`run-command` is the first generic adapter. It allows an MCP wrapper, agent harness, direct Resolve script, GUI automation entrypoint, or other executor to participate without adding provider code to VideoBench.

```bash
videobench run-command \
  --execution-pack .videobench/forms/form-id/execution-pack.json \
  --run-stack run-stack.yaml \
  --run-condition run-condition.yaml \
  --workspace .videobench/work/attempt-001 \
  --artifact-root .videobench/work/attempt-001/output \
  --usage .videobench/work/attempt-001/usage.json \
  --out .videobench/runs/attempt-001.json \
  -- python adapter.py
```

The candidate command receives:

```text
VIDEOBENCH_EXECUTION_PACK
VIDEOBENCH_WORKSPACE
VIDEOBENCH_OUTPUT_DIR
VIDEOBENCH_ATTEMPT_ID
VIDEOBENCH_STACK_ID
VIDEOBENCH_USAGE_PATH   when supplied
```

The command runs without a shell. Its exit code, stdout, stderr, wall time, timeout, and output artifacts are receipted.

The artifact root must be absent or empty before the run. This is deliberate: a runner
must not mix stale files from a prior attempt into the new evidence bundle. Symbolic links
inside the artifact tree are rejected.

The declared `ResourceEnvelope` is enforced against reported usage and benchmark wall
time. A command that otherwise succeeds but exceeds a declared limit receives the typed
outcome `budget_exhausted`. When a cost limit exists but the adapter does not report
candidate cost, the result records `candidate_cost_not_reported` as missing evidence
rather than inventing a zero.

### Included command-adapter proof

The repository includes a small candidate adapter that materializes the frozen known-good
artifact set. It is an execution-path proof, not an editing-agent result.

```bash
videobench compile examples/interview-cut/task.yaml \
  --out .videobench/command-proof/compiled

videobench run-command \
  --execution-pack .videobench/command-proof/compiled/execution-pack.json \
  --run-stack examples/interview-cut/stacks/mock-good.yaml \
  --run-condition examples/interview-cut/run-condition.yaml \
  --workspace .videobench/command-proof/workspace \
  --artifact-root .videobench/command-proof/artifacts \
  --usage .videobench/command-proof/usage.json \
  --out .videobench/command-proof/work-result.json \
  -- python /absolute/path/to/VideoBench/examples/interview-cut/adapters/materialize-good.py
```

Use an absolute adapter path because the candidate process runs from the declared
workspace. The adapter writes the same `UsageRecord` shape shown in
`examples/interview-cut/usage.example.json`.

Infrastructure transport retries must be disclosed. Semantic retries and agent self-correction belong in the attempt's usage and event journal; they are never silently removed.

## Candidate execution through a provider endpoint

`run-openai-compatible` is the first first-party model/provider adapter. It supports
Responses- and Chat Completions-compatible JSON over HTTP while preserving the generic
VideoBench evidence contracts.

```bash
videobench run-openai-compatible \
  --execution-pack .videobench/forms/form-id/execution-pack.json \
  --run-stack path/to/run-stack.yaml \
  --run-condition path/to/run-condition.yaml \
  --adapter-config examples/provider-adapters/openai-responses.yaml \
  --asset-root path/to/task-root \
  --workspace .videobench/work/attempt-001 \
  --artifact-root .videobench/work/attempt-001/output \
  --out .videobench/runs/attempt-001.json
```

The model is declared in `RunStack`; the adapter file controls endpoint, authentication
environment, wire style, retry policy, function tools, request evidence, and response
retention. Built-in tools can read declared text assets and write or copy bounded
artifacts. Additional command tools run without a shell and receive JSON on standard
input.

The adapter enforces model-call, tool-call, token, and wall-time limits where the evidence
permits enforcement. Transport retries are explicit and retain their own request, response,
identifier, and usage receipts. Missing provider usage remains `null`; an otherwise
successful attempt becomes `not_proven` when a configured token limit cannot be checked.
List-equivalent pricing also remains unknown when a nonzero-priced total or subset is
unavailable. Reported input and output totals are inclusive; cached input and reasoning
remain separately recorded subsets so a pricing policy can partition rather than
double-price them.

See [Provider and agent-harness adapters](PROVIDER_ADAPTERS.md) for the complete contract,
security boundary, examples, and claim limit.

## Manual product capture

Use manual capture for managed products or expert-operated sessions that are not automated yet:

```bash
videobench capture \
  --execution-pack execution-pack.json \
  --run-stack run-stack.yaml \
  --run-condition run-condition.yaml \
  --artifact-root result-artifacts \
  --usage usage.json \
  --out work-result.json
```

The operator must preserve the exact prompts, model/product identity available at run time, timestamps, project artifacts, renders, tool traces where exposed, and human intervention receipt.

## Independent verification

```bash
videobench verify \
  --verifier-pack verifier-pack.json \
  --result work-result.json \
  --artifact-root result-artifacts \
  --out verification.json
```

Verification first rehashes captured artifacts. A post-run mutation invalidates the evidence before task checks are considered.

For real Resolve work, capture the state after save, close, and clean reopen where the task requires persistent editable state.

## Judge qualification

```bash
videobench qualify-judge \
  --pack judge-qualification-pack.yaml \
  --run judge-qualification-run.yaml \
  --out qualification-receipt.json
```

A qualification receipt authorizes only the criteria demonstrated by the pack. It should be attached to the exact judge model, prompt, evidence transform, and panel policy used for candidate judgments.

The receipt stores a digest of that exact judge configuration. Changing the panel,
evidence transform, panel policy, or disclosed unknowns invalidates the receipt rather
than silently carrying authority forward.

## Judgment import

The initial implementation keeps model-provider judging outside the core. Any human panel, VLM harness, or command adapter may produce the declared YAML/JSON shape.

```bash
videobench judge-import \
  --judge-pack judge-pack.json \
  --result work-result.json \
  --judge-stack judge-stack.yaml \
  --qualification-receipt qualification-receipt.json \
  --judgment judgment.yaml \
  --out judgment.json
```

`--qualification-receipt` may be repeated. Receipts may also be embedded in the
`JudgeStack`; do not supply the same receipt twice.

VideoBench validates evidence-transform capabilities, qualification binding and scope,
criterion coverage, score ranges, verdict/threshold consistency, task identity, and the
exact WorkResult digest before accepting the judgment bundle.

## Score projection

```bash
videobench score \
  --result work-result.json \
  --verification verification.json \
  --judgment judgment.json \
  --scoring-policy scoring.yaml \
  --pricing-policy pricing.yaml \
  --judge-cost-usd 0.25 \
  --out score.json \
  --report report.md
```

The candidate execution cost and judge cost remain separate.

The scorer applies the task's compiled `AcceptancePolicy`; a later scoring policy cannot
turn off artifact, hard-contract, or semantic gates. It also verifies that the
verification and judgment bundles bind to the exact WorkResult.

Surface Conformance and other objective-only forms may omit `--judgment` when their
compiled acceptance policy does not require semantic acceptance:

```bash
videobench score \
  --result work-result.json \
  --verification verification.json \
  --scoring-policy scoring.yaml \
  --pricing-policy pricing.yaml \
  --out score.json
```

By default, a score is self-submitted and `valid_non_comparable`. An independently
established trust receipt can be supplied with `--trust trust.yaml`; it must agree with
the verified artifact validity, result confidentiality, and attached judgment authority.
Elevated provenance, comparability, and human-adjudication claims must name their
external evidence receipts.

## Study summary

```bash
videobench study-summary \
  --study study.yaml \
  --out study-summary.json \
  score-a1.json score-a2.json score-b1.json
```

The study file names exact frozen form identities, including each ExecutionPack digest.
The current summary reports raw attempt acceptance and family-macro acceptance, rejects
duplicate attempts and overfilled cells, and marks underfilled declared cells incomplete.
Confirmatory releases should add family-clustered uncertainty or hierarchical analysis
under a frozen policy.

Scores with another instrument, form digest, stack, scoring policy, or pricing policy are
excluded from the study summary rather than silently aggregated.

## Resolve state snapshot

With Resolve running and scripting available:

```bash
videobench resolve-snapshot --out resolve-state.json
```

Set `RESOLVE_SCRIPT_API` when the scripting module is not discoverable through the standard platform paths.

The probe is read-only. It records missing or failed API calls under `unknowns` rather than converting them into empty success.

## Media probe

```bash
videobench media-probe final.mov --out final.ffprobe.json
```

FFmpeg's `ffprobe` must be installed or supplied with `--ffprobe`.
