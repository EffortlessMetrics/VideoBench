from __future__ import annotations

import json
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from videobench.adapters.openai_compatible import (
    ChatMaxTokensField,
    CommandToolSpec,
    InlineImageSpec,
    OpenAIAPIStyle,
    OpenAICompatibleConfig,
    ProviderTransportError,
    RequestTraceMode,
    TransportResponse,
    UrllibTransport,
)
from videobench.compiler import compile_task_file
from videobench.contracts import (
    AssetSpec,
    ExecutionPack,
    MediaType,
    RunCondition,
    RunStack,
)
from videobench.io import load_model, payload_as, write_envelope
from videobench.runner import run_openai_compatible
from videobench.types import OutcomeStatus


class FakeTransport:
    def __init__(self, responses: list[TransportResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> TransportResponse:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "body": json.loads(body),
                "timeout_seconds": timeout_seconds,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(payload: dict[str, Any], status: int = 200, **headers: str) -> TransportResponse:
    return TransportResponse(
        status=status,
        headers={key.lower(): value for key, value in headers.items()},
        body=json.dumps(payload).encode(),
    )


def _final_response(text: str = "done", *, usage: bool = True) -> TransportResponse:
    payload: dict[str, Any] = {
        "id": "resp-final",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }
    if usage:
        payload["usage"] = {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 0},
            "output_tokens": 25,
            "output_tokens_details": {"reasoning_tokens": 5},
        }
    return _response(payload, **{"x-request-id": "request-final"})


def _compiled(
    example_root: Path, tmp_path: Path
) -> tuple[Path, ExecutionPack, RunStack, RunCondition]:
    paths = compile_task_file(example_root / "task.yaml", tmp_path / "compiled")
    execution = payload_as(paths.execution_pack, ExecutionPack, expected_kind="execution_pack")
    stack = load_model(example_root / "stacks/mock-good.yaml", RunStack)
    stack.system.provider = "openai-compatible"
    stack.system.model = "test-model"
    stack.resource_envelope.max_model_calls = 8
    condition = RunCondition(attempt_id="provider-001", clean_state_id="clean-v1")
    return paths.execution_pack, execution, stack, condition


def _config(**changes: Any) -> OpenAICompatibleConfig:
    values: dict[str, Any] = {
        "adapter_id": "test-adapter",
        "endpoint": "https://provider.example/v1/responses",
        "require_api_key": False,
        "transport_max_attempts": 1,
        "transport_backoff_seconds": [],
    }
    values.update(changes)
    return OpenAICompatibleConfig.model_validate(values)


def test_responses_run_captures_usage_trace_and_final_text(
    example_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    transport = FakeTransport([_final_response("finished")])
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")

    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )

    assert result.outcome == OutcomeStatus.PASS
    assert result.stdout == "finished"
    assert result.usage.input_tokens == 100
    assert result.usage.cached_input_tokens == 20
    assert result.usage.reasoning_tokens == 5
    assert result.usage.output_tokens == 25
    assert result.usage.model_calls == 1
    assert result.usage.actual_candidate_cost_usd is None
    assert "candidate_cost_not_reported" in result.known_missing_evidence
    assert (tmp_path / "output/provider/final.txt").read_text() == "finished"
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    assert trace["requests"][0]["request_id"] == "request-final"
    assert "secret-value" not in json.dumps(trace)
    assert transport.requests[0]["headers"]["authorization"] == "Bearer secret-value"


def test_responses_tool_loop_writes_artifacts(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    timeline = {
        "timeline": {
            "duration_seconds": 60,
            "aspect_ratio": "16:9",
            "quote_count": 2,
            "b_roll_cues": 1,
            "captions_present": True,
            "lower_third": {"text": "Alex Rivera — Editor"},
            "closing_card": "Measure accepted work",
        },
        "project": {"editable": True, "source_media_online": True},
        "audio": {"true_peak_dbfs": -1},
    }
    first = _response(
        {
            "id": "resp-tools",
            "output": [
                {
                    "type": "function_call",
                    "name": "videobench_write_json_artifact",
                    "arguments": json.dumps({"path": "timeline.json", "value": timeline}),
                    "call_id": "call-json",
                },
                {
                    "type": "function_call",
                    "name": "videobench_write_text_artifact",
                    "arguments": json.dumps(
                        {"path": "final-proxy.txt", "content": "Measure accepted work"}
                    ),
                    "call_id": "call-text",
                },
            ],
            "usage": {
                "input_tokens": 50,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens": 20,
                "output_tokens_details": {"reasoning_tokens": 2},
            },
        }
    )
    transport = FakeTransport([first, _final_response()])

    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )

    assert result.outcome == OutcomeStatus.PASS
    assert result.usage.model_calls == 2
    assert result.usage.tool_calls == 2
    assert (tmp_path / "output/timeline.json").is_file()
    assert (tmp_path / "output/final-proxy.txt").is_file()
    second_input = transport.requests[1]["body"]["input"]
    outputs = [item for item in second_input if item.get("type") == "function_call_output"]
    assert {item["call_id"] for item in outputs} == {"call-json", "call-text"}


def test_chat_completions_inlines_image_and_preserves_chat_usage(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    image = tmp_path / "pixel.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    execution.assets.append(
        AssetSpec(
            asset_id="reference-frame",
            path="pixel.png",
            media_type=MediaType.IMAGE,
            role="reference frame",
        )
    )
    write_envelope(pack_path, "execution_pack", execution)
    transport = FakeTransport(
        [
            _response(
                {
                    "id": "chat-1",
                    "choices": [{"message": {"role": "assistant", "content": "done"}}],
                    "usage": {
                        "prompt_tokens": 80,
                        "prompt_tokens_details": {"cached_tokens": 10},
                        "completion_tokens": 12,
                        "completion_tokens_details": {"reasoning_tokens": 3},
                    },
                }
            )
        ]
    )

    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(
            api_style=OpenAIAPIStyle.CHAT_COMPLETIONS,
            inline_images=[InlineImageSpec(asset_id="reference-frame")],
        ),
        asset_root=tmp_path,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )

    assert result.usage.input_tokens == 80
    assert result.usage.output_tokens == 12
    user_content = transport.requests[0]["body"]["messages"][1]["content"]
    assert any(
        item.get("type") == "image_url"
        and item["image_url"]["url"].startswith("data:image/png;base64,")
        for item in user_content
    )
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    traced_request = trace["requests"][0]["request"]
    assert "<redacted sha256=" in json.dumps(traced_request)
    assert "c3ludGhldGlj" not in json.dumps(traced_request)


def test_transport_retry_is_explicit(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    transport = FakeTransport(
        [
            _response({"error": "slow down"}, status=429, **{"retry-after": "0"}),
            _final_response(),
        ]
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(transport_max_attempts=2, transport_backoff_seconds=[0]),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
        sleep=lambda _: None,
    )
    assert result.outcome == OutcomeStatus.PASS
    assert result.usage.transport_retries == 1
    assert any(event.event_type == "provider_transport_retry" for event in result.events)


def test_terminal_rate_limit_is_tool_failure(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([_response({"error": "rate limited"}, status=429)]),
    )
    assert result.outcome == OutcomeStatus.TOOL_FAILURE
    assert any(event.event_type == "provider_rate_limited" for event in result.events)


def test_malformed_provider_response_is_protocol_invalid(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([TransportResponse(status=200, headers={}, body=b"not-json")]),
    )
    assert result.outcome == OutcomeStatus.PROTOCOL_INVALID
    assert "invalid JSON" in result.stderr


def test_missing_usage_remains_unknown(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([_final_response(usage=False)]),
    )
    assert result.outcome == OutcomeStatus.PASS
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert "input_tokens_not_reported" in result.known_missing_evidence


def test_model_call_budget_stops_tool_loop(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    first = _response(
        {
            "id": "resp-tools",
            "output": [
                {
                    "type": "function_call",
                    "name": "videobench_write_text_artifact",
                    "arguments": json.dumps({"path": "one.txt", "content": "one"}),
                    "call_id": "call-1",
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(max_model_calls=1),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([first]),
    )
    assert result.outcome == OutcomeStatus.BUDGET_EXHAUSTED
    assert any(event.event_type == "model_call_budget_exhausted" for event in result.events)


def test_tool_call_budget_stops_before_execution(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    first = _response(
        {
            "id": "resp-tools",
            "output": [
                {
                    "type": "function_call",
                    "name": "videobench_write_text_artifact",
                    "arguments": json.dumps({"path": "one.txt", "content": "one"}),
                    "call_id": "call-1",
                }
            ],
        }
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(max_tool_calls=0),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([first]),
    )
    assert result.outcome == OutcomeStatus.BUDGET_EXHAUSTED
    assert not (tmp_path / "output/one.txt").exists()


def test_cancellation_prevents_provider_request(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    transport = FakeTransport([])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
        cancellation_check=lambda: True,
    )
    assert result.outcome == OutcomeStatus.HUMAN_ABORT
    assert transport.requests == []


def test_transport_timeout_is_typed(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([ProviderTransportError("TimeoutError: timed out")]),
    )
    assert result.outcome == OutcomeStatus.TIMED_OUT


def test_declared_command_tool_receives_json_and_protocol_environment(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    tool_script = tmp_path / "tool.py"
    tool_script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args=json.load(sys.stdin)\n"
        "out=Path(os.environ['VIDEOBENCH_OUTPUT_DIR'])\n"
        "(out/'tool-result.txt').write_text(args['value'])\n"
        "print(json.dumps({'attempt': os.environ['VIDEOBENCH_ATTEMPT_ID']}))\n",
        encoding="utf-8",
    )
    first = _response(
        {
            "id": "resp-tool",
            "output": [
                {
                    "type": "function_call",
                    "name": "write_with_command",
                    "arguments": json.dumps({"value": "evidence"}),
                    "call_id": "cmd-1",
                }
            ],
        }
    )
    config = _config(
        command_tools=[
            CommandToolSpec(
                name="write_with_command",
                description="Write a test artifact.",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                command=[sys.executable, str(tool_script)],
            )
        ]
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=config,
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([first, _final_response()]),
    )
    assert result.outcome == OutcomeStatus.PASS
    assert (tmp_path / "output/tool-result.txt").read_text() == "evidence"


def test_config_rejects_endpoint_credentials_and_literal_secret_headers() -> None:
    with pytest.raises(ValidationError, match="must not contain credentials"):
        _config(endpoint="https://user:secret@provider.example/v1/responses")
    with pytest.raises(ValidationError, match="sensitive header values"):
        _config(extra_headers={"Authorization": "Bearer secret"})


def test_command_tool_requires_strict_object_schema() -> None:
    with pytest.raises(ValidationError, match="object schema"):
        CommandToolSpec(
            name="bad",
            description="bad",
            parameters={"type": "string", "additionalProperties": False},
            command=[sys.executable],
        )
    with pytest.raises(ValidationError, match="additionalProperties"):
        CommandToolSpec(
            name="bad",
            description="bad",
            parameters={"type": "object", "properties": {}},
            command=[sys.executable],
        )


def test_missing_required_api_key_is_environment_blocked(
    example_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    transport = FakeTransport([_final_response()])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(require_api_key=True),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.ENVIRONMENT_BLOCKED
    assert transport.requests == []
    assert "OPENAI_API_KEY" in result.stderr


def test_header_environment_is_used_without_being_written_to_trace(
    example_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    monkeypatch.setenv("PROVIDER_TENANT", "private-tenant")
    transport = FakeTransport([_final_response()])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(header_environment={"x-tenant": "PROVIDER_TENANT"}),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.PASS
    assert transport.requests[0]["headers"]["x-tenant"] == "private-tenant"
    trace = (tmp_path / "output/provider/trace.json").read_text()
    assert "private-tenant" not in trace


@pytest.mark.parametrize(
    ("mode", "request_present"),
    [
        (RequestTraceMode.DIGEST_ONLY, False),
        (RequestTraceMode.REDACTED, True),
        (RequestTraceMode.FULL, True),
    ],
)
def test_request_trace_modes(
    mode: RequestTraceMode,
    request_present: bool,
    example_root: Path,
    tmp_path: Path,
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(request_trace_mode=mode),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([_final_response()]),
    )
    assert result.outcome == OutcomeStatus.PASS
    request_record = json.loads((tmp_path / "output/provider/trace.json").read_text())["requests"][
        0
    ]
    assert "request_sha256" in request_record
    assert ("request" in request_record) is request_present


def test_chat_request_supports_current_and_legacy_token_fields(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    transport = FakeTransport([_response({"choices": [{"message": {"content": "done"}}]})])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(
            api_style=OpenAIAPIStyle.CHAT_COMPLETIONS,
            max_output_tokens=42,
            reasoning_effort="medium",
            store=None,
        ),
        asset_root=example_root,
        workspace=tmp_path / "workspace-current",
        output_dir=tmp_path / "output-current",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.PASS
    body = transport.requests[0]["body"]
    assert body["max_completion_tokens"] == 42
    assert body["reasoning_effort"] == "medium"
    assert "store" not in body

    legacy_transport = FakeTransport([_response({"choices": [{"message": {"content": "done"}}]})])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=RunCondition(attempt_id="provider-legacy", clean_state_id="clean-v1"),
        config=_config(
            api_style=OpenAIAPIStyle.CHAT_COMPLETIONS,
            max_output_tokens=24,
            chat_max_tokens_field=ChatMaxTokensField.MAX_TOKENS,
        ),
        asset_root=example_root,
        workspace=tmp_path / "workspace-legacy",
        output_dir=tmp_path / "output-legacy",
        transport=legacy_transport,
    )
    assert result.outcome == OutcomeStatus.PASS
    assert legacy_transport.requests[0]["body"]["max_tokens"] == 24


def test_chat_tool_loop_supplies_tool_message(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    first = _response(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "chat-call-1",
                                "type": "function",
                                "function": {
                                    "name": "videobench_write_text_artifact",
                                    "arguments": json.dumps(
                                        {"path": "chat.txt", "content": "chat"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )
    second = _response({"choices": [{"message": {"role": "assistant", "content": "done"}}]})
    transport = FakeTransport([first, second])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(api_style=OpenAIAPIStyle.CHAT_COMPLETIONS),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.PASS
    assert (tmp_path / "output/chat.txt").read_text() == "chat"
    tool_messages = [
        message
        for message in transport.requests[1]["body"]["messages"]
        if message.get("role") == "tool"
    ]
    assert tool_messages[0]["tool_call_id"] == "chat-call-1"


def test_asset_read_copy_and_truncated_tool_result(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    first = _response(
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "videobench_read_asset_text",
                    "arguments": json.dumps({"asset_id": "transcript"}),
                    "call_id": "read-1",
                },
                {
                    "type": "function_call",
                    "name": "videobench_copy_asset",
                    "arguments": json.dumps(
                        {"asset_id": "lower-third", "path": "copied/lower-third.txt"}
                    ),
                    "call_id": "copy-1",
                },
            ]
        }
    )
    transport = FakeTransport([first, _final_response()])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(max_tool_result_chars=20),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.PASS
    assert (tmp_path / "output/copied/lower-third.txt").is_file()
    outputs = [
        item
        for item in transport.requests[1]["body"]["input"]
        if item.get("type") == "function_call_output"
    ]
    truncated = json.loads(next(item["output"] for item in outputs if item["call_id"] == "read-1"))
    assert truncated["truncated"] is True


def test_tool_errors_are_receipted_and_returned_to_model(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    first = _response(
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "unknown_tool",
                    "arguments": "{}",
                    "call_id": "unknown-1",
                },
                {
                    "type": "function_call",
                    "name": "videobench_write_text_artifact",
                    "arguments": "{",
                    "call_id": "invalid-1",
                },
            ]
        }
    )
    transport = FakeTransport([first, _final_response()])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.PASS
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    errors = {item["call_id"]: item["result"]["error"] for item in trace["tool_calls"]}
    assert errors == {
        "unknown-1": "unknown_tool",
        "invalid-1": "invalid_tool_arguments",
    }


def test_token_budget_stops_before_tools(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    stack.resource_envelope.max_input_tokens = 10
    response = _response(
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "videobench_write_text_artifact",
                    "arguments": json.dumps({"path": "should-not-exist.txt", "content": "x"}),
                    "call_id": "call-1",
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 1},
        }
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([response]),
    )
    assert result.outcome == OutcomeStatus.BUDGET_EXHAUSTED
    assert not (tmp_path / "output/should-not-exist.txt").exists()
    assert any(event.event_type == "token_budget_exhausted" for event in result.events)


def test_zero_wall_budget_prevents_provider_request(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    stack.resource_envelope.max_wall_seconds = 0
    transport = FakeTransport([_final_response()])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.TIMED_OUT
    assert transport.requests == []


def test_command_tool_timeout_and_missing_executable_are_receipted(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    first = _response(
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "slow_tool",
                    "arguments": "{}",
                    "call_id": "slow-1",
                },
                {
                    "type": "function_call",
                    "name": "missing_tool",
                    "arguments": "{}",
                    "call_id": "missing-1",
                },
            ]
        }
    )
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    config = _config(
        command_tools=[
            CommandToolSpec(
                name="slow_tool",
                description="sleep",
                parameters=parameters,
                command=[sys.executable, "-c", "import time; time.sleep(1)"],
                timeout_seconds=0.01,
            ),
            CommandToolSpec(
                name="missing_tool",
                description="missing",
                parameters=parameters,
                command=["__videobench_missing_executable__"],
            ),
        ]
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=config,
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([first, _final_response()]),
    )
    assert result.outcome == OutcomeStatus.PASS
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    results = {item["call_id"]: item["result"] for item in trace["tool_calls"]}
    assert results["slow-1"]["error"] == "tool_timeout"
    assert results["missing-1"]["error"] == "FileNotFoundError"


def test_raw_response_can_be_omitted_from_trace(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(preserve_raw_responses=False),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([_final_response("kept separately")]),
    )
    assert result.outcome == OutcomeStatus.PASS
    request = json.loads((tmp_path / "output/provider/trace.json").read_text())["requests"][0]
    assert "response" not in request
    assert request["response_id"] == "resp-final"
    assert request["output_text"] == "kept separately"


def test_urllib_transport_handles_success_and_http_error() -> None:
    requests: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            requests.append(self.rfile.read(length))
            if self.path == "/error":
                self.send_response(429)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"limited"}')
                return
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("x-request-id", "local-request")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    transport = UrllibTransport()
    try:
        success = transport.post(
            url=f"http://{host}:{port}/ok",
            headers={"content-type": "application/json"},
            body=b"{}",
            timeout_seconds=2,
        )
        error = transport.post(
            url=f"http://{host}:{port}/error",
            headers={"content-type": "application/json"},
            body=b"{}",
            timeout_seconds=2,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert success.status == 200
    assert success.headers["x-request-id"] == "local-request"
    assert error.status == 429
    assert requests == [b"{}", b"{}"]


def test_urllib_transport_wraps_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ProviderTransportError, match="URLError"):
        UrllibTransport().post(
            url="https://provider.example/v1/responses",
            headers={},
            body=b"{}",
            timeout_seconds=1,
        )


def test_checked_in_provider_configs_validate(repo_root: Path) -> None:
    config_root = repo_root / "examples/provider-adapters"
    configs = [
        load_model(config_root / "openai-responses.yaml", OpenAICompatibleConfig),
        load_model(config_root / "local-chat-completions.yaml", OpenAICompatibleConfig),
    ]
    assert configs[0].api_style == OpenAIAPIStyle.RESPONSES
    assert configs[0].require_api_key is True
    assert configs[1].api_style == OpenAIAPIStyle.CHAT_COMPLETIONS
    assert configs[1].require_api_key is False
