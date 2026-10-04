# Protocol and artifact graph

## Three compiled views

An authored `TaskSource` compiles into separate views:

```text
TaskSource
   |
   v
TaskCompiler
   +--> ExecutionPack
   +--> VerifierPack
   +--> JudgePack
   +--> FormManifest
```

### ExecutionPack

Contains only what the candidate may see:

- source references;
- brief;
- public constraints;
- output contract;
- non-secret form metadata.

It does not contain hidden obligations, expected terminal state, controlled-mutant identity, or semantic answer keys.

### VerifierPack

Contains:

- the instrument and exact `ExecutionPack` digest it is allowed to verify;
- hidden obligations;
- declarative deterministic checks;
- check severity;
- diagnostic reason codes;
- hard acceptance policy.

### JudgePack

Contains:

- the instrument and exact `ExecutionPack` digest it is allowed to judge;
- semantic criteria;
- evidence requirements;
- acceptable variation;
- prohibited outcomes;
- known mutant references;
- evidence-transform capabilities required for judgment.

The runner imports no verifier or judge contracts.

## Run identity

```text
ModelIdentity
+ SurfaceProfile
+ HarnessPolicy
+ ResourceEnvelope
+ OperatorPolicy
+ ResolveEnvironment
+ known unknowns
= RunStack
```

The run condition is separate:

```text
attempt ID
clean-state ID
seed
recovery policy
tags
start time
```

This prevents environment and system configuration from being confused with one attempt's treatment or random condition.

## WorkResultBundle

A candidate attempt produces:

```text
RunEventJournal
artifacts and raw hashes
semantic JSON digests
usage receipt
stdout/stderr where applicable
outcome status
known missing evidence
```

The bundle also records the instrument, digest of the exact `ExecutionPack`, and the
form's confidentiality state. Verifier and judge packs independently carry the same
ExecutionPack digest; matching task IDs are not treated as sufficient binding. Output
paths are portable POSIX-style relative paths, root-contained, drive-free, and
symlink-free.

The final render is one artifact. It is not the complete result.

A real Resolve run should retain, as applicable:

- project archive or portable export;
- canonical Resolve state snapshot;
- timeline interchange export;
- final renders;
- stems;
- captions;
- generated graphics;
- GUI screen recording;
- tool traces;
- raw provider usage;
- human-intervention receipt.

## Independent verification

The verifier first confirms that captured artifact bytes still match the run receipt. It then applies the form's deterministic checks.

The current declarative check set supports:

```text
artifact exists
minimum artifact count
file SHA-256 equals
text contains
JSON path equals / membership / minimum / maximum
media property equals through probed JSON
```

New validators should be built-in, reviewed, bounded, and declarative where practical. Initial public packs do not execute arbitrary contributed validator code.

## Judgment

A `JudgmentBundle` records:

- exact JudgeStack;
- criterion verdicts and scores;
- confidence;
- reason codes;
- candidate and source time ranges;
- evidence paths;
- raw panel judgments;
- disagreement.

It also records the exact WorkResult digest, JudgePack digest, task-family-form identity,
and compiled acceptance policy. A judgment cannot be moved onto another attempt merely
because the visible render looks similar.

Semantic judgments do not replace hard checks. Comparative judgment comes after independent obligation checks.

## Score projection

```text
WorkResultBundle
+ VerificationBundle
+ JudgmentBundle when the task requires semantics
+ ScoringPolicy
+ PricingPolicy
= ScoreView
```

The `VerificationBundle` binds to the exact WorkResult and VerifierPack. The ScoreView
retains the instrument and ExecutionPack digest and records digests for the WorkResult,
VerificationBundle, optional JudgmentBundle, ScoringPolicy, and PricingPolicy.

The task's compiled `AcceptancePolicy` owns the gates. `ScoringPolicy` chooses only the
declared semantic aggregation rule; it cannot switch off artifact validity, fatal checks,
or required semantic acceptance.

The evidence does not change when semantic aggregation, judge models, or prices change.
A new policy produces a new projection.

## Artifact envelopes

Every durable protocol file is wrapped in an `ArtifactEnvelope`:

```json
{
  "schema_version": "0.1.0",
  "kind": "work_result_bundle",
  "artifact_id": "work_result_bundle:...",
  "created_at": "...",
  "producer": "videobench",
  "payload_sha256": "...",
  "payload": {}
}
```

`payload_sha256` covers canonical JSON for the payload. Loading an envelope verifies the digest before model validation.

Checked-in JSON Schemas live under `contracts/schemas/` and are regenerated with:

```bash
videobench export-schemas --out contracts/schemas
```

## Typed outcome states

A candidate result may be:

```text
pass
fail_candidate
unsupported_surface
environment_blocked
tool_failure
protocol_invalid
verifier_failure
not_observable
not_proven
budget_exhausted
timed_out
human_abort
```

An unsupported capability can count against the configured product outcome while remaining distinguishable from an agent that had the capability and used it incorrectly.

## Trust is multidimensional

VideoBench keeps separate:

- provenance and attestation;
- judgment status;
- artifact validity;
- comparability;
- confidentiality.

A self-submitted run can be valid. A professionally judged result can still be non-comparable to a run under another environment. One `trusted` boolean would destroy those distinctions.

VideoBench defaults score views to `valid_non_comparable`. Direct comparability is an
affirmative study-level claim established by matched forms, stacks, environments, and
policies—not something inferred because two scores share a schema.
