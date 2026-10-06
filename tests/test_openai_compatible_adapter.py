from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import videobench.adapters.openai_compatible as openai_adapter
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
        "api_key_env": None,
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
        config=_config(api_key_env="OPENAI_API_KEY"),
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
    shutil.copytree(example_root / "assets", tmp_path / "assets")
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
        config=_config(require_api_key=True, api_key_env="OPENAI_API_KEY"),
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


def test_provider_tool_strict_flags_are_schema_compatible(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    command_tool = CommandToolSpec(
        name="optional_command",
        description="A non-strict compatibility tool.",
        strict=False,
        parameters={
            "type": "object",
            "properties": {
                "required_value": {"type": "string"},
                "optional_value": {"type": "string"},
            },
            "required": ["required_value"],
            "additionalProperties": False,
        },
        command=[sys.executable],
    )
    transport = FakeTransport([_final_response()])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(command_tools=[command_tool]),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.PASS
    tools = {item["name"]: item for item in transport.requests[0]["body"]["tools"]}
    assert tools["videobench_write_text_artifact"]["strict"] is True
    assert tools["videobench_write_json_artifact"]["strict"] is False
    assert tools["optional_command"]["strict"] is False
    reader = tools["videobench_read_asset_text"]
    assert reader["strict"] is True
    assert set(reader["parameters"]["required"]) == {"asset_id", "max_chars"}
    assert reader["parameters"]["properties"]["max_chars"]["type"] == [
        "integer",
        "null",
    ]


def test_strict_command_tool_requires_every_property_and_nested_object() -> None:
    with pytest.raises(ValidationError, match="require every property"):
        CommandToolSpec(
            name="optional_property",
            description="bad strict schema",
            parameters={
                "type": "object",
                "properties": {
                    "required_value": {"type": "string"},
                    "optional_value": {"type": ["string", "null"]},
                },
                "required": ["required_value"],
                "additionalProperties": False,
            },
            command=[sys.executable],
        )
    with pytest.raises(ValidationError, match="require every property"):
        CommandToolSpec(
            name="nested_optional_property",
            description="bad nested strict schema",
            parameters={
                "type": "object",
                "properties": {
                    "value": {
                        "type": "object",
                        "properties": {"nested": {"type": "string"}},
                        "required": [],
                        "additionalProperties": False,
                    }
                },
                "required": ["value"],
                "additionalProperties": False,
            },
            command=[sys.executable],
        )


def test_plain_http_requires_loopback_or_explicit_opt_in() -> None:
    with pytest.raises(ValidationError, match="limited to loopback"):
        _config(endpoint="http://provider.example/v1/responses")
    assert _config(endpoint="http://127.0.0.1:8000/v1/responses").allow_insecure_http is False
    assert (
        _config(
            endpoint="http://provider.example/v1/responses",
            allow_insecure_http=True,
        ).allow_insecure_http
        is True
    )
    with pytest.raises(ValidationError, match="URL fragment"):
        _config(endpoint="https://provider.example/v1/responses#secret")


def test_raw_response_opt_out_preserves_digest_not_error_body(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    secret_body = b'{"error":"private-provider-detail"}'
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(preserve_raw_responses=False),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([TransportResponse(status=400, headers={}, body=secret_body)]),
    )
    assert result.outcome == OutcomeStatus.TOOL_FAILURE
    assert "private-provider-detail" not in result.stderr
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    request = trace["requests"][0]
    assert "response_text" not in request
    assert request["response_bytes"] == len(secret_body)
    assert request["response_sha256"]
    assert "private-provider-detail" not in json.dumps(trace)



def test_incomplete_responses_output_is_not_proven(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    response = _response(
        {
            "id": "resp-incomplete",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "partial"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 4},
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
    assert result.outcome == OutcomeStatus.NOT_PROVEN
    assert "max_output_tokens" in result.stderr
    assert not (tmp_path / "output/provider/final.txt").exists()
    assert any(event.event_type == "provider_response_incomplete" for event in result.events)


def test_chat_length_finish_is_not_proven(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    response = _response(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"role": "assistant", "content": "partial"},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(api_style=OpenAIAPIStyle.CHAT_COMPLETIONS),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([response]),
    )
    assert result.outcome == OutcomeStatus.NOT_PROVEN
    assert "finish_reason was length" in result.stderr


def test_retry_usage_and_each_attempt_are_preserved(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    retry = _response(
        {"id": "retry-response", "error": "busy", "usage": {"input_tokens": 40, "output_tokens": 10}},
        status=429,
        **{"x-request-id": "retry-request", "retry-after": "0"},
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(transport_max_attempts=2),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([retry, _final_response()]),
        sleep=lambda _: None,
    )
    assert result.outcome == OutcomeStatus.PASS
    assert result.usage.input_tokens == 140
    assert result.usage.output_tokens == 35
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    assert [item["transport_attempt"] for item in trace["requests"]] == [1, 2]
    assert trace["requests"][0]["request_id"] == "retry-request"
    assert "retry-response" in trace["usage"]["metadata"]["provider_response_ids"]


def test_unmetered_retry_makes_totals_unknown(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    retry = _response({"error": "busy"}, status=503, **{"retry-after": "0"})
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(transport_max_attempts=2),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([retry, _final_response()]),
        sleep=lambda _: None,
    )
    assert result.outcome == OutcomeStatus.PASS
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None


def test_failed_request_without_usage_is_unknown_not_zero(
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
        transport=FakeTransport([_response({"error": "denied"}, status=403)]),
    )
    assert result.outcome == OutcomeStatus.TOOL_FAILURE
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None


@pytest.mark.parametrize("bad_value", [True, "100", -1, 1.5])
def test_malformed_usage_is_protocol_invalid(
    example_root: Path, tmp_path: Path, bad_value: object
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    response = _response(
        {
            "status": "completed",
            "output": [],
            "usage": {"input_tokens": bad_value, "output_tokens": 1},
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
        output_dir=tmp_path / f"output-{str(bad_value).replace('/', '-')}",
        transport=FakeTransport([response]),
    )
    assert result.outcome == OutcomeStatus.PROTOCOL_INVALID
    assert result.usage.input_tokens is None


def test_timeout_partial_bytes_are_serializable(
    example_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)

    def timeout_with_partial_output(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise subprocess.TimeoutExpired(
            cmd=["partial_timeout"],
            timeout=0.2,
            output=b"progress\n",
            stderr=b"warning\n",
        )

    monkeypatch.setattr(openai_adapter.subprocess, "run", timeout_with_partial_output)
    first = _response(
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "partial_timeout",
                    "arguments": "{}",
                    "call_id": "timeout-partial",
                }
            ]
        }
    )
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(
            command_tools=[
                CommandToolSpec(
                    name="partial_timeout",
                    description="print and sleep",
                    parameters=parameters,
                    command=[
                        sys.executable,
                        "-c",
                        "import time; print('progress', flush=True); time.sleep(1)",
                    ],
                    timeout_seconds=0.2,
                )
            ]
        ),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([first, _final_response()]),
    )
    assert result.outcome == OutcomeStatus.PASS
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    tool = trace["tool_calls"][0]["result"]
    assert tool["error"] == "tool_timeout"
    assert "progress" in tool["stdout"]


def test_disabled_builtin_tools_cannot_execute(example_root: Path, tmp_path: Path) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    first = _response(
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "videobench_write_text_artifact",
                    "arguments": json.dumps({"path": "forbidden.txt", "content": "no"}),
                    "call_id": "disabled-1",
                }
            ]
        }
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(enable_artifact_tools=False),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([first, _final_response()]),
    )
    assert result.outcome == OutcomeStatus.PASS
    assert not (tmp_path / "output/forbidden.txt").exists()
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    assert trace["tool_calls"][0]["result"]["error"] == "tool_disabled"


def test_command_arguments_are_schema_validated_before_execution(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    marker = tmp_path / "executed.txt"
    script = tmp_path / "command.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    first = _response(
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "typed_tool",
                    "arguments": json.dumps({"value": 123}),
                    "call_id": "typed-1",
                }
            ]
        }
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(
            command_tools=[
                CommandToolSpec(
                    name="typed_tool",
                    description="requires a string",
                    parameters={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                    command=[sys.executable, str(script)],
                )
            ]
        ),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([first, _final_response()]),
    )
    assert result.outcome == OutcomeStatus.PASS
    assert not marker.exists()
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    assert trace["tool_calls"][0]["result"]["error"] == "tool_arguments_schema_violation"


def test_asset_digest_is_reverified_before_provider_request(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    copied_assets = tmp_path / "assets"
    shutil.copytree(example_root, copied_assets)
    transcript = next(item for item in execution.assets if item.asset_id == "transcript")
    (copied_assets / transcript.path).write_text("tampered", encoding="utf-8")
    transport = FakeTransport([_final_response()])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(),
        asset_root=copied_assets,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.PROTOCOL_INVALID
    assert "digest mismatch" in result.stderr
    assert transport.requests == []


def test_candidate_reserved_path_collision_is_preserved_and_rejected(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    script = tmp_path / "collision.py"
    script.write_text(
        "import os\nfrom pathlib import Path\n"
        "p=Path(os.environ['VIDEOBENCH_OUTPUT_DIR'])/'provider'/'trace.json'\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\np.write_text('candidate')\n",
        encoding="utf-8",
    )
    first = _response(
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "write_collision",
                    "arguments": "{}",
                    "call_id": "collision-1",
                }
            ]
        }
    )
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(
            command_tools=[
                CommandToolSpec(
                    name="write_collision",
                    description="write reserved path",
                    parameters=parameters,
                    command=[sys.executable, str(script)],
                )
            ]
        ),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=FakeTransport([first, _final_response()]),
    )
    assert result.outcome == OutcomeStatus.PROTOCOL_INVALID
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    preserved = trace["reserved_path_collisions"][0]["preserved_as"]
    assert (tmp_path / "output" / preserved).read_text() == "candidate"


def test_declared_deliverable_cannot_overlap_adapter_evidence(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    execution.output_contract.deliverables[0].path = "provider/trace.json"
    write_envelope(pack_path, "execution_pack", execution)
    with pytest.raises(ValueError, match="collide with declared deliverables"):
        run_openai_compatible(
            execution_pack_path=pack_path,
            execution_pack=execution,
            run_stack=stack,
            run_condition=condition,
            config=_config(),
            asset_root=example_root,
            workspace=tmp_path / "workspace",
            output_dir=tmp_path / "output",
            transport=FakeTransport([]),
        )


def test_endpoint_query_and_provider_echoed_secrets_are_redacted(
    example_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    monkeypatch.setenv("TEST_PROVIDER_KEY", "super-secret")
    endpoint = "https://provider.example/v1/responses?api-version=secret-version"
    transport = FakeTransport(
        [
            _response(
                {"error": "super-secret secret-version"},
                status=400,
                **{"x-request-id": "error-request"},
            )
        ]
    )
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(
            endpoint=endpoint,
            api_key_env="TEST_PROVIDER_KEY",
            require_api_key=True,
        ),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert transport.requests[0]["url"] == endpoint
    durable = (tmp_path / "output/provider/trace.json").read_text()
    assert "super-secret" not in durable
    assert "secret-version" not in durable
    assert "super-secret" not in result.stderr
    assert "secret-version" not in result.stderr
    assert result.usage.metadata["endpoint"] == "https://provider.example/v1/responses"


def test_plain_http_rejects_any_credential_source() -> None:
    with pytest.raises(ValidationError, match="credentialed provider requests require HTTPS"):
        _config(
            endpoint="http://127.0.0.1:8000/v1/responses",
            api_key_env="OPENAI_API_KEY",
        )
    with pytest.raises(ValidationError, match="credentialed provider requests require HTTPS"):
        _config(
            endpoint="http://127.0.0.1:8000/v1/responses",
            header_environment={"x-private": "PRIVATE_HEADER"},
        )


def test_redirect_is_not_followed() -> None:
    target_hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path == "/start":
                self.send_response(302)
                self.send_header("location", "/target")
                self.end_headers()
                return
            target_hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        response = UrllibTransport().post(
            url=f"http://{host}:{port}/start",
            headers={"content-type": "application/json"},
            body=b"{}",
            timeout_seconds=2,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert response.status == 302
    assert target_hits == []


def test_urllib_transport_wraps_http_protocol_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise http.client.BadStatusLine("broken")

    monkeypatch.setattr(openai_adapter._OPENER, "open", fail)
    with pytest.raises(ProviderTransportError, match="BadStatusLine"):
        UrllibTransport().post(
            url="https://provider.example/v1/responses",
            headers={},
            body=b"{}",
            timeout_seconds=1,
        )


def test_retry_after_is_finite_and_capped() -> None:
    config = _config(max_retry_after_seconds=0.25, transport_backoff_seconds=[0.1])
    assert openai_adapter._retry_delay(config, 0, {"retry-after": "86400"}) == 0.25
    assert openai_adapter._retry_delay(config, 0, {"retry-after": "inf"}) == 0.1


def test_stateless_responses_replay_only_self_contained_reasoning(
    example_root: Path, tmp_path: Path
) -> None:
    pack_path, execution, stack, condition = _compiled(example_root, tmp_path)
    first = _response(
        {
            "status": "completed",
            "output": [
                {"type": "reasoning", "id": "rs-drop", "encrypted_content": None},
                {"type": "reasoning", "id": "rs-keep", "encrypted_content": "ciphertext"},
                {
                    "type": "function_call",
                    "name": "videobench_write_text_artifact",
                    "arguments": json.dumps({"path": "reasoning.txt", "content": "ok"}),
                    "call_id": "reasoning-call",
                },
            ],
        }
    )
    transport = FakeTransport([first, _final_response()])
    result = run_openai_compatible(
        execution_pack_path=pack_path,
        execution_pack=execution,
        run_stack=stack,
        run_condition=condition,
        config=_config(
            store=False,
            reasoning_effort="medium",
            responses_include=["reasoning.encrypted_content"],
        ),
        asset_root=example_root,
        workspace=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        transport=transport,
    )
    assert result.outcome == OutcomeStatus.PASS
    assert transport.requests[0]["body"]["include"] == ["reasoning.encrypted_content"]
    replay = transport.requests[1]["body"]["input"]
    ids = [item.get("id") for item in replay if item.get("type") == "reasoning"]
    assert ids == ["rs-keep"]
