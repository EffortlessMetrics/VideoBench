# ADR 0006: Unknown provider usage is not zero

## Status

Accepted.

## Context

Raw APIs, managed products, local endpoints, and agent harnesses expose different usage evidence. Some report complete token details. Some omit cached input, reasoning, media units, retries, or cash cost. Some report no metering at all.

Defaulting an unavailable dimension to zero manufactures economic evidence. A run with no token receipt can then appear cheaper than a fully receipted run, and a pricing projection can produce a precise but false dollar amount.

## Decision

Provider-metered `UsageRecord` dimensions are nullable.

```text
null = not established by the run evidence
0    = established zero
```

List-equivalent cost is nullable. If a frozen pricing policy requires a total
or subset whose usage is unknown, the total is unknown. Cached input and
reasoning are subsets of inclusive input and output totals; different ordinary
and subset rates require both values so the projection can partition rather
than double-price them.

Locally observable counts and durations may retain numeric zero defaults when the runner itself can establish them.

## Consequences

- adapters must preserve missing usage explicitly;
- reports distinguish priced and unpriced attempts;
- study summaries state economic-evidence coverage;
- a configured limit cannot be claimed enforced when its required usage is
  unavailable; an otherwise successful attempt is `not_proven`, not accepted;
- old evidence can be repriced only to the extent its raw usage supports the new policy;
- `$0.00` is reserved for an evidenced zero, not a missing receipt.
