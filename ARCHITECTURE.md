# Architecture

VideoBench uses ports-and-adapters boundaries around a versioned evidence protocol.

## Modules

| Module | Responsibility |
|---|---|
| `types` | wire-safe enums, artifact envelope, shared status vocabulary |
| `contracts` | versioned domain models and information boundaries |
| `canonical` | canonical JSON, raw and semantic digests |
| `compiler` | task validation, blind view compilation, leak checks |
| `runner` | command/manual/mock/provider execution, event and artifact capture |
| `verifier` | independent artifact integrity and deterministic checks |
| `judge` | evidence-transform validation, judgment import, qualification |
| `analysis` | gated scoring, pricing, family-level aggregation, reports |
| `adapters` | Resolve, media, provider, and future control integrations |
| `schemas` | checked-in JSON Schema projection |
| `cli` | thin orchestration over the modules above |

## Information-flow boundaries

- Runner code imports candidate-safe contracts only.
- The candidate receives an `ExecutionPack`, never the `VerifierPack` or `JudgePack`.
- Verification never trusts candidate success claims as terminal-state truth.
- Judging never reruns the candidate.
- Scoring consumes evidence bundles and policies; it does not alter them.
- Reports are projections.

## Ports to extend

The first release uses ordinary Python call boundaries rather than a framework-heavy dependency injection layer. The stable seams are:

```text
candidate command / product capture
Resolve state probe
media probe
model provider
control surface
judge provider
artifact store
pricing provider
operator interface
```

A concrete adapter should translate external behavior into the existing contracts rather than adding provider-specific fields throughout the domain model.

The first-party OpenAI-compatible adapter is the reference implementation of that rule:
provider JSON stays in a candidate-side trace, while the durable cross-provider surface is
`RunEvent`, `UsageRecord`, `EvidenceArtifact`, and `WorkResultBundle`.

## Python-first decision

Python minimizes friction around Resolve scripting, subprocess orchestration, media inspection, model adapters, and fixture iteration. The protocol is kept language-neutral through JSON Schemas and content-addressed artifacts.

Stable performance-sensitive components may later move to Rust or Go. A port is justified by a measured operational need, not by treating the prototype language as temporary throwaway work.
