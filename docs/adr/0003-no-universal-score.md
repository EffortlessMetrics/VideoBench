# ADR 0003: No universal composite score

- **Status:** accepted
- **Date:** 2026-10-04

## Context

Operation correctness, editorial quality, revision preservation, reliability, token use, dollar cost, latency, and human work are not interchangeable. Arbitrary weights would create a precise-looking number that users could not interpret.

## Decision

Publish vectors and one headline metric per instrument where justified. Do not combine the entire suite into one weighted VideoBench total.

Use conjunctive acceptance gates for fatal obligations. Report quality conditional on valid completion and economics as cost to accepted work.

## Consequences

- Results are less convenient for one-dimensional ranking.
- Failure modes and product trade-offs remain visible.
- Alternative decision-makers may apply their own explicit score views to immutable evidence.
