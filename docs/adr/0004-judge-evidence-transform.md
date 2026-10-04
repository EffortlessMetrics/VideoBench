# ADR 0004: Judge evidence transform is part of JudgeStack

- **Status:** accepted
- **Date:** 2026-10-04

## Context

A video judge rarely receives raw source and candidate artifacts exactly as produced. Transcoding, chunking, frame sampling, audio omission, transcripts, contact sheets, and project summaries determine which defects are observable.

## Decision

Make `JudgeEvidenceTransform` a first-class component of `JudgeStack` identity. Each semantic criterion declares required evidence capabilities. Judgment import fails when the transform lacks those capabilities.

## Consequences

- A model name alone does not identify a judge result.
- Rejudging under another transform creates a new receipt.
- Judge qualification must use the same transform as candidate judging.
- Evidence blind spots can produce `insufficient_basis` instead of fabricated certainty.
