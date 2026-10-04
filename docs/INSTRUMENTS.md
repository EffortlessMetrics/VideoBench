# Instruments

VideoBench is one protocol supporting distinct instruments. Controlled evidence and realistic field evidence are both valuable; combining them into one score would make neither interpretable.

## 1. Surface Conformance

**Object:** control surface or adapter.

**Question:** can the surface produce, report, and persist the required Resolve state?

Typical conditions:

- direct Resolve scripting;
- compound MCP;
- granular MCP;
- offline project manipulation;
- GUI bridge;
- hybrid surface.

Dimensions:

```text
availability
correct terminal state
false-success rate
safe failure
persistence after reopen
idempotence where applicable
reversibility where applicable
error quality
```

Conformance normally avoids an LLM. It qualifies the substrate before failures are attributed to an agent using it.

The ontology is semantic. Raw API or MCP method counts are retained as audit coverage, not weighted as capability value.

## 2. Agentic Execution Core

**Object:** RunStack.

**Question:** can the configured agent complete bounded, objectively verifiable editing work?

Core cases isolate one main mechanic where practical:

- ingest and organization;
- timeline creation and configuration;
- placement and trimming;
- linked audio/video preservation;
- track operations;
- titles and captions;
- retiming;
- audio routing and levels;
- render configuration and execution;
- interchange export.

The principal result is first-attempt hard-contract completion, with typed failure reasons and resource receipts.

## 3. Editorial Decision Core

**Object:** RunStack.

**Question:** can it make a defensible editing decision rather than merely operate tools?

Candidate families include:

- performance selection;
- quote selection;
- cut-point placement;
- b-roll matching;
- dialogue/music relationship;
- continuity and information order.

The result remains embodied in an editable project or bounded timeline. Controlled decisions provide diagnostic evidence before a whole project compounds every failure mode.

## 4. Project / Field

**Object:** full working system.

**Question:** can it produce professionally acceptable finished work from supplied assets and a brief?

This instrument joins:

- deterministic deliverable checks;
- project editability and source lineage;
- final-render validation;
- source-aware editorial judgment;
- repeated attempts;
- interaction burden and economics.

Field runs may use autonomous, scripted-collaboration, or expert-operated policies. Results remain separated by policy.

## 5. Revision / Recovery

**Object:** full working system acting on an existing project.

**Question:** can it change the requested work while preserving accepted work?

A revision form declares:

```text
starting accepted project
requested changes
protected invariants
permitted collateral changes
forbidden regressions
final deliverables
```

Metrics include:

```text
requested-change completion
protected-state preservation
regression count
unnecessary edit radius
timeline churn
revision first-pass acceptance
same-defect recurrence
cost to accepted revision
human intervention
```

A matched revision study may compare a clean consolidated final instruction against a correction trajectory reaching the same final state.

## 6. Judge Qualification

**Object:** JudgeStack.

**Question:** can the measurement system recognize the success and failure classes it is authorized to judge?

Qualification uses:

- absolute anchors;
- acceptable alternatives;
- controlled mutants;
- near-miss cases;
- order reversals;
- identity blinding;
- compression and evidence-transform variants;
- prompt-injection sentinels;
- confidence calibration;
- preserved disagreement.

Eligibility is criterion-specific. A judge qualified for caption correctness is not automatically qualified for performance selection or audio mixing.

## Economics is cross-cutting

Economics applies to candidate instruments but remains a separate analysis layer. VideoBench preserves raw usage and later applies versioned pricing and utilization assumptions.

The useful headline is cost to accepted work, not `quality / dollars` and not the marginal cost fiction of `$0` under a flat subscription.
