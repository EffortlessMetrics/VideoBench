# Agent operating contract

VideoBench uses a repo-native, evidence-first development style.

## Read the construct first

Before changing task, scoring, judging, or protocol behavior, read:

- `docs/CONSTRUCT.md`
- `docs/INSTRUMENTS.md`
- `docs/PROTOCOL.md`
- `docs/TASK_AUTHORING.md`
- `docs/JUDGING.md`
- `docs/STATISTICS.md`
- `docs/TRUST.md`

Do not broaden one instrument into generic video quality. Do not collapse several instruments into one total.

## Preserve the evaluated object

Results belong to a declared RunStack. Do not silently attribute a surface, harness, memory, environment, or operator effect to the model name.

Keep observation and action surfaces separate. Keep autonomous, scripted-collaboration, and expert-operated conditions separate.

## Protect information boundaries

- Candidates receive only the `ExecutionPack`.
- `VerifierPack` and `JudgePack` are compiler outputs, never hand-edited run inputs.
- The runner must not import verifier or judge behavior.
- Candidate success telemetry is diagnostic, not authoritative.
- Model output, terminal-state verification, judgment, score, study analysis, and report remain separate artifacts.
- Raw evidence is immutable. Rejudging, reweighting, repricing, and rerunning are different operations.

## Protect creative validity

- A reference cut is an anchor, not the only valid answer.
- Hard obligations must be observable.
- Semantic criteria must name the evidence required to judge them.
- Every critical criterion should have a controlled mutant.
- A judge is eligible only for demonstrated criteria and evidence transforms.
- `insufficient_basis` is a valid result.

## Ontology gate

Do not add a top-level concept because it sounds useful.

A new construct should normally have:

```text
one real or professionally defensible task family
one control or acceptable alternative
one controlled mutant requiring the distinction
one observable consequence or judge evidence contract
```

Prefer a module inside an existing package until an independent protocol or information boundary earns another package.

## Development loop

1. inspect the construct and current contracts;
2. state the evidence-producing transformation;
3. implement the smallest coherent vertical slice;
4. add known-good, known-bad, and boundary tests;
5. regenerate schemas;
6. review leakage, provenance, validity, comparability, and public claims;
7. leave durable receipts.

## Verification

During focused work:

```bash
python -m pytest tests/path_or_test.py
python -m ruff check src tests
python -m mypy src/videobench
```

Before integration:

```bash
python scripts/check.py
```

Do not lower a gate merely because new boundary code reduced coverage. Exercise the boundary or explicitly justify exclusion.
