# ADR 0002: Evidence DAG and three compiled views

- **Status:** accepted
- **Date:** 2026-10-04

## Context

A linear run-and-score service would let candidate execution, hidden verification, judging, and reporting contaminate one another. It would also make old evidence difficult to rejudge or reprice.

## Decision

Treat VideoBench as an evidence compiler and DAG.

Compile each TaskSource into separate `ExecutionPack`, `VerifierPack`, and `JudgePack` artifacts plus a `FormManifest`. Candidate execution produces a `WorkResultBundle`. Verification and judgment consume that bundle independently. Scoring and reports are versioned projections.

## Consequences

- Candidate systems cannot inspect hidden expected state through normal protocol types.
- The same run may be independently reverified and rejudged.
- New prices and score policies do not alter historical usage or judgments.
- Artifact count increases, but every boundary becomes reviewable and hashable.
