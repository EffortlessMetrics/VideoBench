from __future__ import annotations

from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement target, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


adapter = "src/videobench/adapters/openai_compatible.py"
replace(adapter, "import hashlib\n", "import hashlib\nimport ipaddress\n")
replace(
    adapter,
    '''class InlineImageSpec(StrictModel):
    asset_id: str
    detail: str = "auto"
    max_bytes: int = Field(default=10_000_000, ge=1)


''',
    '''def _validate_strict_function_schema(
    schema: Mapping[str, Any], *, path: str = "$"
) -> None:
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
            raise ValueError(
                f"strict tool schema object at {path} must require every property"
            )
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
                    _validate_strict_function_schema(
                        child, path=f"{path}.{keyword}[{index}]"
                    )
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


''',
)
replace(
    adapter,
    '''    parameters: dict[str, Any]
    command: list[str] = Field(min_length=1)
''',
    '''    parameters: dict[str, Any]
    strict: bool = True
    command: list[str] = Field(min_length=1)
''',
)
replace(
    adapter,
    '''        if self.parameters.get("additionalProperties") is not False:
            raise ValueError("strict command tool schemas must set additionalProperties to false")
        return self
''',
    '''        if self.parameters.get("additionalProperties") is not False:
            raise ValueError("command tool schemas must set additionalProperties to false")
        if self.strict:
            _validate_strict_function_schema(self.parameters)
        return self
''',
)
replace(
    adapter,
    '''    api_key_env: str = "OPENAI_API_KEY"
    require_api_key: bool = True
''',
    '''    api_key_env: str = "OPENAI_API_KEY"
    require_api_key: bool = True
    allow_insecure_http: bool = False
''',
)
replace(
    adapter,
    '''        if parsed.username is not None or parsed.password is not None:
            raise ValueError("endpoint must not contain credentials")
''',
    '''        if parsed.username is not None or parsed.password is not None:
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
''',
)
replace(
    adapter,
    '''                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "videobench_write_json_artifact",
''',
    '''                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "name": "videobench_write_json_artifact",
''',
)
replace(
    adapter,
    '''                        "required": ["path", "value"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "videobench_copy_asset",
''',
    '''                        "required": ["path", "value"],
                        "additionalProperties": False,
                    },
                    "strict": False,
                },
                {
                    "name": "videobench_copy_asset",
''',
)
replace(
    adapter,
    '''                        "required": ["asset_id", "path"],
                        "additionalProperties": False,
                    },
                },
''',
    '''                        "required": ["asset_id", "path"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
''',
)
replace(
    adapter,
    '''                        "asset_id": {"type": "string"},
                        "max_chars": {"type": "integer", "minimum": 1},
                    },
                    "required": ["asset_id"],
                    "additionalProperties": False,
                },
            }
''',
    '''                        "asset_id": {"type": "string"},
                        "max_chars": {"type": ["integer", "null"], "minimum": 1},
                    },
                    "required": ["asset_id", "max_chars"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
''',
)
replace(
    adapter,
    '''            "description": tool.description,
            "parameters": tool.parameters,
        }
''',
    '''            "description": tool.description,
            "parameters": tool.parameters,
            "strict": tool.strict,
        }
''',
)
replace(
    adapter,
    '''                "parameters": item["parameters"],
                "strict": True,
            }
            for item in definitions
''',
    '''                "parameters": item["parameters"],
                "strict": item["strict"],
            }
            for item in definitions
''',
)
replace(
    adapter,
    '''                "parameters": item["parameters"],
                "strict": True,
            },
        }
''',
    '''                "parameters": item["parameters"],
                "strict": item["strict"],
            },
        }
''',
)
replace(
    adapter,
    '''def _usage_values(payload: Mapping[str, Any], style: OpenAIAPIStyle) -> dict[str, int | None]:
''',
    '''def _attach_response_body_evidence(
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
''',
)
replace(
    adapter,
    '''            max_chars = int(arguments.get("max_chars", config.max_asset_text_chars))
            max_chars = min(max_chars, config.max_asset_text_chars)
''',
    '''            requested_max_chars = arguments.get("max_chars")
            max_chars = (
                config.max_asset_text_chars
                if requested_max_chars is None
                else int(requested_max_chars)
            )
            max_chars = min(max_chars, config.max_asset_text_chars)
''',
)
replace(
    adapter,
    '''                response_record["response_text"] = response.body.decode(
                    "utf-8",
                    errors="replace",
                )
                trace["requests"].append(response_record)
                event_type = (
''',
    '''                decoded_error = _attach_response_body_evidence(
                    response_record,
                    response,
                    preserve_raw=config.preserve_raw_responses,
                )
                trace["requests"].append(response_record)
                event_type = (
''',
)
replace(
    adapter,
    '''                stderr = response_record["response_text"]
                break
''',
    '''                stderr = (
                    decoded_error
                    if config.preserve_raw_responses
                    else f"Provider returned HTTP {response.status}; response body withheld."
                )
                break
''',
)
replace(
    adapter,
    '''                response_record["response_text"] = response.body.decode(
                    "utf-8",
                    errors="replace",
                )
                trace["requests"].append(response_record)
                outcome = OutcomeStatus.PROTOCOL_INVALID
''',
    '''                _attach_response_body_evidence(
                    response_record,
                    response,
                    preserve_raw=config.preserve_raw_responses,
                )
                trace["requests"].append(response_record)
                outcome = OutcomeStatus.PROTOCOL_INVALID
''',
)

tests = Path("tests/test_openai_compatible_adapter.py")
test_text = tests.read_text(encoding="utf-8")
if "test_provider_tool_strict_flags_are_schema_compatible" in test_text:
    raise SystemExit("provider contract tests already present")
test_text += '''


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
        transport=FakeTransport(
            [TransportResponse(status=400, headers={}, body=secret_body)]
        ),
    )
    assert result.outcome == OutcomeStatus.TOOL_FAILURE
    assert "private-provider-detail" not in result.stderr
    trace = json.loads((tmp_path / "output/provider/trace.json").read_text())
    request = trace["requests"][0]
    assert "response_text" not in request
    assert request["response_bytes"] == len(secret_body)
    assert request["response_sha256"]
    assert "private-provider-detail" not in json.dumps(trace)
'''
tests.write_text(test_text, encoding="utf-8")

replace(
    "docs/PROVIDER_ADAPTERS.md",
    '''- endpoint URLs containing user information are rejected.
- request traces never contain outbound headers.

Set `require_api_key: false` only for an endpoint that intentionally accepts unauthenticated local requests.
''',
    '''- endpoint URLs containing user information or fragments are rejected.
- plain HTTP is limited to loopback hosts by default; a non-loopback HTTP endpoint requires an explicit `allow_insecure_http: true` declaration.
- request traces never contain outbound headers.

Set `require_api_key: false` only for an endpoint that intentionally accepts unauthenticated local requests. Prefer HTTPS whenever a credential or private source material leaves the workstation.
''',
)
replace(
    "docs/PROVIDER_ADAPTERS.md",
    '''`preserve_raw_responses: true` retains complete provider JSON responses. When false, the trace keeps response identifiers, usage, parsed output text, and executed tool calls without retaining the complete response object. The source pack's confidentiality and redistribution policy still governs whether a resulting trace may be published.
''',
    '''`preserve_raw_responses: true` retains complete provider JSON responses. When false, successful traces keep response identifiers, usage, parsed output text, and executed tool calls without retaining the complete response object; HTTP and protocol-error bodies are replaced by their SHA-256 digest and byte count and are not copied into stderr. The source pack's confidentiality and redistribution policy still governs whether a resulting trace may be published.
''',
)
replace(
    "docs/PROVIDER_ADAPTERS.md",
    '''Tool names and parameter schemas are validated before the run. Strict schemas must describe an object and set `additionalProperties: false`.
''',
    '''Tool names and parameter schemas are validated before the run. Command tools default to `strict: true`. Every object in a strict schema must set `additionalProperties: false`, and every declared property must appear in `required`; a logically optional value is represented as a required nullable field. Set `strict: false` only when a compatible endpoint or a deliberately open value shape cannot satisfy that subset. The built-in arbitrary-JSON artifact writer is intentionally non-strict; the other built-ins use strict-compatible schemas.
''',
)
replace(
    "CHANGELOG.md",
    '''  loops, bounded artifact/asset tools, declarative command tools, resource envelopes, and
  credential-free transport tests.
''',
    '''  loops, bounded artifact/asset tools, declarative command tools, resource envelopes,
  per-tool strict-schema validation, loopback-only plain HTTP defaults, complete raw-response
  opt-out, and credential-free transport tests.
''',
)

Path("VERIFICATION_FAILURE.txt").unlink(missing_ok=True)
Path(".github/workflows/harden-provider-live-contract.yml").unlink()
Path(".github/scripts/harden_provider_live_contract.py").unlink()
