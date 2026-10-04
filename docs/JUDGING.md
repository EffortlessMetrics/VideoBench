# Judging and qualification

Judging is the largest validity risk in a benchmark of creative work. A frontier video model returning a number is not yet an oracle.

## Deterministic before semantic

The evaluation order is:

```text
artifact integrity
-> hard contract checks
-> atomic semantic criteria
-> preserved panel disagreement
-> versioned scoring policy
-> optional comparative judgment
```

Comparative preference cannot rescue a candidate that failed an independent fatal obligation.

## JudgeStack

```text
JudgeIdentity
+ PromptVersion
+ JudgeEvidenceTransform
+ PanelPolicy
+ QualificationReceipts
+ known unknowns
= JudgeStack
```

A changed model snapshot, prompt, evidence transform, or panel policy produces a different JudgeStack.

Qualification authority is bound to a digest of the exact JudgeStack configuration with
the receipts themselves excluded to avoid circular identity. A receipt generated for one
panel cannot be attached after changing its judges, transform, panel policy, or disclosed
unknowns.

## The evidence transform is part of the judge

A judge may receive:

- original media;
- transcoded proxies;
- temporal chunks;
- sampled frames;
- audio or no audio;
- transcripts;
- contact sheets;
- source-selection maps;
- project-state summaries.

Those transformations determine which defects are observable. They must be frozen and receipted.

The transform records:

```text
input hashes
proxy codec, resolution, bitrate, and frame rate
audio policy
frame-sampling policy
chunk boundaries
transcript policy
source-context policy
project-state inclusion
truncation
known blind spots
```

A model shown one frame per second is not eligible to judge single-frame flashes or exact cut timing. A judge without audio cannot judge the mix. A final-render-only judge cannot establish editability or source lineage.

## Criterion-specific evidence

| Criterion | Minimum useful evidence |
|---|---|
| Export correctness | Media probe and decoded deliverable |
| Caption accuracy | Render, caption file, source transcript |
| Timing and pacing | Continuous temporal video with audio |
| Audio treatment | Faithful audio proxy or original audio |
| Narrative coherence | Complete edit, brief, transcript |
| Source selection | Edit plus source proxies/transcript/timeline map |
| Editability | Project artifact and canonical state |
| Brief adherence | Brief, source context, project and final output as needed |

## Absolute anchors and mutants

A qualification pack should include:

```text
strong reference
acceptable alternative
minimum acceptable result
polished but substantively wrong result
isolated defect mutants
catastrophic failure
prompt-injection sentinels
```

Question variants test the candidate. Controlled output mutants test the measurement system.

## Qualification receipt

The current receipt records:

- qualification pack hash;
- JudgeStack ID and configuration hash;
- eligible criteria;
- anchor accuracy;
- mutant discrimination;
- order or injection rates when measured;
- validity period;
- notes.

The first implementation uses exact expected verdicts and pairwise score relations. Later qualification should add criterion-level calibration, order reversal, identity blinding, compression robustness, and cross-rating.

Receipts carry `valid_from` and optional `valid_until` timestamps. VideoBench rejects
not-yet-valid, expired, foreign-stack, and configuration-mismatched receipts.

## Judgment consistency

For a scored criterion:

- `accept` requires a score at or above the criterion threshold;
- `reject` requires a score below the criterion threshold;
- `indeterminate` and `insufficient_basis` carry no numeric score.

This prevents a polished narrative verdict from contradicting the declared measurement
scale. A criterion marked `fatal_below_threshold` produces an explicit fatal semantic
failure when rejected; the task acceptance policy decides whether that failure is an
absolute gate.

## Do not reward majority agreement alone

Agreement may indicate shared error or herding. Judge quality should be established through hidden anchors, mutant discrimination, calibrated confidence, order-invariant decisions, and useful dissent that survives adjudication.

A valid panel result may be:

```text
accept
reject
indeterminate
insufficient basis
```

Forcing a majority verdict can hide a weak oracle or inadequate evidence.

## Professional-editor review

Human attention is highest-value at:

- task-family legitimacy;
- acceptable-alternative review;
- fatal-defect definition;
- mutant isolation;
- evidence sufficiency;
- disputed high-impact judgments;
- public claim review.

A professional reviewer should not be asked to invent arbitrary percentage weights before the constructs and anchors are valid.

## Injection safety

Source video, captions, on-screen text, spoken audio, candidate logs, and imported judgments are untrusted input.

Judges must not receive environment-changing tool access. Qualification packs should include both visual and spoken attempts to redirect or manipulate the judge.
