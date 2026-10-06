# Economics

VideoBench measures the cost of obtaining accepted work, not merely the cost of producing any output.

## Preserve raw facts first

A `UsageRecord` retains separately:

```text
input tokens
cached input tokens
cache writes
reasoning tokens
output tokens
image and video units
model calls
tool calls
compaction events
model retries
transport retries
wall time
active agent time
Resolve processing time
render time
human interventions
human seconds
actual candidate cash cost
```

These quantities are not interchangeable. They remain immutable run evidence.

Provider-metered fields are nullable. `null` means the run did not establish the value;
it never means zero. An evidenced zero and an unavailable receipt have different economic
meaning and remain different wire states.

## PricingPolicy

A versioned pricing policy maps raw usage into an API-equivalent list cost:

```text
raw usage + frozen unit prices = list-equivalent candidate cost
```

Old runs can be repriced under a new policy without rerunning the edit. Historical reports continue to reference the exact policy originally used.

If a policy assigns a nonzero rate to an unavailable usage dimension, the projected total
is unknown. Study reports therefore retain both mean cost over priced attempts and the
number of attempts with sufficient pricing evidence.

Provider-specific accounting varies. In the VideoBench wire contract, reported
`input_tokens` and `output_tokens` are inclusive totals. Cached input is a subset
of input; reasoning is a subset of output. A pricing projection therefore uses:

```text
(input total - cached input) × ordinary input rate
+ cached input × cached rate
+ (output total - reasoning) × ordinary output rate
+ reasoning × reasoning rate
```

This preserves the provider receipt while preventing subset tokens from being
charged twice. When the ordinary and subset rates differ, a missing subset makes
the projected total unknown. A pricing policy must also state how cache writes,
images, video, and per-call charges are treated rather than assuming all usage
shares one price.

## Three economic views

### Metered candidate cost

What the provider actually charged for the attempt, where exposed.

### API-equivalent list cost

Raw usage repriced under the frozen list-price policy.

### Product-plan economics

For subscription and quota products, retain:

```text
plan price
quota/reset window
attempts completed
accepted outputs
quota consumed
observed throughput
utilization assumption
```

A subscription run may have zero marginal cash cost. Reporting `$0.00 per run` alone is therefore true but decision-useless.

## Human interaction

Human work stays explicit:

- number of interventions;
- active human seconds;
- nature of intervention where possible;
- whether the run was autonomous, scripted, or expert-operated.

A labour-rate conversion may be a later score view. Human time itself remains the primary fact.

## Candidate and evaluation cost are separate

```text
candidate execution cost
human operator cost
judge cost
benchmark infrastructure cost
fixture-development amortization
```

An expensive judge panel does not make the candidate system more expensive to operate. Reports should show evaluation cost without folding it into candidate execution cost.

## Useful headline metrics

```text
P(accepted on first attempt)
expected candidate cost to accepted work
expected human minutes to accepted work
wall time to accepted work
accepted outputs per product quota period
quality-cost Pareto frontier
```

Avoid `quality / dollars` as the headline. Ratios behave badly near zero and can reward cheap unacceptable output.

## Retry accounting

Infrastructure transport retries and semantic retries are different.

- Every transport attempt remains counted and, when available, contributes its
  own reported usage.
- A retry without a usage receipt makes the affected aggregate unknown; later
  successful usage does not erase that gap.
- Model retries, re-prompts, self-corrections, and compactions are part of the candidate burden.
- Failed attempts remain in acceptance probability and cost-to-accepted-work analysis.
- Silent retries are invalid.
