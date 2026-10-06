# VideoBench

**VideoBench is an evidence-first instrument suite for agentic professional video editing.**

It evaluates whether a declared editing stack can transform frozen source and project state into an accepted, editable deliverable under a bounded work contract—and how control surface, instruction trajectory, resource envelope, and operator policy change that result.

The evaluated object is the full **RunStack**, not a model name:

```text
model + harness + observation surface + action surface
+ tool/scaffold policy + context/memory policy
+ resource envelope + Resolve environment + operator policy
```

VideoBench does not collapse operation, editorial judgment, revision, reliability, and economics into one score. Those constructs share a receipted protocol and remain separate instruments.

> **Status:** usable public-alpha foundation. The repository ships a complete synthetic vertical instrument, generic command/manual execution, a first-party OpenAI-compatible provider and function-tool adapter, independent verification, judge qualification and import, versioned pricing and scoring, family-level aggregation, JSON Schemas, and a read-only DaVinci Resolve state probe. It does not yet ship a professionally reviewed media pack or an official comparative model result.

`VideoBench` is the repository's working public name. The Python distribution is named
`videobench-workbench` so this alpha does not claim the already-occupied `videobench`
package name.

## What is working now

- Compile one authored task into blind `ExecutionPack`, `VerifierPack`, and `JudgePack` views.
- Run any agent, MCP wrapper, script, or GUI harness through a command adapter—or import an external product session manually.
- Run Responses- or Chat Completions-compatible model endpoints through a receipted function-tool harness with explicit retries, budgets, usage evidence, and request-trace policy.
- Capture immutable work results, raw usage, event journals, artifact hashes, semantic JSON digests, and explicit upstream evidence links.
- Verify terminal state independently of the candidate tool's success claims.
- Qualify judges against known anchors and controlled mutants, bound to the exact panel and evidence-transform configuration.
- Import source-aware semantic judgments with criterion-level reasons and evidence references.
- Gate acceptance on artifact validity, hard contract compliance, and semantic acceptance.
- Rejudge, reweight, reprice, and re-report without rerunning the candidate.
- Aggregate only the exact frozen forms named by a study, then macro-average by task family rather than pretending generated forms are independent discoveries.
- Capture a read-only snapshot of the current Resolve project when the Resolve scripting API is available.

## Instruments

| Instrument | Main question |
|---|---|
| **Surface Conformance** | Can a control surface produce and persist the required Resolve state? |
| **Agentic Execution Core** | Can a configured agent complete bounded editing operations through that surface? |
| **Editorial Decision Core** | Can it make a defensible selection, sequencing, trim, b-roll, or mix decision? |
| **Project / Field** | Can the full system produce accepted, editable finished work? |
| **Revision / Recovery** | Can it change the requested work while preserving what was already right? |
| **Judge Qualification** | Can the measurement system recognize the relevant successes and failures? |

Economics is an analysis layer across candidate instruments. It is not a creative-quality score.

## Quick proof

Python 3.11 or newer is required.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"

videobench demo --root . --out .videobench/demo
```

The demo:

1. validates the source assets;
2. compiles candidate, verifier, and judge views;
3. qualifies a frozen judge against anchors and mutants;
4. materializes known-good and known-bad candidate artifacts;
5. independently verifies both results;
6. imports criterion-level judgments;
7. applies versioned scoring and pricing policies;
8. proves `mock-good` is accepted and `mock-bad` is rejected;
9. validates the exact frozen `StudySpec` and emits its family-level summary;
10. emits complete evidence bundles and Markdown reports.

Expected final line:

```text
instrument valid mock-good accepted; mock-bad rejected
```

Run the full verification chain:

```bash
python scripts/check.py
```

## Real run shape

Compile a task:

```bash
videobench compile examples/interview-cut/task.yaml \
  --out .videobench/forms/interview-cut
```

Run an external candidate command. The command receives the execution-pack, workspace, output, attempt, and stack paths through `VIDEOBENCH_*` environment variables:

```bash
videobench run-command \
  --execution-pack .videobench/forms/interview-cut/execution-pack.json \
  --run-stack path/to/run-stack.yaml \
  --run-condition path/to/run-condition.yaml \
  --workspace .videobench/work/attempt-001 \
  --artifact-root .videobench/work/attempt-001/output \
  --out .videobench/runs/attempt-001.json \
  -- python path/to/your_agent_adapter.py
```

The artifact directory must be absent or empty at start. VideoBench rejects stale output
rather than silently mixing evidence from two attempts.

Run a model endpoint directly through the first-party provider adapter:

```bash
videobench run-openai-compatible \
  --execution-pack .videobench/forms/interview-cut/execution-pack.json \
  --run-stack path/to/run-stack.yaml \
  --run-condition path/to/run-condition.yaml \
  --adapter-config examples/provider-adapters/openai-responses.yaml \
  --asset-root examples/interview-cut \
  --workspace .videobench/work/attempt-001 \
  --artifact-root .videobench/work/attempt-001/output \
  --out .videobench/runs/attempt-001.json
```

Credentials and extra sensitive headers come from environment variables. Provider-metered
usage remains unknown when the endpoint does not report it; VideoBench never converts a
missing receipt into zero cost. See [Provider adapters](docs/PROVIDER_ADAPTERS.md).

A ChatGPT, Claude, Codex, Resolve GUI, or other product session can instead be captured after the work is complete:

```bash
videobench capture \
  --execution-pack .videobench/forms/interview-cut/execution-pack.json \
  --run-stack path/to/run-stack.yaml \
  --run-condition path/to/run-condition.yaml \
  --artifact-root path/to/result-artifacts \
  --usage path/to/usage.json \
  --out .videobench/runs/attempt-001.json
```

Then verify, judge, and score through separate commands. See [Running](docs/RUNNING.md).

## Evidence graph

```text
TaskSource
   |
   v
TaskCompiler
   +--> ExecutionPack ----+
   +--> VerifierPack      |
   +--> JudgePack         |
   +--> FormManifest      |
                           v
RunStack + RunCondition + ExecutionPack
                           |
                           v
                    RunEventJournal
                           |
                           v
                    WorkResultBundle
                      /           \
                     v             v
        VerificationBundle    JudgmentBundle (when required)
                     \             /
                      v           v
                  versioned ScoreView
                           |
                           v
                     Report / study
```

Candidate execution cannot import verifier or judge contracts. Verifier and judge packs bind to the exact candidate-facing ExecutionPack digest and instrument. Tool-reported success is diagnostic evidence, never the terminal-state oracle. Reports are projections over immutable evidence.

## Repository layout

```text
contracts/schemas/          checked-in JSON Schemas
src/videobench/             Python package and CLI
examples/interview-cut/     complete public development form
examples/provider-adapters/ provider transport/evidence examples
tests/                       protocol and adapter tests
docs/                        construct, protocol, operations, and ADRs
```

## Design commitments

- **Accepted work, not any output.** Hard contract failure cannot be averaged away by polish.
- **RunStack, not model label.** Surface, harness, memory, tool and operator policy remain part of the result.
- **Work graph, not click script.** Tasks declare obligations and dependencies; implementations may use MCP, scripting, GUI, or hybrids.
- **Independent terminal-state verification.** A candidate cannot grade its own success.
- **Source-aware judgment.** Judge eligibility is limited by the evidence transform it actually received.
- **Receipted judge authority.** Qualification cannot be reused after changing the panel, prompt identity, evidence transform, or panel policy.
- **No universal total.** Each instrument may expose a headline metric; the suite does not manufacture one arbitrary weighted score.
- **Families are the independent unit.** Repeated forms and attempts are modeled as correlated evidence.
- **Raw economics first.** Tokens, list-equivalent cost, cash spend, quota economics, latency, and human work stay distinct.
- **Frozen forms never mutate.** Corrections produce errata and new releases.

## Documentation

- [Construct](docs/CONSTRUCT.md)
- [Instruments](docs/INSTRUMENTS.md)
- [Protocol and artifact graph](docs/PROTOCOL.md)
- [Task authoring](docs/TASK_AUTHORING.md)
- [Running and integration](docs/RUNNING.md)
- [Provider and agent-harness adapters](docs/PROVIDER_ADAPTERS.md)
- [Judging and judge qualification](docs/JUDGING.md)
- [Resolve and control surfaces](docs/RESOLVE.md)
- [Economics](docs/ECONOMICS.md)
- [Statistical design](docs/STATISTICS.md)
- [Trust, provenance, and rights](docs/TRUST.md)
- [Roadmap](docs/ROADMAP.md)
- [Architecture decisions](docs/adr/)

## Name and package boundary

`VideoBench` is the current repository and project name. The Python distribution is deliberately named `videobench-workbench` because `videobench` is already occupied in the Python ecosystem and the public identity remains provisional. The installed command and import package are both `videobench`.

## License

VideoBench is licensed under the GNU Affero General Public License, version 3 only (`AGPL-3.0-only`). See [`LICENSE`](LICENSE).

Source media, fonts, plugins, proprietary Resolve components, model outputs, and contributed benchmark packs may carry separate rights and must declare them in their provenance manifests.
