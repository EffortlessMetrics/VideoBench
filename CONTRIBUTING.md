# Contributing

VideoBench accepts implementation changes, adapters, documentation, task-family proposals, controlled mutants, and reproduction receipts.

## Before opening a change

Read `AGENTS.md` and the governing documentation for the surface you are changing.

Task and scoring changes carry a higher evidence burden than ordinary code changes. A new top-level construct normally needs a defensible task family, a control or acceptable alternative, a discriminating mutant, and an observable consequence or evidence contract.

## Development setup

```bash
uv sync --locked --extra dev
uv run --locked --no-sync python scripts/check.py
```

## Pull requests

A pull request should state:

- the construct or protocol boundary affected;
- the evidence-producing change;
- known-good, known-bad, and boundary tests added;
- schema changes;
- fixture, rights, privacy, or claim-boundary effects;
- commands run and their results.

Do not commit proprietary source media, private conversations, secret provider credentials, Resolve databases containing unrelated projects, or model outputs whose redistribution is prohibited.

## Task-family proposals

Use the task-family issue template. Public promotion requires construct, oracle, judge, and rights review. High frontier-model failure is a review signal, not automatic proof of validity.

## Generated contracts

After changing Pydantic protocol models:

```bash
videobench export-schemas --out contracts/schemas
```

`uv run --locked --no-sync python scripts/check.py` rejects schema drift.

The manifest pins uv, Ruff, and ty; `uv.lock` owns resolved dependencies. Update the lock with `uv lock`, then verify `uv lock --check`. The strict mypy check remains a blocking companion until its additional obligations have a proven replacement; ty is required, not advisory.

## Commit style

Use focused commits with concrete subjects, for example:

```text
feat(verifier): add persisted timeline range check
fix(judge): reject transforms without continuous audio
 docs(protocol): separate run and judgment validity
```
