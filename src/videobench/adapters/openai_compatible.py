"""Receipted OpenAI-compatible model and agent-harness adapter.

The adapter is deliberately outside the benchmark domain contracts. It translates one
provider surface into the generic :class:`UsageRecord`, :class:`RunEvent`, and artifact
protocol without allowing provider-specific response objects to leak into authoring,
verification, judging, scoring, or study analysis.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field, model_validator

from videobench.canonical import (
    resolve_under_root,
    sha256_hex,
    validate_relative_evidence_path,
)
from videobench.contracts import (
    AssetSpec,
    ExecutionPack,
    RunCondition,
    RunEvent,
    RunStack,
    UsageRecord,
)
from videobench.io import write_json
from videobench.types import OutcomeStatus, StrictModel


class OpenAIAPIStyle(StrEnum):
    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"


class RequestTraceMode(StrEnum):
    """How provider request payloads are represented in the durable trace."""

    DIGEST_ONLY = "digest_only"
    REDACTED = "redacted"
    FULL = "full"


class ChatMaxTokensField(StrEnum):
    """Token-limit field used by a Chat Completions-compatible endpoint."""

    MAX_COMPLETION_TOKENS = "max_completion_tokens"
    MAX_TOKENS = "max_tokens"


def _validate_strict_function_schema(schema: Mapping[str, Any], *, path: str = "$") -> None:
    """Validate the JSON Schema subset required by strict function tools."""

    schema_type = schema.get("type")
    is_object = schema_type == "object" or (
        isinstance(schema_type, list) and "object" in schema_type
    )
    if is_object:
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError(f"strict tool schema object at {path} must declare properties")
        if schema.get("additionalProperties") is not False:
            raise ValueError(
                f"strict tool schema object at {path} must set additionalProperties to false"
            )
        required = schema.get("required", [])
        if not isinstance(required, list) or set(required) != set(properties):
            raise ValueError(f"strict tool schema object at {path} must require every property")
        for name, child in properties.items():
            if isinstance(child, Mapping):
                _validate_strict_function_schema(child, path=f"{path}.properties.{name}")

    items = schema.get("items")
    if isinstance(items, Mapping):
        _validate_strict_function_schema(items, path=f"{path}.items")
    for keyword in ("allOf", "anyOf", "oneOf"):
        variants = schema.get(keyword)
        if isinstance(variants, list):
            for index, child in enumerate(variants):
                if isinstance(child, Mapping):
                    _validate_strict_function_schema(child, path=f"{path}.{keyword}[{index}]")
    definitions = schema.get("$defs")
    if isinstance(definitions, Mapping):
        for name, child in definitions.items():
            if isinstance(child, Mapping):
                _validate_strict_function_schema(child, path=f"{path}.$defs.{name}")


def _is_loopback_hostname(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class InlineImageSpec(StrictModel):
    asset_id: str
    detail: str = "auto"
    max_bytes: int = Field(default=10_000_000, ge=1)


class CommandToolSpec(StrictModel):
    """A declared function tool backed by a local command.

    Tool arguments are sent as one JSON object on stdin. The command executes without a
    shell and receives only a small baseline environment plus explicitly allowed names.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    strict: bool = True
    command: list[str] = Field(min_length=1)
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    pass_environment: list[str] = Field(default_factory=list)
    working_directory: str | None = None

    @model_validator(mode="after")
    def validate_paths(self) -> CommandToolSpec:
        if self.working_directory is not None:
            validate_relative_evidence_path(self.working_directory)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.name):
            raise ValueError(
                "command tool names must contain only letters, numbers, underscores, "
                "or hyphens and be at most 64 characters"
            )
        if any(not item for item in self.command):
            raise ValueError("command entries must not be empty")
        if self.parameters.get("type") != "object":
            raise ValueError("command tool parameters must declare an object schema")
        if not isinstance(self.parameters.get("properties", {}), dict):
            raise ValueError("command tool parameters.properties must be an object")
        if self.parameters.get("additionalProperties") is not False:
            raise ValueError("command tool schemas must set additionalProperties to false")
        if self.strict:
            _validate_strict_function_schema(self.parameters)
        return self


class OpenAICompatibleConfig(StrictModel):
    adapter_id: str
    endpoint: str
    api_style: OpenAIAPIStyle = OpenAIAPIStyle.RESPONSES
    api_key_env: str = "OPENAI_API_KEY"
    require_api_key: bool = True
    allow_insecure_http: bool = False
    header_environment: dict[str, str] = Field(default_factory=dict)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    instructions: str = (
        "You are the candidate agent in a VideoBench run. Complete the declared editing "
        "work through the available tools. Durable deliverables must be written below the "
        "declared output root. Do not claim terminal success merely because a tool accepted "
        "a request."
    )
    prompt_prefix: str = ""
    max_model_calls: int = Field(default=8, ge=1)
    max_tool_calls: int = Field(default=64, ge=0)
    request_timeout_seconds: float = Field(default=120.0, gt=0.0)
    transport_max_attempts: int = Field(default=3, ge=1)
    transport_backoff_seconds: list[float] = Field(default_factory=lambda: [0.5, 1.0])
    retry_http_statuses: list[int] = Field(
        default_factory=lambda: [408, 409, 429, 500, 502, 503, 504]
    )
    store: bool | None = False
    reasoning_effort: str | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    chat_max_tokens_field: ChatMaxTokensField = ChatMaxTokensField.MAX_COMPLETION_TOKENS
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    inline_images: list[InlineImageSpec] = Field(default_factory=list)
    command_tools: list[CommandToolSpec] = Field(default_factory=list)
    enable_artifact_tools: bool = True
    enable_asset_reader: bool = True
    max_asset_text_chars: int = Field(default=200_000, ge=1)
    max_tool_result_chars: int = Field(default=100_000, ge=1)
    preserve_raw_responses: bool = True
    request_trace_mode: RequestTraceMode = RequestTraceMode.REDACTED
    final_text_path: str = "provider/final.txt"
    trace_path: str = "provider/trace.json"

    @model_validator(mode="after")
    def validate_configuration(self) -> OpenAICompatibleConfig:
        parsed = urllib.parse.urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("endpoint must be an HTTP or HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("endpoint must not contain credentials")
        if parsed.fragment:
            raise ValueError("endpoint must not contain a URL fragment")
        if (
            parsed.scheme == "http"
            and not self.allow_insecure_http
            and not _is_loopback_hostname(parsed.hostname)
        ):
            raise ValueError(
                "plain HTTP endpoints are limited to loopback unless "
                "allow_insecure_http is explicitly enabled"
            )
        if not self.api_key_env:
            raise ValueError("api_key_env must not be empty")
        validate_relative_evidence_path(self.final_text_path)
        validate_relative_evidence_path(self.trace_path)
        names = [tool.name for tool in self.command_tools]
        reserved = {
            "videobench_write_text_artifact",
            "videobench_write_json_artifact",
            "videobench_read_asset_text",
            "videobench_copy_asset",
        }
        if len(names) != len(set(names)):
            raise ValueError("command tool names must be unique")
        overlap = reserved.intersection(names)
        if overlap:
            raise ValueError(f"command tool names collide with built-ins: {sorted(overlap)}")
        image_ids = [item.asset_id for item in self.inline_images]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("inline image asset IDs must be unique")
        if any(delay < 0 for delay in self.transport_backoff_seconds):
            raise ValueError("transport backoff values must be nonnegative")
        sensitive_headers = {"authorization", "api-key", "x-api-key"}
        literal_sensitive = sensitive_headers.intersection(
            name.lower() for name in self.extra_headers
        )
        if literal_sensitive:
            raise ValueError(
                "sensitive header values must come from api_key_env or "
                f"header_environment, not extra_headers: {sorted(literal_sensitive)}"
            )
        if any(
            not name or not environment for name, environment in self.header_environment.items()
        ):
            raise ValueError("header_environment names and environment variables must not be empty")
        return self


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HTTPTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> TransportResponse: ...


class UrllibTransport:
    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> TransportResponse:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return TransportResponse(
                    status=int(response.status),
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return TransportResponse(
                status=int(error.code),
                headers={key.lower(): value for key, value in error.headers.items()},
                body=error.read(),
            )
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            raise ProviderTransportError(f"{type(error).__name__}: {error}") from error


class ProviderTransportError(RuntimeError):
    pass


class ProviderEnvironmentError(RuntimeError):
    pass


class ProviderProtocolError(RuntimeError):
    pass


@dataclass
class AdapterExecution:
    outcome: OutcomeStatus
    events: list[RunEvent]
    usage: UsageRecord
    stdout: str = ""
    stderr: str = ""
    known_missing_evidence: list[str] | None = None
    notes: list[str] | None = None


@dataclass
class _UsageAccumulator:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    input_known: bool = True
    cached_known: bool = True
    cache_write_known: bool = True
    reasoning_known: bool = True
    output_known: bool = True

    def add(self, values: Mapping[str, int | None]) -> None:
        input_tokens = values.get("input_tokens")
        if input_tokens is None:
            self.input_known = False
        else:
            self.input_tokens += input_tokens

        cached_input_tokens = values.get("cached_input_tokens")
        if cached_input_tokens is None:
            self.cached_known = False
        else:
            self.cached_input_tokens += cached_input_tokens

        cache_write_tokens = values.get("cache_write_tokens")
        if cache_write_tokens is None:
            self.cache_write_known = False
        else:
            self.cache_write_tokens += cache_write_tokens

        reasoning_tokens = values.get("reasoning_tokens")
        if reasoning_tokens is None:
            self.reasoning_known = False
        else:
            self.reasoning_tokens += reasoning_tokens

        output_tokens = values.get("output_tokens")
        if output_tokens is None:
            self.output_known = False
        else:
            self.output_tokens += output_tokens

    def finish(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens if self.input_known else None,
            "cached_input_tokens": (self.cached_input_tokens if self.cached_known else None),
            "cache_write_tokens": (self.cache_write_tokens if self.cache_write_known else None),
            "reasoning_tokens": self.reasoning_tokens if self.reasoning_known else None,
            "output_tokens": self.output_tokens if self.output_known else None,
        }


def _event(events: list[RunEvent], event_type: str, message: str, **data: Any) -> None:
    events.append(
        RunEvent(
            sequence=len(events),
            event_type=event_type,
            message=message,
            data=data,
        )
    )


def _safe_output_path(output_dir: Path, relative: str) -> Path:
    path = resolve_under_root(output_dir, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _asset_by_id(execution_pack: ExecutionPack, asset_id: str) -> AssetSpec:
    for asset in execution_pack.assets:
        if asset.asset_id == asset_id:
            return asset
    raise ValueError(f"Unknown ExecutionPack asset ID: {asset_id}")


def _asset_path(execution_pack: ExecutionPack, asset_root: Path, asset_id: str) -> Path:
    asset = _asset_by_id(execution_pack, asset_id)
    path = resolve_under_root(asset_root, asset.path)
    if not path.is_file():
        raise ValueError(f"ExecutionPack asset is not a regular file: {asset_id}")
    return path


def _execution_prompt(execution_pack: ExecutionPack, config: OpenAICompatibleConfig) -> str:
    assets = (
        "\n".join(
            f"- {asset.asset_id}: {asset.media_type.value}; role={asset.role}; path={asset.path}"
            for asset in execution_pack.assets
        )
        or "- none"
    )
    deliverables = (
        "\n".join(
            f"- {item.deliverable_id}: {item.path}; type={item.media_type.value}; "
            f"editable={item.editable}; {item.description}"
            for item in execution_pack.output_contract.deliverables
        )
        or "- none"
    )
    requirements = (
        "\n".join(f"- {item}" for item in execution_pack.output_contract.requirements) or "- none"
    )
    invariants = (
        "\n".join(f"- {item}" for item in execution_pack.output_contract.protected_invariants)
        or "- none"
    )
    shortcuts = (
        "\n".join(f"- {item}" for item in execution_pack.output_contract.prohibited_shortcuts)
        or "- none"
    )
    constraints = "\n".join(f"- {item}" for item in execution_pack.public_constraints) or "- none"
    prefix = f"{config.prompt_prefix.rstrip()}\n\n" if config.prompt_prefix else ""
    return (
        f"{prefix}VideoBench task `{execution_pack.task_id}` / form "
        f"`{execution_pack.form_id}`.\n\n"
        f"## Brief\n{execution_pack.brief}\n\n"
        f"## Assets\n{assets}\n\n"
        f"## Required deliverables\n{deliverables}\n\n"
        f"## Public requirements\n{requirements}\n\n"
        f"## Protected invariants\n{invariants}\n\n"
        f"## Prohibited shortcuts\n{shortcuts}\n\n"
        f"## Additional constraints\n{constraints}\n\n"
        "Use the tools available in this run. Write durable result artifacts below the "
        "VideoBench output root. Finish with a concise account of what was produced and "
        "any material uncertainty; the benchmark will verify terminal state independently."
    )


def _image_data_url(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"Inline image exceeds declared max_bytes: {path} ({size} > {max_bytes})")
    mime, _ = mimetypes.guess_type(path.name)
    if not mime or not mime.startswith("image/"):
        raise ValueError(f"Inline asset is not an image: {path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _builtin_tool_definitions(config: OpenAICompatibleConfig) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    if config.enable_artifact_tools:
        definitions.extend(
            [
                {
                    "name": "videobench_write_text_artifact",
                    "description": "Write a UTF-8 text artifact below the benchmark output root.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "name": "videobench_write_json_artifact",
                    "description": "Write a JSON artifact below the benchmark output root.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "value": {},
                        },
                        "required": ["path", "value"],
                        "additionalProperties": False,
                    },
                    "strict": False,
                },
                {
                    "name": "videobench_copy_asset",
                    "description": "Copy one declared input asset into the output root.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "asset_id": {"type": "string"},
                            "path": {"type": "string"},
                        },
                        "required": ["asset_id", "path"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            ]
        )
    if config.enable_asset_reader:
        definitions.append(
            {
                "name": "videobench_read_asset_text",
                "description": "Read bounded UTF-8 text from one declared input asset.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "asset_id": {"type": "string"},
                        "max_chars": {"type": ["integer", "null"], "minimum": 1},
                    },
                    "required": ["asset_id", "max_chars"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        )
    return definitions


def _all_tool_definitions(config: OpenAICompatibleConfig) -> list[dict[str, Any]]:
    definitions = _builtin_tool_definitions(config)
    definitions.extend(
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "strict": tool.strict,
        }
        for tool in config.command_tools
    )
    return definitions


def _provider_tools(config: OpenAICompatibleConfig) -> list[dict[str, Any]]:
    definitions = _all_tool_definitions(config)
    if config.api_style == OpenAIAPIStyle.RESPONSES:
        return [
            {
                "type": "function",
                "name": item["name"],
                "description": item["description"],
                "parameters": item["parameters"],
                "strict": item["strict"],
            }
            for item in definitions
        ]
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["parameters"],
                "strict": item["strict"],
            },
        }
        for item in definitions
    ]


def _initial_conversation(
    *,
    execution_pack: ExecutionPack,
    asset_root: Path,
    config: OpenAICompatibleConfig,
) -> list[dict[str, Any]]:
    prompt = _execution_prompt(execution_pack, config)
    if config.api_style == OpenAIAPIStyle.RESPONSES:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for item in config.inline_images:
            path = _asset_path(execution_pack, asset_root, item.asset_id)
            content.append(
                {
                    "type": "input_image",
                    "image_url": _image_data_url(path, item.max_bytes),
                    "detail": item.detail,
                }
            )
        return [{"role": "user", "content": content}]

    chat_content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for item in config.inline_images:
        path = _asset_path(execution_pack, asset_root, item.asset_id)
        chat_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": _image_data_url(path, item.max_bytes),
                    "detail": item.detail,
                },
            }
        )
    return [
        {"role": "system", "content": config.instructions},
        {"role": "user", "content": chat_content},
    ]


def _request_body(
    *,
    config: OpenAICompatibleConfig,
    run_stack: RunStack,
    conversation: list[dict[str, Any]],
) -> dict[str, Any]:
    tools = _provider_tools(config)
    if config.api_style == OpenAIAPIStyle.RESPONSES:
        body: dict[str, Any] = {
            "model": run_stack.system.model,
            "instructions": config.instructions,
            "input": conversation,
        }
        if config.store is not None:
            body["store"] = config.store
        if tools:
            body["tools"] = tools
        if config.reasoning_effort is not None:
            body["reasoning"] = {"effort": config.reasoning_effort}
        if config.max_output_tokens is not None:
            body["max_output_tokens"] = config.max_output_tokens
        if config.temperature is not None:
            body["temperature"] = config.temperature
        return body

    body = {
        "model": run_stack.system.model,
        "messages": conversation,
    }
    if config.store is not None:
        body["store"] = config.store
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if config.max_output_tokens is not None:
        body[config.chat_max_tokens_field.value] = config.max_output_tokens
    if config.reasoning_effort is not None:
        body["reasoning_effort"] = config.reasoning_effort
    if config.temperature is not None:
        body["temperature"] = config.temperature
    return body


def _headers(config: OpenAICompatibleConfig) -> dict[str, str]:
    headers = {"content-type": "application/json", **config.extra_headers}
    api_key = os.environ.get(config.api_key_env)
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    elif config.require_api_key:
        raise ProviderEnvironmentError(
            f"Required API key environment variable is missing: {config.api_key_env}"
        )
    for header, environment_name in config.header_environment.items():
        value = os.environ.get(environment_name)
        if value is None:
            raise ProviderEnvironmentError(
                f"Required header environment variable is missing: {environment_name}"
            )
        headers[header] = value
    return headers


def _redact_data_url(value: str) -> str:
    if not value.startswith("data:") or ";base64," not in value:
        return value
    prefix, encoded = value.split(",", 1)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return f"{prefix},<redacted-invalid-base64>"
    digest = hashlib.sha256(raw).hexdigest()
    return f"{prefix},<redacted sha256={digest} bytes={len(raw)}>"


def _redact_request(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_data_url(value)
    if isinstance(value, list):
        return [_redact_request(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_request(item) for key, item in value.items()}
    return value


def _request_trace(body: dict[str, Any], mode: RequestTraceMode) -> dict[str, Any]:
    record: dict[str, Any] = {"request_sha256": sha256_hex(body)}
    if mode == RequestTraceMode.REDACTED:
        record["request"] = _redact_request(body)
    elif mode == RequestTraceMode.FULL:
        record["request"] = body
    return record


def _decode_json(response: TransportResponse) -> dict[str, Any]:
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderProtocolError(f"Provider returned invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ProviderProtocolError("Provider response must be a JSON object")
    return value


def _attach_response_body_evidence(
    record: dict[str, Any],
    response: TransportResponse,
    *,
    preserve_raw: bool,
) -> str:
    decoded = response.body.decode("utf-8", errors="replace")
    if preserve_raw:
        record["response_text"] = decoded
    else:
        record["response_sha256"] = hashlib.sha256(response.body).hexdigest()
        record["response_bytes"] = len(response.body)
    return decoded


def _usage_values(payload: Mapping[str, Any], style: OpenAIAPIStyle) -> dict[str, int | None]:
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return {
            "input_tokens": None,
            "cached_input_tokens": None,
            "cache_write_tokens": None,
            "reasoning_tokens": None,
            "output_tokens": None,
        }
    if style == OpenAIAPIStyle.RESPONSES:
        input_details = usage.get("input_tokens_details")
        output_details = usage.get("output_tokens_details")
        return {
            "input_tokens": _optional_int(usage.get("input_tokens")),
            "cached_input_tokens": _nested_optional_int(input_details, "cached_tokens"),
            "cache_write_tokens": _nested_optional_int(input_details, "cache_write_tokens"),
            "reasoning_tokens": _nested_optional_int(output_details, "reasoning_tokens"),
            "output_tokens": _optional_int(usage.get("output_tokens")),
        }
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    return {
        "input_tokens": _optional_int(usage.get("prompt_tokens")),
        "cached_input_tokens": _nested_optional_int(prompt_details, "cached_tokens"),
        "cache_write_tokens": _nested_optional_int(prompt_details, "cache_write_tokens"),
        "reasoning_tokens": _nested_optional_int(completion_details, "reasoning_tokens"),
        "output_tokens": _optional_int(usage.get("completion_tokens")),
    }


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _nested_optional_int(value: Any, key: str) -> int | None:
    if not isinstance(value, Mapping):
        return None
    return _optional_int(value.get(key))


def _parse_responses_output(payload: Mapping[str, Any]) -> tuple[str, list[dict[str, str]]]:
    output = payload.get("output")
    if not isinstance(output, list):
        raise ProviderProtocolError("Responses payload is missing an output list")
    texts: list[str] = []
    calls: list[dict[str, str]] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type == "function_call":
            name = item.get("name")
            arguments = item.get("arguments")
            call_id = item.get("call_id") or item.get("id")
            if (
                not isinstance(name, str)
                or not isinstance(arguments, str)
                or not isinstance(call_id, str)
            ):
                raise ProviderProtocolError("Malformed Responses function call")
            calls.append({"name": name, "arguments": arguments, "call_id": call_id})
        elif item_type == "message":
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, Mapping) and part.get("type") == "output_text":
                        text = part.get("text")
                        if isinstance(text, str):
                            texts.append(text)
    return "\n".join(texts).strip(), calls


def _parse_chat_output(
    payload: Mapping[str, Any],
) -> tuple[str, list[dict[str, str]], dict[str, Any]]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ProviderProtocolError("Chat Completions payload is missing choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise ProviderProtocolError("Chat Completions payload is missing a message")
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    calls: list[dict[str, str]] = []
    tool_calls = message.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        raise ProviderProtocolError("Chat Completions tool_calls must be a list")
    for item in tool_calls:
        if not isinstance(item, Mapping):
            raise ProviderProtocolError("Malformed Chat Completions tool call")
        function = item.get("function")
        call_id = item.get("id")
        if not isinstance(function, Mapping) or not isinstance(call_id, str):
            raise ProviderProtocolError("Malformed Chat Completions tool call")
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, str):
            raise ProviderProtocolError("Malformed Chat Completions function payload")
        calls.append({"name": name, "arguments": arguments, "call_id": call_id})
    return text.strip(), calls, dict(message)


def _tool_result_for_model(value: dict[str, Any], max_chars: int) -> str:
    rendered = json.dumps(value, sort_keys=True, ensure_ascii=False)
    if len(rendered) <= max_chars:
        return rendered
    return json.dumps(
        {
            "truncated": True,
            "original_chars": len(rendered),
            "prefix": rendered[:max_chars],
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _baseline_command_environment() -> dict[str, str]:
    permitted = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "HOME",
        "USERPROFILE",
        "TMP",
        "TEMP",
        "TMPDIR",
    }
    return {name: value for name, value in os.environ.items() if name in permitted}


def _execute_tool(
    *,
    name: str,
    arguments_text: str,
    call_id: str,
    execution_pack: ExecutionPack,
    run_stack: RunStack,
    run_condition: RunCondition,
    asset_root: Path,
    workspace: Path,
    output_dir: Path,
    config: OpenAICompatibleConfig,
    remaining_wall_seconds: float | None = None,
) -> dict[str, Any]:
    try:
        arguments = json.loads(arguments_text or "{}")
    except json.JSONDecodeError as error:
        return {"ok": False, "error": "invalid_tool_arguments", "detail": str(error)}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "tool_arguments_must_be_object"}

    try:
        if name == "videobench_write_text_artifact":
            path = _safe_output_path(output_dir, str(arguments["path"]))
            content = arguments["content"]
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            path.write_text(content, encoding="utf-8")
            return {"ok": True, "path": path.relative_to(output_dir).as_posix()}
        if name == "videobench_write_json_artifact":
            path = _safe_output_path(output_dir, str(arguments["path"]))
            write_json(path, arguments["value"])
            return {"ok": True, "path": path.relative_to(output_dir).as_posix()}
        if name == "videobench_read_asset_text":
            path = _asset_path(execution_pack, asset_root, str(arguments["asset_id"]))
            requested_max_chars = arguments.get("max_chars")
            max_chars = (
                config.max_asset_text_chars
                if requested_max_chars is None
                else int(requested_max_chars)
            )
            max_chars = min(max_chars, config.max_asset_text_chars)
            text = path.read_text(encoding="utf-8")
            return {
                "ok": True,
                "asset_id": arguments["asset_id"],
                "text": text[:max_chars],
                "truncated": len(text) > max_chars,
                "total_chars": len(text),
            }
        if name == "videobench_copy_asset":
            source = _asset_path(execution_pack, asset_root, str(arguments["asset_id"]))
            destination = _safe_output_path(output_dir, str(arguments["path"]))
            shutil.copy2(source, destination)
            return {"ok": True, "path": destination.relative_to(output_dir).as_posix()}
    except (KeyError, TypeError, ValueError, OSError, UnicodeDecodeError) as error:
        return {"ok": False, "error": type(error).__name__, "detail": str(error)}

    command_tool = next((item for item in config.command_tools if item.name == name), None)
    if command_tool is None:
        return {"ok": False, "error": "unknown_tool", "tool": name}

    if command_tool.working_directory is None:
        cwd = workspace
    else:
        cwd = resolve_under_root(workspace, command_tool.working_directory)
        cwd.mkdir(parents=True, exist_ok=True)
    environment = _baseline_command_environment()
    for environment_name in command_tool.pass_environment:
        value = os.environ.get(environment_name)
        if value is not None:
            environment[environment_name] = value
    environment.update(
        {
            "VIDEOBENCH_TOOL_NAME": name,
            "VIDEOBENCH_TOOL_CALL_ID": call_id,
            "VIDEOBENCH_OUTPUT_DIR": str(output_dir.resolve()),
            "VIDEOBENCH_WORKSPACE": str(workspace.resolve()),
            "VIDEOBENCH_ASSET_ROOT": str(asset_root.resolve()),
            "VIDEOBENCH_ATTEMPT_ID": run_condition.attempt_id,
            "VIDEOBENCH_STACK_ID": run_stack.stack_id,
        }
    )
    timeout_seconds = command_tool.timeout_seconds
    if remaining_wall_seconds is not None:
        timeout_seconds = min(timeout_seconds, max(0.0, remaining_wall_seconds))
    if timeout_seconds <= 0:
        return {
            "ok": False,
            "error": "wall_time_exhausted",
            "timeout_seconds": 0.0,
            "duration_seconds": 0.0,
        }
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command_tool.command,
            input=json.dumps(arguments, sort_keys=True, ensure_ascii=False),
            text=True,
            capture_output=True,
            cwd=cwd,
            env=environment,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_seconds": time.perf_counter() - started,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "ok": False,
            "error": "tool_timeout",
            "timeout_seconds": timeout_seconds,
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
            "duration_seconds": time.perf_counter() - started,
        }
    except OSError as error:
        return {
            "ok": False,
            "error": type(error).__name__,
            "detail": str(error),
            "duration_seconds": time.perf_counter() - started,
        }


def _retry_delay(
    config: OpenAICompatibleConfig, retry_index: int, headers: Mapping[str, str]
) -> float:
    retry_after = headers.get("retry-after")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    if not config.transport_backoff_seconds:
        return 0.0
    return config.transport_backoff_seconds[
        min(retry_index, len(config.transport_backoff_seconds) - 1)
    ]


def _remaining_wall_seconds(start: float, run_stack: RunStack) -> float | None:
    limit = run_stack.resource_envelope.max_wall_seconds
    if limit is None:
        return None
    return max(0.0, limit - (time.perf_counter() - start))


def _token_budget_failures(
    usage: Mapping[str, int | None], run_stack: RunStack
) -> list[dict[str, str | int]]:
    failures: list[dict[str, str | int]] = []
    for resource, limit, actual in (
        ("input_tokens", run_stack.resource_envelope.max_input_tokens, usage["input_tokens"]),
        (
            "output_tokens",
            run_stack.resource_envelope.max_output_tokens,
            usage["output_tokens"],
        ),
    ):
        if limit is not None and actual is not None and actual > limit:
            failures.append({"resource": resource, "limit": limit, "actual": actual})
    return failures


def execute_openai_compatible(
    *,
    execution_pack: ExecutionPack,
    run_stack: RunStack,
    run_condition: RunCondition,
    config: OpenAICompatibleConfig,
    asset_root: Path,
    workspace: Path,
    output_dir: Path,
    transport: HTTPTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    cancellation_check: Callable[[], bool] | None = None,
) -> AdapterExecution:
    """Execute one receipted provider/harness attempt.

    The caller owns output-directory freshness and final WorkResultBundle construction.
    This function never reads verifier or judge artifacts.
    """

    transport = transport or UrllibTransport()
    cancellation_check = cancellation_check or (lambda: False)
    workspace.mkdir(parents=True, exist_ok=True)
    events: list[RunEvent] = []
    _event(
        events,
        "provider_run_started",
        "OpenAI-compatible provider run started.",
        adapter_id=config.adapter_id,
        api_style=config.api_style.value,
        endpoint=config.endpoint,
    )
    start = time.perf_counter()
    trace: dict[str, Any] = {
        "adapter_id": config.adapter_id,
        "api_style": config.api_style.value,
        "endpoint": config.endpoint,
        "model": run_stack.system.model,
        "request_trace_mode": config.request_trace_mode.value,
        "requests": [],
        "tool_calls": [],
    }
    usage_accumulator = _UsageAccumulator()
    logical_calls = 0
    transport_retries = 0
    tool_calls = 0
    http_request_ids: list[str] = []
    provider_response_ids: list[str] = []
    final_text = ""
    outcome = OutcomeStatus.PASS
    stderr = ""
    known_missing: list[str] = []

    try:
        conversation = _initial_conversation(
            execution_pack=execution_pack,
            asset_root=asset_root,
            config=config,
        )
    except (OSError, UnicodeDecodeError, ValueError) as error:
        conversation = []
        outcome = OutcomeStatus.PROTOCOL_INVALID
        stderr = f"{type(error).__name__}: {error}"
        _event(
            events,
            "provider_input_invalid",
            "Provider input could not be constructed from the declared execution pack.",
            error=stderr,
        )

    provider_headers: dict[str, str] = {}
    if outcome == OutcomeStatus.PASS:
        try:
            provider_headers = _headers(config)
        except ProviderEnvironmentError as error:
            outcome = OutcomeStatus.ENVIRONMENT_BLOCKED
            stderr = str(error)
            _event(
                events,
                "provider_environment_blocked",
                "Provider credentials or required headers were unavailable.",
                error=stderr,
            )

    effective_model_limit = config.max_model_calls
    if run_stack.resource_envelope.max_model_calls is not None:
        effective_model_limit = min(
            effective_model_limit,
            run_stack.resource_envelope.max_model_calls,
        )
    effective_tool_limit = config.max_tool_calls
    if run_stack.resource_envelope.max_tool_calls is not None:
        effective_tool_limit = min(
            effective_tool_limit,
            run_stack.resource_envelope.max_tool_calls,
        )

    try:
        while outcome == OutcomeStatus.PASS:
            if cancellation_check():
                outcome = OutcomeStatus.HUMAN_ABORT
                _event(events, "provider_run_cancelled", "Provider run was cancelled.")
                break

            remaining_wall = _remaining_wall_seconds(start, run_stack)
            if remaining_wall is not None and remaining_wall <= 0:
                outcome = OutcomeStatus.TIMED_OUT
                _event(
                    events,
                    "wall_time_budget_exhausted",
                    "Provider run exhausted the declared wall-time budget.",
                    limit=run_stack.resource_envelope.max_wall_seconds,
                )
                break

            if logical_calls >= effective_model_limit:
                outcome = OutcomeStatus.BUDGET_EXHAUSTED
                _event(
                    events,
                    "model_call_budget_exhausted",
                    "Provider run exhausted the declared model-call budget.",
                    limit=effective_model_limit,
                )
                break

            body = _request_body(
                config=config,
                run_stack=run_stack,
                conversation=conversation,
            )
            logical_calls += 1
            _event(
                events,
                "provider_request_started",
                "Provider request started.",
                logical_call=logical_calls,
            )
            response: TransportResponse | None = None
            last_transport_error: str | None = None

            for transport_attempt in range(config.transport_max_attempts):
                remaining_wall = _remaining_wall_seconds(start, run_stack)
                if remaining_wall is not None and remaining_wall <= 0:
                    outcome = OutcomeStatus.TIMED_OUT
                    _event(
                        events,
                        "wall_time_budget_exhausted",
                        "Provider run exhausted the declared wall-time budget.",
                        limit=run_stack.resource_envelope.max_wall_seconds,
                    )
                    break
                request_timeout = config.request_timeout_seconds
                if remaining_wall is not None:
                    request_timeout = min(request_timeout, remaining_wall)

                try:
                    response = transport.post(
                        url=config.endpoint,
                        headers=provider_headers,
                        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                        timeout_seconds=request_timeout,
                    )
                    if (
                        response.status in config.retry_http_statuses
                        and transport_attempt + 1 < config.transport_max_attempts
                    ):
                        delay = _retry_delay(config, transport_attempt, response.headers)
                        remaining_wall = _remaining_wall_seconds(start, run_stack)
                        if remaining_wall is not None:
                            delay = min(delay, remaining_wall)
                        transport_retries += 1
                        _event(
                            events,
                            "provider_transport_retry",
                            "Retrying provider request after retryable HTTP status.",
                            logical_call=logical_calls,
                            status=response.status,
                            retry_number=transport_retries,
                            delay_seconds=delay,
                        )
                        sleep(delay)
                        response = None
                        continue
                    break
                except ProviderTransportError as error:
                    last_transport_error = str(error)
                    if transport_attempt + 1 >= config.transport_max_attempts:
                        break
                    delay = _retry_delay(config, transport_attempt, {})
                    remaining_wall = _remaining_wall_seconds(start, run_stack)
                    if remaining_wall is not None:
                        delay = min(delay, remaining_wall)
                    transport_retries += 1
                    _event(
                        events,
                        "provider_transport_retry",
                        "Retrying provider request after transport failure.",
                        logical_call=logical_calls,
                        error=last_transport_error,
                        retry_number=transport_retries,
                        delay_seconds=delay,
                    )
                    sleep(delay)

            if outcome != OutcomeStatus.PASS:
                break
            if response is None:
                timed_out = bool(
                    last_transport_error
                    and any(
                        token in last_transport_error.lower() for token in ("timed out", "timeout")
                    )
                )
                outcome = OutcomeStatus.TIMED_OUT if timed_out else OutcomeStatus.TOOL_FAILURE
                stderr = last_transport_error or ("Provider transport failed without a response.")
                _event(
                    events,
                    "provider_transport_failed",
                    "Provider transport attempts were exhausted.",
                    logical_call=logical_calls,
                    error=stderr,
                )
                break

            request_id = response.headers.get("x-request-id")
            if request_id:
                http_request_ids.append(request_id)
            response_record: dict[str, Any] = {
                "logical_call": logical_calls,
                "status": response.status,
                "request_id": request_id,
                **_request_trace(body, config.request_trace_mode),
            }
            if response.status < 200 or response.status >= 300:
                decoded_error = _attach_response_body_evidence(
                    response_record,
                    response,
                    preserve_raw=config.preserve_raw_responses,
                )
                trace["requests"].append(response_record)
                event_type = (
                    "provider_rate_limited" if response.status == 429 else "provider_http_error"
                )
                _event(
                    events,
                    event_type,
                    "Provider returned a non-success HTTP response.",
                    logical_call=logical_calls,
                    status=response.status,
                    request_id=request_id,
                )
                outcome = OutcomeStatus.TOOL_FAILURE
                stderr = (
                    decoded_error
                    if config.preserve_raw_responses
                    else f"Provider returned HTTP {response.status}; response body withheld."
                )
                break

            try:
                payload = _decode_json(response)
                usage_accumulator.add(_usage_values(payload, config.api_style))
                provider_response_id = payload.get("id")
                if isinstance(provider_response_id, str):
                    provider_response_ids.append(provider_response_id)

                if config.api_style == OpenAIAPIStyle.RESPONSES:
                    parsed_text, pending_calls = _parse_responses_output(payload)
                    output_items = payload.get("output")
                    if isinstance(output_items, list):
                        conversation.extend(
                            dict(item) for item in output_items if isinstance(item, Mapping)
                        )
                else:
                    parsed_text, pending_calls, assistant_message = _parse_chat_output(payload)
                    conversation.append(assistant_message)

                if parsed_text:
                    final_text = parsed_text
                if config.preserve_raw_responses:
                    response_record["response"] = payload
                else:
                    response_record["response_id"] = provider_response_id
                    response_record["usage"] = payload.get("usage")
                    response_record["output_text"] = parsed_text
                trace["requests"].append(response_record)
            except ProviderProtocolError as error:
                _attach_response_body_evidence(
                    response_record,
                    response,
                    preserve_raw=config.preserve_raw_responses,
                )
                trace["requests"].append(response_record)
                outcome = OutcomeStatus.PROTOCOL_INVALID
                stderr = str(error)
                _event(
                    events,
                    "provider_protocol_invalid",
                    "Provider response did not satisfy the configured API protocol.",
                    logical_call=logical_calls,
                    error=stderr,
                )
                break

            token_failures = _token_budget_failures(
                usage_accumulator.finish(),
                run_stack,
            )
            if token_failures:
                outcome = OutcomeStatus.BUDGET_EXHAUSTED
                _event(
                    events,
                    "token_budget_exhausted",
                    "Provider run exceeded a declared token budget.",
                    failures=token_failures,
                )
                break

            _event(
                events,
                "provider_response_received",
                "Provider response received.",
                logical_call=logical_calls,
                request_id=request_id,
                tool_calls=len(pending_calls),
                final_text=bool(parsed_text),
            )
            if not pending_calls:
                break

            tool_outputs: list[tuple[dict[str, str], dict[str, Any]]] = []
            for pending in pending_calls:
                remaining_wall = _remaining_wall_seconds(start, run_stack)
                if remaining_wall is not None and remaining_wall <= 0:
                    outcome = OutcomeStatus.TIMED_OUT
                    _event(
                        events,
                        "wall_time_budget_exhausted",
                        "Provider run exhausted the declared wall-time budget.",
                        limit=run_stack.resource_envelope.max_wall_seconds,
                    )
                    break
                if tool_calls >= effective_tool_limit:
                    outcome = OutcomeStatus.BUDGET_EXHAUSTED
                    _event(
                        events,
                        "tool_call_budget_exhausted",
                        "Provider run exhausted the declared tool-call budget.",
                        limit=effective_tool_limit,
                    )
                    break
                tool_calls += 1
                _event(
                    events,
                    "tool_call_started",
                    "Provider-requested tool call started.",
                    tool=pending["name"],
                    call_id=pending["call_id"],
                    tool_call=tool_calls,
                )
                result = _execute_tool(
                    name=pending["name"],
                    arguments_text=pending["arguments"],
                    call_id=pending["call_id"],
                    execution_pack=execution_pack,
                    run_stack=run_stack,
                    run_condition=run_condition,
                    asset_root=asset_root,
                    workspace=workspace,
                    output_dir=output_dir,
                    config=config,
                    remaining_wall_seconds=remaining_wall,
                )
                trace["tool_calls"].append(
                    {
                        "name": pending["name"],
                        "call_id": pending["call_id"],
                        "arguments": pending["arguments"],
                        "result": result,
                    }
                )
                _event(
                    events,
                    "tool_call_finished",
                    "Provider-requested tool call finished.",
                    tool=pending["name"],
                    call_id=pending["call_id"],
                    ok=bool(result.get("ok")),
                    tool_call=tool_calls,
                )
                if result.get("error") == "wall_time_exhausted":
                    outcome = OutcomeStatus.TIMED_OUT
                    _event(
                        events,
                        "wall_time_budget_exhausted",
                        "Provider run exhausted the declared wall-time budget.",
                        limit=run_stack.resource_envelope.max_wall_seconds,
                    )
                    break
                tool_outputs.append((pending, result))
            if outcome != OutcomeStatus.PASS:
                break

            for pending, result in tool_outputs:
                rendered = _tool_result_for_model(
                    result,
                    config.max_tool_result_chars,
                )
                if config.api_style == OpenAIAPIStyle.RESPONSES:
                    conversation.append(
                        {
                            "type": "function_call_output",
                            "call_id": pending["call_id"],
                            "output": rendered,
                        }
                    )
                else:
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": pending["call_id"],
                            "name": pending["name"],
                            "content": rendered,
                        }
                    )
    except KeyboardInterrupt:
        outcome = OutcomeStatus.HUMAN_ABORT
        _event(
            events,
            "provider_run_interrupted",
            "Provider run was interrupted locally.",
        )

    elapsed = time.perf_counter() - start
    usage_values = usage_accumulator.finish()
    for field_name, value in usage_values.items():
        if value is None:
            known_missing.append(f"{field_name}_not_reported")
    known_missing.extend(
        [
            "candidate_cost_not_reported",
            "image_units_not_reported",
            "video_units_not_reported",
            "active_agent_seconds_not_reported",
        ]
    )
    known_missing = sorted(set(known_missing))
    usage = UsageRecord(
        input_tokens=usage_values["input_tokens"],
        cached_input_tokens=usage_values["cached_input_tokens"],
        cache_write_tokens=usage_values["cache_write_tokens"],
        reasoning_tokens=usage_values["reasoning_tokens"],
        output_tokens=usage_values["output_tokens"],
        image_units=None,
        video_units=None,
        model_calls=logical_calls,
        tool_calls=tool_calls,
        transport_retries=transport_retries,
        wall_seconds=elapsed,
        active_agent_seconds=None,
        actual_candidate_cost_usd=None,
        metadata={
            "adapter_id": config.adapter_id,
            "api_style": config.api_style.value,
            "endpoint": config.endpoint,
            "http_request_ids": sorted(set(http_request_ids)),
            "provider_response_ids": sorted(set(provider_response_ids)),
            "provider_requests": logical_calls + transport_retries,
        },
    )
    if final_text:
        _safe_output_path(output_dir, config.final_text_path).write_text(
            final_text,
            encoding="utf-8",
        )
    _event(
        events,
        "provider_run_finished",
        "OpenAI-compatible provider run finished.",
        outcome=outcome.value,
        model_calls=logical_calls,
        tool_calls=tool_calls,
        transport_retries=transport_retries,
    )
    trace["outcome"] = outcome.value
    trace["usage"] = usage.model_dump(mode="json", exclude_none=False)
    trace["known_missing_evidence"] = known_missing
    trace["events"] = [item.model_dump(mode="json") for item in events]
    write_json(_safe_output_path(output_dir, config.trace_path), trace)
    return AdapterExecution(
        outcome=outcome,
        events=events,
        usage=usage,
        stdout=final_text,
        stderr=stderr,
        known_missing_evidence=known_missing,
        notes=[
            "Provider request digests, configured request representations, tool calls, "
            "and raw usage are preserved in the adapter trace."
        ],
    )
