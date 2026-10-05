# Provider and agent-harness adapters

VideoBench includes a first-party OpenAI-compatible HTTP adapter for receipted model and tool runs. It translates provider behavior into the generic `RunStack`, `RunEvent`, `UsageRecord`, and `WorkResultBundle` contracts. Provider-specific response objects do not enter task authoring, verification, judging, scoring, or study analysis.

The adapter supports two wire styles:

```text
responses
chat_completions
```

The model identity remains in `RunStack`. The adapter configuration describes transport, request policy, evidence retention, and the function-tool harness.

## Run one attempt

```bash
videobench run-openai-compatible \
  --execution-pack .videobench/forms/form-id/execution-pack.json \
  --run-stack path/to/run-stack.yaml \
  --run-condition path/to/run-condition.yaml \
  --adapter-config examples/provider-adapters/openai-responses.yaml \
  --asset-root path/to/task-root \
  --workspace .videobench/work/attempt-001 \
  --artifact-root .videobench/work/attempt-001/output \
  --out .videobench/runs/attempt-001.json
```

The output directory must be absent or empty. The adapter writes its final text, provider trace, function-tool artifacts, and any declared command-tool outputs below that directory. The runner then captures and hashes every durable artifact.

## Configuration

A minimal Responses configuration is:

```yaml
adapter_id: openai-responses-v1
endpoint: https://api.openai.com/v1/responses
api_style: responses
api_key_env: OPENAI_API_KEY
require_api_key: true
store: false
request_trace_mode: redacted
max_model_calls: 8
max_tool_calls: 64
```

A local Chat Completions-compatible endpoint can omit authentication and provider-specific storage fields:

```yaml
adapter_id: local-chat-v1
endpoint: http://127.0.0.1:8000/v1/chat/completions
api_style: chat_completions
require_api_key: false
store: null
chat_max_tokens_field: max_tokens
request_trace_mode: redacted
```

`OpenAICompatibleConfig` is a checked-in JSON Schema. Unknown fields are rejected.

## Credentials and headers

Secrets come from environment variables.

- `api_key_env` supplies the bearer token.
- `header_environment` maps additional header names to environment-variable names.
- literal `authorization`, `api-key`, and `x-api-key` values are rejected in `extra_headers`.
- endpoint URLs containing user information or fragments are rejected.
- plain HTTP is limited to loopback hosts by default; a non-loopback HTTP endpoint requires an explicit `allow_insecure_http: true` declaration.
- request traces never contain outbound headers.

Set `require_api_key: false` only for an endpoint that intentionally accepts unauthenticated local requests. Prefer HTTPS whenever a credential or private source material leaves the workstation.

## Request and response evidence

`request_trace_mode` controls how the exact provider payload appears in the durable trace:

| Mode | Durable request evidence |
|---|---|
| `digest_only` | canonical request digest only |
| `redacted` | digest plus request body with inline image bytes replaced by their hash and byte count |
| `full` | digest plus the complete request body |

`redacted` is the default. It preserves prompt, tool-schema, and request-shape evidence without duplicating inline source-image bytes into the trace.

`preserve_raw_responses: true` retains complete provider JSON responses. When false, successful traces keep response identifiers, usage, parsed output text, and executed tool calls without retaining the complete response object; HTTP and protocol-error bodies are replaced by their SHA-256 digest and byte count and are not copied into stderr. The source pack's confidentiality and redistribution policy still governs whether a resulting trace may be published.

## Function tools

The adapter exposes bounded built-ins when enabled:

```text
videobench_write_text_artifact
videobench_write_json_artifact
videobench_read_asset_text
videobench_copy_asset
```

These tools enforce root-contained paths. They cannot read arbitrary host files or write outside the declared artifact root.

Additional tools use declarative command specifications:

```yaml
command_tools:
  - name: resolve_edit_step
    description: Execute one bounded editing step through a qualified wrapper.
    parameters:
      type: object
      properties:
        operation:
          type: string
        arguments:
          type: object
      required: [operation, arguments]
      additionalProperties: false
    command: [python, /absolute/path/to/resolve_wrapper.py]
    timeout_seconds: 120
    pass_environment: [RESOLVE_SCRIPT_API]
```

Command tools:

- execute without a shell;
- receive one JSON object on standard input;
- receive only a small baseline environment plus explicitly allowed variables;
- receive `VIDEOBENCH_OUTPUT_DIR`, `VIDEOBENCH_WORKSPACE`, `VIDEOBENCH_ASSET_ROOT`, attempt ID, stack ID, tool name, and call ID;
- preserve exit status, stdout, stderr, duration, timeout, and launch failures in the tool trace;
- do not establish terminal success. Independent verification still decides what state exists.

Tool names and parameter schemas are validated before the run. Command tools default to `strict: true`. Every object in a strict schema must set `additionalProperties: false`, and every declared property must appear in `required`; a logically optional value is represented as a required nullable field. Set `strict: false` only when a compatible endpoint or a deliberately open value shape cannot satisfy that subset. The built-in arbitrary-JSON artifact writer is intentionally non-strict; the other built-ins use strict-compatible schemas.

A non-strict command wrapper remains responsible for validating the arguments it accepts. `strict: false` changes provider-side schema enforcement; it does not weaken VideoBench's independent terminal-state verification.

## Retry and budget semantics

Transport retries are explicit events and usage facts. They are separate from model retries, re-prompts, tool loops, and agent self-correction.

The adapter enforces the tighter of its own and the `RunStack` model-call and tool-call limits. It also applies the declared wall-time budget while requests and command tools are running, and stops before executing tools after a reported token budget has already been exceeded.

A retry, timeout, rate limit, malformed response, missing credential, cancellation, or exhausted resource envelope receives a typed outcome and remains in the evidence. Failed attempts are not discarded from later acceptance or cost analysis.

## Usage is unknown until proven

Provider-metered fields are nullable by design:

```text
input_tokens
cached_input_tokens
cache_write_tokens
reasoning_tokens
output_tokens
image_units
video_units
actual candidate cost
```

`null` means the provider or product surface did not expose enough evidence. It never means zero. A list-equivalent cost is therefore also unknown when a pricing policy assigns a nonzero rate to a missing usage dimension.

Locally observable counts such as model calls, tool calls, transport retries, and wall time remain concrete.

## Offline and live tests

The default suite is credential-free. It covers both API styles, function-tool loops, request redaction, usage parsing, explicit retries, rate limits, malformed responses, missing usage, timeouts, cancellation, command-tool failures, and resource budgets. A local HTTP test exercises the real standard-library transport without contacting an external provider.

A credentialed run is an external evidence operation. Preserve its exact `RunStack`, adapter configuration, endpoint identity, provider timestamps and identifiers, raw usage, pricing policy, output artifacts, and redaction receipt before using it in a study.

## Claim boundary

A successful adapter run establishes that the declared provider/harness path produced a valid `WorkResultBundle`. It does not establish that the work met the brief, that Resolve reached the requested state, or that the edit was professionally acceptable. Those claims require independent verification and, where applicable, a qualified JudgeStack.
