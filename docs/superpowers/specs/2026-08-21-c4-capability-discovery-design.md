# C4 Capability Discovery — Design

Date: 2026-08-21
Status: Approved design, pending implementation plan
Branch: `phase-c4-capability-discovery`
Base: `main` at `1a22562b8e55210e0904955005ad2cd81ccafabd`

## Context

Phase C4 strengthens Rakit's capability discovery and diagnostics after C3 normalized installation and extras UX.

Rakit already has a real compile-time capability graph in `rakit-core`: `CapabilityProvider`, `CapabilityRequirement`, `CapabilityReport`, and fail-closed capability validation. Web, schema, and SQLAlchemy persistence currently participate in that graph. The `rakit check TARGET` command already prints basic provider and requirement information.

However, capability visibility is incomplete and conflates several different questions:

1. What integrations are installed in the Python environment?
2. What integrations are actually configured on this application?
3. Which configured integrations participate in compiler-enforced capabilities?
4. Which compiler requirements are satisfied or missing?

These are not equivalent. C4 must make the distinctions explicit rather than treating package installation as activation.

Rakit has not had a public release. C4 therefore does not preserve unpublished compatibility aliases or retain weaker APIs purely for backward compatibility when a cleaner first-release contract is available.

## Goals

C4 will:

- distinguish installed integrations from configured application integrations;
- add a dedicated `rakit capabilities` inspector while keeping `rakit check` a validator;
- provide a stable machine-readable JSON schema from C4 v1;
- aggregate the full capability graph before failing instead of stopping at the first missing requirement;
- introduce a reusable installed-integration discovery contract suitable for Phase D and third-party adapters;
- expose configured integration inventory separately from compiler capability enforcement;
- preserve fail-closed compiler behavior;
- improve diagnostics without introducing auto-installation, implicit activation, or speculative capability requirements.

## Non-goals

C4 will not:

- auto-install packages;
- auto-activate integrations;
- add new adapters;
- introduce a general plugin marketplace or public plugin manager;
- infer integrations by scanning package names heuristically;
- turn `rakit check` into a full environment inspector;
- add a second overlapping command such as `rakit doctor`;
- change server runtime selection semantics;
- invent compiler capability requirements for auth, storage, or server behavior that the compiler does not currently enforce;
- treat an installed package as an active application capability.

## Core invariant: installed is not configured

C4 locks the following semantic boundary:

> An installed integration means an implementation is available in the environment. A configured integration means the application actually uses or composes that implementation. A compiler capability provider means the implementation participates in enforced capability semantics.

These states are related but never interchangeable.

A package discovered through installed-integration metadata must never become active merely because it is present in the environment.

## Architecture

### 1. Aggregate capability analysis

`rakit-core` will introduce a first-class `CapabilityAnalysis` value object that represents the complete evaluation of capability requirements against configured capability providers.

Conceptually:

```python
CapabilityAnalysis
├── providers
├── requirements
├── reports
├── available
├── missing_requirements
└── valid
```

A new `analyze_capabilities(requirements, providers)` operation will:

1. normalize the supplied provider and requirement collections into deterministic tuples;
2. evaluate every requirement;
3. produce every `CapabilityReport`;
4. compute the union of available capabilities;
5. expose all unsatisfied requirements; and
6. return a `CapabilityAnalysis` regardless of whether the graph is valid.

Compiler validation will use this object rather than calling a fail-fast requirement helper repeatedly.

The compile flow becomes:

```text
collect configured providers
collect all requirements
analyze entire graph
if analysis invalid:
    raise one CONFIG_INVALID error carrying full analysis details
continue compilation
```

The compiler remains fail-closed. The behavioral change is only that it fails once after evaluating all requirements rather than failing on the first missing requirement.

Because Rakit is unreleased, old capability helper APIs that become redundant may be simplified or removed rather than retained solely for compatibility. The implementation plan must inventory direct call sites before removing anything.

### 2. Configured integration inventory is separate from enforcement

`ApplicationBuilder` will gain a diagnostic registry for configured integrations, separate from `_capability_providers`.

Conceptually:

```text
Configured application diagnostics
├── configured integrations
├── capability providers
├── capability requirements
└── capability analysis
```

A configured integration describes a concrete integration actually composed into the application. It is diagnostic metadata, not capability authority.

This avoids forcing auth, storage, and server subsystems into the compile-time capability graph when their runtime architecture does not justify it.

The builder will expose an explicit registration operation such as:

```python
register_configured_integration(...)
```

Duplicate configured integration identifiers are configuration errors.

Expected first-party configured inventory behavior:

- Starlette web integration: recorded by `Admin`;
- Pydantic schema integration: recorded by `Admin`;
- SQLAlchemy persistence: recorded by `SQLAlchemyPlugin.configure()`;
- local storage: recorded by `LocalStoragePlugin.configure()`;
- SQLAlchemy auth: recorded when the corresponding auth backend/session store composition is supplied to `Admin`;
- custom auth/storage implementations without Rakit metadata remain usable, but diagnostics must not guess their implementation identity.

For custom implementations lacking explicit metadata, diagnostics may report a conservative `custom/unknown` implementation classification where useful, but must never fabricate an official integration identifier.

Server adapters are not part of configured application inventory in C4 because Uvicorn/Granian selection occurs through the runtime server command rather than application compilation. Installed server integrations remain discoverable through the environment view.

### 3. Installed integration descriptor

C4 will add a lightweight installed-integration descriptor contract. This contract advertises what an installed distribution can provide if explicitly configured.

Conceptually:

```python
InstalledIntegrationDescriptor(
    integration_id="persistence.sqlalchemy",
    category="persistence",
    display_name="SQLAlchemy",
    advertised_capabilities=CapabilitySet.of(...),
)
```

The exact final field names may be refined during implementation only if semantics remain unchanged. The required semantic fields are:

- stable integration identifier;
- category;
- human display name;
- advertised capability set, which may be empty when no compiler capability graph exists for that integration.

`advertised_capabilities` means capabilities the implementation advertises when correctly configured. It does not mean those capabilities are active on the target application.

### 4. Generic installed-integration discovery

Installed integration discovery will use a dedicated Python entry-point group:

```toml
[project.entry-points."rakit.integrations"]
"persistence.sqlalchemy" = "rakit_sqlalchemy.discovery:integration"
```

Entry points should resolve to lightweight discovery modules rather than importing a full runtime stack unnecessarily.

C4 will not scan installed distribution names or import arbitrary `rakit-*` packages heuristically.

The discovery contract is intentionally generic so Phase D and third-party adapters can participate without changes to the inspector.

Expected first-party installed descriptors in C4 v1:

- `web.starlette`
- `schema.pydantic`
- `persistence.sqlalchemy`
- `auth.sqlalchemy`
- `storage.local`
- `server.uvicorn`
- `server.granian`

One distribution may advertise multiple integration descriptors. For example, `rakit-web` may expose Starlette web and Pydantic schema descriptors independently.

C4 will not advertise a generated API transport integration until a genuine replaceable implementation boundary exists.

The existing `rakit.servers` entry-point group remains the runtime server adapter registry. `rakit.integrations` is parallel diagnostic metadata and does not replace server runtime discovery.

### 5. Installed discovery failure behavior

Installed discovery fails explicitly when metadata is not trustworthy.

Errors include:

- duplicate `integration_id` claims;
- malformed descriptors;
- an entry point that cannot be loaded;
- an entry point that resolves to an invalid descriptor type.

These are discovery errors and cause the capability command to exit non-zero because a reliable inspection could not be produced.

There is no silent fallback to package-name guessing.

## CLI design

### `rakit check TARGET`

`rakit check` remains a validator.

Its responsibilities are:

- load and compile the target;
- validate configuration;
- summarize the configured capability graph;
- exit non-zero when capability requirements are unsatisfied or other configuration errors occur.

After aggregate analysis, missing-capability output should report all missing requirements rather than only the first one.

`rakit check` does not inspect the installed environment and does not implicitly invoke installed-integration discovery.

### `rakit capabilities`

C4 introduces a separate inspector command.

Supported forms:

```bash
rakit capabilities TARGET
rakit capabilities TARGET --installed
rakit capabilities --installed
rakit capabilities TARGET --json
rakit capabilities --installed --json
rakit capabilities TARGET --installed --json
```

A call without a target is valid only when `--installed` is requested. The CLI should reject a call that has neither a target nor `--installed`.

### Inspector exit semantics

`rakit capabilities` is a pure inspector.

If target loading and capability analysis succeed, the command exits `0` even when configured capability requirements are missing. In that case the report carries `valid: false`.

It exits non-zero only when a reliable report cannot be produced, such as:

- target import failure;
- non-capability configuration failure preventing analysis;
- malformed installed descriptor;
- duplicate installed integration identifier;
- installed entry-point loading failure;
- an internal analysis/discovery failure.

This prevents `rakit capabilities` from becoming an alias for `rakit check`.

## Human-readable output

Configured and installed sections must remain visually separate.

Example configured output:

```text
Application: myapp:admin
Status: invalid

Configured integrations:
  web.starlette
  schema.pydantic
  persistence.sqlalchemy
  auth.sqlalchemy
  storage.local

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
  generated-api.read          satisfied
  generated-api.patch         missing
    missing: schema.partial-update
```

When `--installed` is requested, a distinct section is appended:

```text
Installed integrations:
  auth.sqlalchemy          authentication
  persistence.sqlalchemy  persistence
  server.granian          server
  server.uvicorn           server
  storage.local            storage
```

The exact spacing may follow existing Click conventions. Ordering must be deterministic.

Installed integrations must never be labelled active merely because they are installed.

## JSON contract v1

C4 v1 includes a stable JSON contract with an explicit schema version.

Configured-target example:

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
        "capabilities": [
          "schema.input-validation",
          "schema.output-serialization"
        ]
      }
    ],
    "requirements": [
      {
        "id": "generated-api.patch",
        "status": "missing",
        "required": [
          "schema.input-validation",
          "schema.partial-update"
        ],
        "available": [
          "schema.input-validation"
        ],
        "missing": [
          "schema.partial-update"
        ],
        "providers": [
          "schema.pydantic"
        ]
      }
    ]
  },
  "installed": null
}
```

When `--installed` is requested, `installed` becomes an array of installed-integration descriptor records.

For installed-only inspection:

```bash
rakit capabilities --installed --json
```

these fields are `null` rather than a fabricated empty application:

```json
{
  "schema_version": 1,
  "target": null,
  "valid": null,
  "configured": null,
  "installed": []
}
```

JSON ordering must be deterministic so output is stable in tests and automation.

Human output and JSON must be rendered from one normalized report model rather than assembling independent data paths that can drift.

## Relationship between configured integrations and capability providers

Configured integration inventory and capability providers intentionally overlap only where enforcement exists.

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

This is correct, not incomplete.

Auth and storage should only become compiler capability providers later if concrete compiler requirements need those capability contracts. C4 must not introduce such requirements merely for cosmetic symmetry.

## Report model

The CLI should use a normalized report object that contains both optional views:

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

The exact package placement of the CLI-facing report model may be chosen during the implementation plan, but the report should not introduce runtime dependencies into `rakit-core` that are specific to Click or Python package metadata.

Core capability semantics belong in `rakit-core`; environment entry-point discovery and CLI rendering belong above core.

## Error model

### Missing capability requirements

Configured capability requirements that are missing are a normal inspectable state.

- compiler: fail closed with one aggregate configuration error;
- `rakit check`: non-zero;
- `rakit capabilities TARGET`: exit `0`, `valid: false`;
- JSON: all missing requirements included.

The aggregate compiler error must carry structured details sufficient to reconstruct the full capability analysis. It must not require parsing a human message.

### Other target errors

Non-capability configuration errors are not converted into capability reports. If target loading/compilation cannot reach a reliable capability analysis, `rakit capabilities` exits non-zero and preserves an actionable error.

### Installed discovery errors

Malformed, duplicate, or unloadable installed descriptors fail explicitly. No broken descriptor is silently omitted.

## Determinism

C4 diagnostics must be deterministic.

At minimum:

- configured integrations sorted by integration id;
- providers sorted by provider id;
- capabilities sorted by capability name;
- requirements sorted by requirement id;
- installed integrations sorted by integration id;
- JSON arrays use the same canonical ordering as human output.

This is important for regression tests, CI, IDE integrations, and future tooling.

## First-party integration metadata

C4 v1 will add installed discovery metadata for all current first-party integration boundaries:

| Integration id | Category | Configured inventory | Compiler provider | Installed discovery |
| --- | --- | --- | --- | --- |
| `web.starlette` | web | yes | yes | yes |
| `schema.pydantic` | schema | yes | yes | yes |
| `persistence.sqlalchemy` | persistence | yes | yes | yes |
| `auth.sqlalchemy` | authentication | yes when used | no | yes |
| `storage.local` | storage | yes when installed on app | no | yes |
| `server.uvicorn` | server | no in application compile | no | yes |
| `server.granian` | server | no in application compile | no | yes |

The implementation must avoid importing heavyweight optional runtime dependencies solely to enumerate installed descriptors where a lightweight descriptor module can be used.

## Package boundary guidance

Recommended responsibility split:

### `rakit-core`

- `CapabilityAnalysis`;
- `analyze_capabilities`;
- aggregate capability error details;
- configured-integration value object/registration semantics if they are compiler/application-builder metadata;
- no Click or `importlib.metadata` environment discovery dependency.

### `rakit`

- installed-integration discovery orchestration using `importlib.metadata`;
- inspection report composition;
- human renderer;
- JSON renderer;
- `rakit capabilities` command;
- revised `rakit check` presentation.

### Integration distributions

- lightweight `rakit.integrations` descriptor entry points;
- configured-integration registration at their natural configuration boundary.

### `rakit-server`

- existing `rakit.servers` runtime entry-point behavior remains unchanged.

## Security and trust boundaries

Entry points are executable Python metadata. Installed integration discovery therefore follows normal Python environment trust assumptions and must not claim to be a sandbox.

However, C4 should minimize unnecessary side effects by requiring first-party descriptors to live in lightweight modules and by not constructing runtime adapters merely to inspect metadata.

Discovery must never mutate the application, install packages, initialize databases, start servers, or perform network operations as part of the contract.

## Verification strategy

The user's established Rakit workflow remains authoritative:

1. implement feature/source first;
2. perform non-test/manual verification;
3. add regression/unit tests after source behavior is verified;
4. run full CI last;
5. do not merge unless explicitly asked;
6. do not tag, release, version-bump, or publish unless explicitly asked.

### Source-first/manual verification matrix

Before adding regression tests, C4 source behavior should be exercised for:

- valid configured app;
- invalid app with multiple missing requirements, proving aggregate reporting;
- configured integration inventory separate from capability providers;
- installed-only discovery;
- configured + installed combined inspection;
- human output deterministic ordering;
- JSON output with `schema_version: 1`;
- installed-only JSON using `null` configured fields;
- inspector exit `0` with `valid: false`;
- `rakit check` exit non-zero for the same invalid target;
- malformed installed descriptor failure;
- duplicate installed integration id failure;
- entry-point loading failure;
- installed package never becoming configured implicitly;
- current server runtime registry remaining unchanged.

### Regression coverage

Regression tests should cover at least:

- core aggregate analysis;
- compiler aggregate fail-closed behavior;
- structured aggregate error details;
- configured integration registration and duplicate rejection;
- first-party configured integration registration;
- generic installed integration entry-point discovery;
- descriptor validation and duplicate detection;
- CLI human output;
- JSON schema v1 output;
- exit code semantics;
- existing `rakit check` behavior where still applicable;
- all first-party `rakit.integrations` metadata declarations;
- release/artifact behavior if entry-point metadata affects built distributions.

### Final repository verification

After regressions pass:

- Ruff format;
- Ruff lint;
- `ty`;
- full pytest on Python 3.12, 3.13, and 3.14;
- lowest-direct dependency matrix;
- latest dependency matrix;
- coverage gate;
- strict MkDocs build;
- artifact validation and dry run;
- generated web-asset reproducibility;
- exact-head final CI.

## Documentation and roadmap closure

C4 documentation should explain:

- installed versus configured semantics;
- `rakit check` versus `rakit capabilities`;
- human and JSON inspection examples;
- how third-party integrations advertise installed metadata;
- why advertised installed capabilities do not mean active capabilities.

At C4 completion:

- mark C4 Complete;
- mark Phase D adapter ecosystem as Next;
- update the stale near-term execution order so C3 is no longer listed as upcoming;
- update the changelog;
- do not trigger any public release action.

## Acceptance criteria

C4 is complete when all of the following are true:

1. `CapabilityAnalysis` represents the entire configured capability graph.
2. Compiler capability validation evaluates all requirements before one aggregate fail-closed error.
3. `rakit check TARGET` remains a validator and reports aggregate capability failures with non-zero exit status.
4. `rakit capabilities TARGET` inspects configured state and exits `0` when analysis succeeds even if `valid` is false.
5. `rakit capabilities --installed` discovers installed integrations through the generic `rakit.integrations` contract.
6. Installed integrations are never treated as configured implicitly.
7. Configured integration inventory is separate from compiler capability providers.
8. First-party web, schema, persistence, auth, storage, Uvicorn, and Granian boundaries publish honest discovery metadata where applicable.
9. Human and JSON output are generated from the same normalized report data.
10. JSON includes `schema_version: 1` and preserves explicit `null` values for unavailable views.
11. Discovery and output ordering are deterministic.
12. Malformed/duplicate/unloadable installed descriptors fail explicitly.
13. Current `rakit.servers` runtime semantics remain unchanged.
14. Source-first manual verification passes before regression tests are added.
15. Full exact-head CI passes after docs and roadmap closure.
16. No merge, tag, release, version bump, TestPyPI upload, or PyPI publication occurs without explicit maintainer instruction.
