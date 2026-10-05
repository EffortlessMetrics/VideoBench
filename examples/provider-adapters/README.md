# Provider adapter examples

These files configure transport and evidence policy. The candidate model belongs in the `RunStack`, not in the adapter configuration.

- `openai-responses.yaml` uses the Responses wire style, bearer authentication from `OPENAI_API_KEY`, non-storage, and redacted request traces.
- `local-chat-completions.yaml` demonstrates an unauthenticated loopback Chat Completions-compatible endpoint that expects the legacy `max_tokens` field.

The examples contain no credentials. Copy one, pin the actual endpoint and policy used by the run, and retain the exact file with the resulting evidence bundle.
