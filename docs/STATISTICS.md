# Statistical design

## Independent evidence is primarily the family

The hierarchy is:

```text
attempt -> frozen form -> task family -> instrument view -> release view
```

Ten variants of one interview-compression grammar are not ten independent discoveries. They share assets, obligations, editorial structure, and judge behavior.

## Required practices

Confirmatory releases should use:

- a `StudySpec` that names each exact task, family, form, and ExecutionPack digest;
- paired comparisons inside families;
- macro-averaging by family;
- family-clustered bootstrap or hierarchical models;
- repeated attempts for nondeterministic RunStacks;
- separate candidate-run and judge variance;
- confidence intervals;
- predeclared release manifests;
- frozen scoring, pricing, and analysis policies;
- exploratory packs separated from official forms;
- explicit indeterminate and not-observable rates.

The current implementation exposes raw attempt acceptance and family-macro acceptance. More formal uncertainty belongs in the analysis policy once the first real packs establish plausible variance.

## Factor vectors, not one opaque difficulty label

Record raw task factors such as:

```text
source duration
source clip count
candidate take count
speaker and camera count
timeline duration
track count
effect depth
deliverable count
aspect-ratio changes
caption density
dependency depth
instruction ambiguity
revision radius
protected invariants
source-to-output compression ratio
```

A convenient `difficulty = high` label may be derived later. It should not replace the factor evidence.

## One principal treatment per confirmatory study

A study may evaluate a broad real-world stack delta. It should not then claim one hidden factor caused the result.

For a causal study, name:

```text
treatment factor
control level
treatment level
held-fixed factors
permitted claim
excluded claims
```

The `TreatmentSpec` contract records exactly those fields.

## Repeated attempts

Repeated attempts estimate operational reliability rather than demanding bit-for-bit determinism.

Reproducibility means:

> the same frozen experimental condition yields an independently reproducible distribution of observed outcomes.

Every repeat starts from a clean state and receives its own attempt ID, run journal, artifacts, verification, and judgment. Duplicate score views for one attempt are rejected rather than counted twice. Underfilled declared cells remain visible as incomplete study notes.

## Judge variance

Candidate variance and judge variance must not be conflated.

Useful designs include:

- rejudge the same WorkResultBundle with repeated JudgeStack attempts;
- hold evidence transform fixed while changing judge model;
- hold judge model fixed while changing evidence transform;
- compare automated panels with selective professional adjudication;
- preserve criterion-level disagreement.

## First-release claims

With a small number of task families, uncertainty will be wide. The first public report should be framed as instrument validation and an initial empirical surface, not a population-level ranking of all agentic editors.
