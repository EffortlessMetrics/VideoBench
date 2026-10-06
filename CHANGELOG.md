# Changelog

All notable changes will be documented here.

## Unreleased

### Added

- Python-first evidence protocol and CLI.
- Three-view task compiler with leak checks and exact ExecutionPack/instrument binding.
- Command, manual, and frozen-candidate run capture with clean-output, resource, symlink, reserved-environment, and invalid-usage controls.
- First-party OpenAI-compatible Responses/Chat Completions adapter with credential-safe
  headers, request digests and redaction, image input, explicit retries, function-tool
  loops, bounded artifact/asset tools, declarative command tools, resource envelopes,
  per-tool strict-schema validation, loopback-only plain HTTP defaults, complete raw-response
  opt-out, and credential-free transport tests.
- Provider-adapter integrity controls for terminal response states, request-by-request
  retry receipts, nullable metering, frozen-asset digest checks, reserved evidence paths,
  local JSON-Schema argument validation, redirect refusal, HTTPS-only credentials,
  secret-safe durable errors, bounded `Retry-After`, and stateless encrypted-reasoning
  replay.
- Nullable provider-metered usage and economic-evidence coverage so an unavailable token
  or cost receipt is never reported as zero.
- Inclusive token accounting that partitions cached input and reasoning subsets before
  applying versioned list prices, plus `not_proven` outcomes when a declared token limit
  cannot be checked from the available usage evidence.
- Independent artifact and terminal-state verifier.
- Judge evidence transforms, qualification, and judgment import.
- Gated scoring, pricing, exact-frozen-form family summaries, trust-claim validation, and Markdown reports.
- Read-only Resolve project snapshot and ffprobe adapter.
- Checked-in JSON Schemas and synthetic vertical instrument.
