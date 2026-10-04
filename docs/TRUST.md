# Trust, provenance, and rights

Trust belongs to evidence bundles and their receipts. It is not a personality assigned to a model, contributor, or benchmark operator.

## Separate trust dimensions

### Provenance and attestation

```text
self_submitted
peer_reproduced
official_reproduced
official_hosted
attested_environment
```

### Judgment status

```text
unjudged
self_judged
qualified_panel_judged
human_adjudicated
```

### Artifact validity

```text
valid
invalid
contested
instrument_failure
not_proven
```

### Comparability

```text
directly_comparable
diagnostically_comparable
valid_non_comparable
```

### Confidentiality

```text
public
controlled
private_canary
retired_audit
```

One `trust_class` field would mix facts that must remain independently reviewable.

Score projection defaults to:

```text
self_submitted
unjudged or self_judged/qualified_panel_judged from attached evidence
verified artifact validity
valid_non_comparable
the WorkResult confidentiality state
```

`directly_comparable` is not inferred from a successful run. It requires an affirmative
study receipt showing that exact frozen forms, RunStack conditions, environments, retry
policy, scoring policy, and pricing policy support the intended comparison. A
`TrustReceipt` asserting elevated provenance, diagnostic/direct comparability, or human
adjudication must carry `evidence_refs`; scoring also rejects judgment-status claims that
contradict the attached JudgmentBundle and qualification receipts.

## Rights manifest

Every real source pack should declare:

```text
source authority
copyright and license
consent or lawful-use basis
privacy classification
redaction manifest
allowed publication scope
model-provider upload permission
candidate-output redistribution permission
retention and deletion policy
```

Private source assets can remain encrypted, restricted, redacted, or hash-only. The active pack may reference them without committing raw content.

## Model and product provenance

Record:

- provider and surface;
- model name and snapshot where exposed;
- collection date and time;
- product plan and effort mode;
- memory, project, and context policy;
- tool and scaffold versions;
- publication and redistribution constraints;
- known silent-update risk.

A product result collected on one date is an observation of that product configuration on that date.

## Environment attestation

An environment receipt should be content-addressed and tied to the attempt. When a third party cannot reproduce a proprietary or managed environment exactly, the result may remain valid but only diagnostically comparable.

## Community validators

Initial public packs accept only:

- built-in declarative checks;
- reviewed first-party adapters;
- bounded command execution initiated by the local operator;
- strict artifact-size and resource policies.

Do not execute arbitrary validator code from a submitted pack inside an official runner without a dedicated sandbox and review policy.

## Prompt injection

Source media, captions, on-screen text, spoken words, model output, tool logs, and imported judgments are untrusted input.

Judge execution must not expose environment-changing tools. Qualification should include visual, textual, and spoken injection sentinels.

## Release lifecycle

```text
public development forms
private active forms
quarterly canary refreshes
semiannual official packs
bridge forms across adjacent releases
retired public audit forms
```

Frozen forms never mutate. Defects produce an `ErratumRecord` and a new release or exclusion decision.

VideoBench is designed to make gaming and contamination visible. It does not claim to be cheating-proof.
