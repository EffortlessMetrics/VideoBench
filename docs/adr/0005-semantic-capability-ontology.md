# ADR 0005: Semantic capability ontology

- **Status:** accepted
- **Date:** 2026-10-04

## Context

Resolve scripting, MCP implementations, GUI agents, and future native assistants expose different method and tool taxonomies. Benchmarking raw method names would bind the instrument to one implementation and overweight APIs with many accessors.

## Decision

Define benchmark capabilities in terms of editing work and observable terminal state. Map implementation methods to those semantic capabilities for audit coverage.

## Consequences

- One capability form can be attempted through MCP, direct scripting, GUI, or hybrids.
- Method coverage remains useful to maintainers without becoming the score.
- The capability registry requires review when Resolve behavior changes.
