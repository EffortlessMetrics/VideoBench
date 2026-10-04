# Task authoring

A benchmark form is not ready because a model fails it or because its reference output looks plausible. It becomes eligible after construct, oracle, evidence, and judge review.

## Hierarchy

```text
AssetSet != TaskFamily != Form != Pack
         != StudySpec != Attempt != Observation
```

### AssetSet

Frozen source material and rights metadata.

### TaskFamily

The stable work construct, such as interview compression, b-roll integration, performance selection, or surgical revision.

### Form

One frozen instance of a family: exact assets, brief, starting project, output contract, hidden obligations, evidence configuration, and acceptable variation.

### Pack

A release-selected collection of forms.

### StudySpec

A predeclared comparison: exact frozen task/form/ExecutionPack identities, participating
stacks, treatment, controls, attempts, budgets, judge policy, pricing policy, analysis
policy, and permitted claims. Naming only a family is not enough for an official study;
it would permit post-run form selection.

### Attempt

One clean execution from one clean starting state.

### Observation

A derived measurement from an attempt. Several checks or criteria do not become several independent runs.

## Authoring a TaskSource

A `TaskSource` declares:

```text
task/family/form identity
instrument
brief
assets and hashes
output contract
public constraints
hidden obligations
objective checks
semantic criteria
evidence requirements
acceptable variation
prohibited outcomes
controlled mutants
acceptance policy
confidentiality and metadata
```

See [`examples/interview-cut/task.yaml`](../examples/interview-cut/task.yaml) for the complete public development form.

## Asset discipline

Every exact asset should have:

- stable path or content-addressed reference;
- SHA-256;
- role;
- media type;
- publication eligibility;
- rights and consent basis in the pack provenance manifest.

Asset paths are portable POSIX-style paths relative to the task source directory and may
not escape it. VideoBench rejects absolute paths, drive-relative Windows paths, native
backslashes, empty/current/parent segments, and symbolic links. Files use byte SHA-256;
directory assets use a deterministic manifest over relative file path, size, and byte
digest.

The public demo commits small synthetic assets. Real media packs should normally store large content in LFS or content-addressed object storage while keeping manifests and hashes in Git.

## Hard obligations

A hard obligation must identify an observable consequence.

Good:

> The project must reopen with every used source clip online.

Weak:

> The project should be professional.

The first belongs in the verifier. The second needs decomposition into either objective defects or semantic criteria.

## Objective checks

Each check declares:

```text
check ID
check type
artifact path
JSON path where applicable
expected value or bound
severity
reason code
```

Fatal checks gate acceptance. Major and advisory checks remain visible diagnostics without silently changing the gate.

The compiled task acceptance policy, not a later reporting preference, determines which
classes of evidence are mandatory. Scoring policies may select a declared semantic
aggregation rule but cannot weaken the compiled artifact or hard-contract gates.

Avoid using deterministic checks to force one valid creative solution. A reference timeline is evidence, not the universal answer key.

## Semantic criteria

A criterion must state:

- the decision being evaluated;
- the score range and threshold;
- whether falling below the threshold is fatal;
- the evidence the judge needs;
- stable reason codes.

Task-family criteria are preferable to one universal `aesthetic quality` scale.

Examples:

- interview: selection, argument, performance, pacing, b-roll use;
- montage: audiovisual rhythm, shot progression, temporal structure;
- tutorial: information order, legibility, instructional completeness;
- revision: requested-change completion, preservation, collateral damage.

## Acceptable variation

Declare the degrees of freedom explicitly. Examples:

- several quote orders may support the same argument;
- more than one take may be professionally acceptable;
- exact trim points may vary within a beat;
- either of two b-roll shots may satisfy the purpose.

A benchmark that silently expects one editor's timeline will measure imitation.

## Controlled mutants

Every critical dimension should have at least one discriminating mutant.

Useful mutants include:

```text
essential quote removed
meaning-changing reorder
wrong performance take
flash frame
black gap
music transition off phrase
dialogue buried
clipped audio
caption shifted
wrong lower-third identity
safe-area violation
wrong aspect ratio
flattened project
offline source media
visual or spoken judge injection
```

The best mutant changes one intended dimension while preserving the rest.

## Promotion reviews

### Construct review

- What work construct is being measured?
- Which instrument owns it?
- Is one primary mechanic isolated where a causal claim is intended?
- Which stressors are incidental?
- What alternative explanation remains?
- What would falsify the intended interpretation?

### Oracle and contract review

- Which requirements are hard?
- Which outcomes are valid alternatives?
- Can each fatal obligation be observed independently?
- Does the verifier reject controlled violations?
- Does the starting state recreate deterministically?

### Judge review

- What evidence is required for each criterion?
- Can qualified judges detect the controlled mutants?
- Do they preserve acceptable alternatives?
- What transform blind spots remain?
- When is `insufficient basis` the correct result?

### Rights and privacy review

- Is every asset authorized for its declared use?
- May raw source and candidate outputs be redistributed?
- Is any private source retained outside Git?
- Is the active form public, controlled, private-canary, or retired-audit?

No single review substitutes for the others.
