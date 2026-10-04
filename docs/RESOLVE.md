# DaVinci Resolve and control surfaces

VideoBench is centered on professional NLE work but is not bound to one control interface.

## Surface profile

Every RunStack declares separately:

```text
observation surface
action surface
media-analysis surface
verification access
tool granularity
allowed external tools
network policy
```

Supported vocabulary currently includes:

```text
mcp_compound
mcp_granular
resolve_scripting
gui
command
manual
hybrid
none
```

`MCP versus direct` is not one complete experimental variable. A compound semantic MCP, one-method-per-tool MCP, offline project editor, direct scripting harness, and screenshot-driven GUI agent expose different planning, perception, and verification burdens.

## Semantic capability ontology

Benchmark task families describe work capabilities, not implementation method names.

Initial ontology areas:

- media ingest and organization;
- project and timeline management;
- clip placement, source range, and trimming;
- track and linked-media behavior;
- transitions and retiming;
- titles, graphics, and captions;
- markers and review state;
- color;
- Fusion;
- Fairlight/audio;
- render and delivery;
- interchange and conform;
- metadata and analysis.

An API/method coverage report may map implementation methods to these capabilities. Raw method count is not a benchmark weight.

## Read-only state probe

`videobench resolve-snapshot` connects through `DaVinciResolveScript` and captures, where observable:

- Resolve version, product, and page;
- current project and settings;
- timeline names, ranges, timecodes, and settings;
- video, audio, and subtitle tracks;
- timeline item ranges and properties;
- media-pool clip properties;
- missing or failed calls.

The probe is deliberately read-only and tolerant of version differences. Unavailable methods appear under `unknowns`.

## Persistence protocol

For forms where editable project state is contractual:

1. start from a frozen project/database snapshot;
2. run the candidate;
3. save the project;
4. close the project or Resolve as declared;
5. restore the verifier's clean observation context;
6. reopen the project;
7. capture project state and deliverables;
8. decode and probe renders;
9. preserve the project export and raw state receipt.

An operation that appears in the UI but does not survive reopen has not satisfied a persistent-state obligation.

## MCP integration

The current generic command adapter is the stable integration seam:

```text
VideoBench ExecutionPack
-> MCP/model harness command
-> Resolve work
-> output/project/state receipts
-> WorkResultBundle
```

A dedicated MCP adapter should add:

- tool schema hash;
- server version and commit;
- enabled tool subset;
- compound/granular mode;
- raw calls and responses;
- server verification claims;
- transport retries;
- unsupported-capability receipts.

Server-reported verification remains diagnostic. Benchmark-owned state inspection is authoritative for terminal-state checks.

## GUI integration

GUI studies must record:

- display resolution and scaling;
- Resolve workspace layout;
- open page/panel state;
- input method;
- screenshot or video observation policy;
- coordinate normalization;
- focus changes and interruptions;
- screen recording;
- accessibility/OCR facilities;
- timing and timeout policy.

GUI and structured-surface results should not be pooled as one treatment without a specific common-capability study.

## Environment receipt

A real environment should retain:

```text
OS and patch level
CPU/GPU/RAM
Resolve version and edition
project database mode
color management
fonts
plugins
codecs
control-surface versions
screen profile for GUI
network policy
asset hashes
capability probe
known unsupported or unobservable features
```

The environment is part of RunStack identity, not incidental metadata.
