# ADR 0001: Python-first implementation

- **Status:** accepted
- **Date:** 2026-10-04

## Context

The first instrument must integrate Resolve scripting, media tools, subprocess-based agent harnesses, model and judge adapters, fixture authoring, and rapidly changing protocol contracts. The principal early risk is an incorrect measurement model, not runtime throughput.

## Decision

Implement the first complete system in Python 3.11+ with Pydantic contracts and checked-in JSON Schemas.

Use ports-and-adapters boundaries so stable performance-sensitive components can later move to Rust or Go without changing the evidence protocol.

## Consequences

- Faster iteration around Resolve and media tooling.
- One executable package for compiler, runner, verifier, judge import, analysis, and CLI.
- Schema contracts remain language-neutral.
- Python code is production-quality prototype code, not disposable pseudocode.
- A future port requires measured need and compatibility tests against frozen evidence artifacts.
