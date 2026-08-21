# C4 Capability Discovery — Design

Date: 2026-08-21  
Status: Approved design, pending implementation plan  
Branch: `phase-c4-capability-discovery`  
Base: `main` at `1a22562b8e55210e0904955005ad2cd81ccafabd`

## Context

Phase C4 strengthens Rakit's capability discovery and diagnostics after C3 normalized installation and extras UX.

Rakit already has a real compile-time capability graph in `rakit-core`: `CapabilityProvider`, `CapabilityRequirement`, `CapabilityReport`, and fail-closed capability validation. Web, schema, and SQLAlchemy persistence participate in that graph today. `rakit check TARGET` already prints a basic view of providers and requirements.

The missing distinction is between four different questions:

1. Which integrations are installed in the Python environment?
2. Which integrations are actually configured on this application?
3. Which configured integrations participate in compiler-enforced capabilities?
4. Which compiler requirements are satisfied or missing?

C4 makes those states explicit. Rakit remains unreleased, so C4 may simplify unpublished APIs rather than preserve compatibility baggage.

## Goals

C4 will:

- distinguish installed integrations from configured integrations;
- add `rakit capabilities` as a dedicated inspector while keeping `rakit check` a validator;
- provide a stable JSON schema from C4 v1;
- evaluate the full configured capability graph before one aggregate fail-closed error;
- add a generic installed-integration discovery contract suitable for Phase D and third-party adapters;
- expose configured integration inventory separately from compiler capability enforcement;
- preserve explicit activation and fail-closed semantics.

## Non-goals

C4 will not:

- auto-install or auto-activate integrations;
- add adapters;
- scan package names heuristically;
- turn `rakit check` into an environment inspector;
- add another overlapping command such as `rakit doctor`;
- change server runtime selection;
- invent auth/storage/server capability requirements merely for diagnostic symmetry;
- treat installed integrations as active application capabilities.

## Locked invariant: installed is not configured

An installed integration means an implementation is available in the environment. A configured integration means the target application actually composes that implementation. A compiler capability provider means a configured component participates in capability enforcement.

These states may overlap but are never interchangeable. Installed metadata never activates an integration.

## Core capability analysis

`rakit-core` will introduce `CapabilityAnalysis` as the complete evaluation of requirements against configured providers.

Conceptually:

```text
CapabilityAnalysis
├── providers
├── requirements
├── reports
├── available
├── missing_requirements
└── valid
```

`analyze_capabilities(requirements, providers)` will:

1. normalize providers and requirements into deterministic tuples;
2. evaluate every requirement;
3. produce every `CapabilityReport`;
4. compute the union of available capabilities;
5. expose all unsatisfied requirements; and
6. return a `CapabilityAnalysis` even when invalid.

Compilation becomes:

```text
collect configured providers
collect all requirements
analyze entire graph
if analysis invalid:
    raise one CONFIG_INVALID carrying the full structured analysis
continue compilation
```

The compiler remains fail-closed. Only the failure granularity changes: all missing requirements are known before the compiler raises.

If existing fail-fast helpers become redundant, they may be simplified or removed after implementation-time call-site inventory because there is no public compatibility burden yet.

## Configured integration inventory

Configured integration inventory is diagnostic metadata and is separate from capability authority.

`ApplicationBuilder` will maintain a configured-integration registry distinct from `_capability_providers`, with an explicit operation such as:

```python
register_configured_integration(...)
```

Duplicate configured integration ids are configuration errors.

The compiled diagnostic view therefore contains:

```text
configured
├── integrations
├── capability providers
├── capability requirements
└── capability analysis
```

Expected first-party behavior:

- `web.starlette`: registered by `Admin`;
- `schema.pydantic`: registered by `Admin`;
- `persistence.sqlalchemy`: registered by `SQLAlchemyPlugin.configure()`;
- `storage.local`: registered by `LocalStoragePlugin.configure()`;
- `auth.sqlalchemy`: registered when matching built-in SQLAlchemy auth components are supplied to `Admin`;
- server adapters: not part of configured application inventory because server selection occurs at `rakit run` time.

### Configured auth metadata contract

Auth is constructor-level composition rather than a compiler plugin, so C4 will not force `AuthBackend` or `SessionStore` protocols to become capability providers.

Instead, Rakit-owned auth implementations may expose optional lightweight integration metadata through a dedicated optional marker contract. The built-in SQLAlchemy auth backend and SQLAlchemy session store will advertise the same configured integration id, `auth.sqlalchemy`.

When `Admin` receives both `auth_backend` and `session_store`:

1. if both expose the same valid Rakit integration metadata, `Admin` records that configured integration;
2. if neither exposes metadata, auth remains fully usable and diagnostics report it conservatively as custom/unknown rather than guessing an official integration id;
3. if only one side exposes Rakit integration metadata, or the two advertise conflicting official integration ids, configuration fails explicitly because the diagnostic identity is internally inconsistent.

This marker is diagnostic metadata only. It does not become part of the required `AuthBackend` or `SessionStore` structural protocol and does not grant capabilities.

Custom storage/auth implementations remain usable without official metadata. Rakit must not fabricate an official integration identifier for them.

## Installed integration descriptor

C4 will add a lightweight installed-integration descriptor representing what a distribution can provide if explicitly configured.

Conceptually:

```python
InstalledIntegrationDescriptor(
    integration_id="persistence.sqlalchemy",
    category="persistence",
    display_name="SQLAlchemy",
    advertised_capabilities=CapabilitySet.of(...),
)
```

Required semantics:

- stable integration id;
- category;
- human display name;
- advertised capability set, which may be empty where no compiler capability contract exists.

`advertised_capabilities` means capability potential of the installed implementation, not active capability state on a target.

## Generic installed discovery

Installed integration discovery uses a dedicated entry-point group:

```toml
[project.entry-points."rakit.integrations"]
"persistence.sqlalchemy" = "rakit_sqlalchemy.discovery:integration"
```

First-party entry points should resolve through lightweight discovery modules and avoid constructing runtime adapters merely to inspect metadata.

Expected C4 v1 installed descriptors:

- `web.starlette`
- `schema.pydantic`
- `persistence.sqlalchemy`
- `auth.sqlalchemy`
- `storage.local`
- `server.uvicorn`
- `server.granian`

A distribution may advertise multiple descriptors. `rakit-web`, for example, may advertise Starlette and Pydantic independently.

C4 will not advertise a generated API transport until a real replaceable implementation boundary exists.

The existing `rakit.servers` entry-point group remains the runtime server registry. `rakit.integrations` is parallel diagnostic metadata and does not alter runtime server discovery.

### Installed discovery failures

Discovery fails explicitly when metadata is unreliable:

- duplicate `integration_id` claims;
- malformed descriptor;
- entry-point load failure;
- entry point resolving to the wrong type.

There is no fallback to package-name guessing and no silent omission of broken descriptors.

## CLI surface

### `rakit check TARGET`

`rakit check` remains a validator.

It validates the target and exits non-zero for unsatisfied capability requirements or other configuration errors. After C4 it reports aggregate capability failures rather than stopping at the first missing requirement.

It does not inspect installed environment metadata.

### `rakit capabilities`

C4 adds a separate inspector:

```bash
rakit capabilities TARGET
rakit capabilities TARGET --installed
rakit capabilities --installed
rakit capabilities TARGET --json
rakit capabilities --installed --json
rakit capabilities TARGET --installed --json
```

A call with neither TARGET nor `--installed` is rejected as invalid CLI usage.

### Inspector exit semantics

`rakit capabilities` is a pure inspector.

If target loading reaches a reliable capability analysis, the command exits `0` even when requirements are missing. The report carries `valid: false`.

It exits non-zero only when a reliable report cannot be produced, including:

- target import failure;
- non-capability configuration failure that prevents analysis;
- malformed/duplicate/unloadable installed descriptor;
- internal discovery or analysis failure.

This keeps `rakit capabilities` semantically distinct from `rakit check`.

## Normalized inspection report

Human text and JSON must render from one normalized report model so the two surfaces cannot drift.

Conceptually:

```text
CapabilityInspectionReport
├── schema_version
├── target
├── valid
├── configured
│   ├── integrations
│   ├── providers
│   └── requirements/reports
└── installed
```

Core capability semantics stay in `rakit-core`. Environment entry-point discovery, report composition, Click rendering, and JSON serialization live above core in the `rakit` facade package.

## Human-readable output

Configured and installed sections stay visibly separate.

Example:

```text
Application: myapp:admin
Status: invalid

Configured integrations:
  auth.sqlalchemy
  persistence.sqlalchemy
  schema.pydantic
  storage.local
  web.starlette

Capability providers:
  persistence.sqlalchemy
    persistence.read
    persistence.relationships
    persistence.write
    transactions.root-uow

  schema.pydantic
    schema.field-introspection
    schema.input-validation
    schema.output-serialization
    schema.partial-update

Requirements:
  generated-api.read    satisfied
  generated-api.patch   missing
    missing: schema.partial-update
```

With `--installed`, a separate section is appended:

```text
Installed integrations:
  auth.sqlalchemy          authentication
  persistence.sqlalchemy  persistence
  server.granian          server
  server.uvicorn           server
  storage.local            storage
```

Installed entries are never labelled active merely because they are present.

## JSON schema v1

C4 v1 immediately establishes a versioned machine-readable contract.

Configured-target shape:

```json
{
  "schema_version": 1,
  "target": "myapp:admin",
  "valid": false,
  "configured": {
    "integrations": [],
    "providers": [
      {
        "id": "schema.pydantic",
        "capabilities": ["schema.input-validation"]
      }
    ],
    "requirements": [
      {
        "id": "generated-api.patch",
        "status": "missing",
        "required": ["schema.input-validation", "schema.partial-update"],
        "available": ["schema.input-validation"],
        "missing": ["schema.partial-update"],
        "providers": ["schema.pydantic"]
      }
    ]
  },
  "installed": null
}
```

Installed-only inspection:

```json
{
  "schema_version": 1,
  "target": null,
  "valid": null,
  "configured": null,
  "installed": []
}
```

When `--installed` is requested, `installed` is an array of installed descriptor records. Explicit `null` means that a view was not requested or does not exist; it is not replaced with a fabricated empty application.

## Enforcement graph versus diagnostic inventory

Configured integration inventory and capability providers intentionally overlap only where compiler enforcement exists.

Example:

```text
Configured integrations:
  web.starlette
  schema.pydantic
  persistence.sqlalchemy
  auth.sqlalchemy
  storage.local

Capability providers:
  web.starlette
  schema.pydantic
  persistence.sqlalchemy
```

This is correct.

Auth and storage become capability providers only if future concrete compiler consumers require those capability contracts. C4 does not introduce such requirements for cosmetic symmetry.

## Determinism

All diagnostics use canonical ordering:

- configured integrations by integration id;
- providers by provider id;
- capabilities by capability name;
- requirements by requirement id;
- installed integrations by integration id;
- JSON arrays follow the same canonical ordering as human output.

## First-party metadata matrix

| Integration id | Category | Configured inventory | Compiler provider | Installed discovery |
| --- | --- | --- | --- | --- |
| `web.starlette` | web | yes | yes | yes |
| `schema.pydantic` | schema | yes | yes | yes |
| `persistence.sqlalchemy` | persistence | yes | yes | yes |
| `auth.sqlalchemy` | authentication | yes when used | no | yes |
| `storage.local` | storage | yes when used | no | yes |
| `server.uvicorn` | server | no in app compile | no | yes |
| `server.granian` | server | no in app compile | no | yes |

## Error model

### Missing configured requirements

Missing capability requirements are an inspectable state:

- compiler: one aggregate fail-closed configuration error;
- `rakit check`: non-zero;
- `rakit capabilities TARGET`: exit `0`, `valid: false`;
- JSON: every missing requirement included.

The aggregate error must contain structured details sufficient to reconstruct the analysis without parsing human text.

### Other target failures

Non-capability failures are not disguised as capability failures. If a target cannot reach reliable capability analysis, `rakit capabilities` exits non-zero with an actionable error.

### Installed discovery failures

Malformed, duplicate, conflicting, or unloadable descriptors fail explicitly.

## Package boundaries

### `rakit-core`

Owns:

- `CapabilityAnalysis`;
- `analyze_capabilities`;
- aggregate capability error details;
- configured integration value/registry semantics associated with `ApplicationBuilder`;
- optional lightweight configured-integration marker semantics used by Rakit-owned constructor-composed implementations.

It does not depend on Click or installed-environment discovery.

### `rakit`

Owns:

- `importlib.metadata` installed discovery orchestration;
- normalized inspection report composition;
- human rendering;
- JSON rendering;
- `rakit capabilities`;
- revised aggregate `rakit check` presentation.

### Integration distributions

Own:

- lightweight `rakit.integrations` descriptor entry points;
- configured integration registration or optional markers at their natural composition boundary.

### `rakit-server`

Keeps existing `rakit.servers` runtime semantics unchanged.

## Trust and side effects

Python entry points are executable metadata and follow normal environment trust assumptions; C4 does not claim sandboxing.

Discovery itself must not:

- mutate the target application;
- install packages;
- initialize databases;
- start servers;
- perform network operations as part of the descriptor contract.

First-party descriptors should be lightweight to minimize unnecessary import side effects.

## Verification workflow

The established Rakit workflow remains authoritative:

1. implement source/features first;
2. perform non-test/manual verification;
3. add regression/unit tests only after source behavior is verified;
4. run full CI last;
5. do not merge unless explicitly requested;
6. do not tag, release, version-bump, TestPyPI-upload, or PyPI-publish unless explicitly requested.

### Source-first manual matrix

Before regression tests, verify:

- valid configured app;
- invalid app with multiple missing requirements;
- aggregate analysis includes all failures;
- configured inventory stays separate from capability providers;
- built-in SQLAlchemy auth is identified through matching auth metadata;
- custom auth without metadata remains usable and is not falsely identified;
- conflicting one-sided/mismatched auth metadata fails explicitly;
- installed-only discovery;
- configured + installed combined discovery;
- deterministic human output;
- JSON `schema_version: 1`;
- installed-only JSON with null configured fields;
- inspector exit `0` with `valid: false`;
- `rakit check` non-zero for the same invalid target;
- malformed descriptor failure;
- duplicate descriptor failure;
- entry-point load failure;
- installed package never becomes configured implicitly;
- server runtime registry behavior remains unchanged.

### Regression coverage

After source verification, add tests for:

- `CapabilityAnalysis` and deterministic aggregation;
- compiler aggregate fail-closed behavior and structured details;
- configured integration registration and duplicate rejection;
- first-party configured registrations/markers;
- generic installed entry-point discovery;
- descriptor validation and duplicates;
- human and JSON rendering;
- CLI exit semantics;
- all first-party `rakit.integrations` declarations;
- release artifact metadata where entry points affect wheels/sdists.

### Final CI

Final verification includes:

- Ruff format and lint;
- `ty`;
- full pytest on Python 3.12/3.13/3.14;
- lowest-direct and latest dependency suites;
- coverage;
- strict MkDocs;
- artifact validation and dry run;
- generated web-asset reproducibility;
- exact-head final CI after docs/roadmap closure.

## Documentation and roadmap closure

C4 docs will explain:

- installed versus configured semantics;
- `rakit check` versus `rakit capabilities`;
- human and JSON examples;
- third-party `rakit.integrations` metadata;
- why advertised installed capabilities are not active capabilities.

At completion:

- mark C4 Complete;
- mark Phase D adapter ecosystem Next;
- remove stale C3 wording from near-term execution order;
- update `CHANGELOG.md`;
- do not perform a public release.

## Acceptance criteria

C4 is complete when:

1. `CapabilityAnalysis` represents the entire configured capability graph.
2. Compiler capability validation evaluates every requirement before one aggregate fail-closed error.
3. `rakit check TARGET` remains a validator and reports aggregate capability failures with non-zero status.
4. `rakit capabilities TARGET` exits `0` when analysis succeeds even if `valid` is false.
5. `rakit capabilities --installed` discovers integrations through `rakit.integrations`.
6. Installed integrations are never treated as configured implicitly.
7. Configured integration inventory remains separate from compiler capability providers.
8. Built-in SQLAlchemy auth has explicit optional diagnostic identity without making metadata mandatory for custom auth protocols.
9. First-party web/schema/persistence/auth/storage/Uvicorn/Granian boundaries publish honest installed metadata where applicable.
10. Human and JSON views render from the same normalized report.
11. JSON contains `schema_version: 1` and explicit nulls for unavailable views.
12. Output ordering is deterministic.
13. Malformed, duplicate, conflicting, or unloadable installed metadata fails explicitly.
14. Existing `rakit.servers` runtime semantics remain unchanged.
15. Source-first manual verification passes before regression tests are added.
16. Full exact-head CI passes after documentation and roadmap closure.
17. No merge or release action occurs without explicit maintainer instruction.
