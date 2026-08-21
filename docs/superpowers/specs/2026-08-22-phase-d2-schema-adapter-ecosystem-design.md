# Rakit Phase D2 Schema Adapter Ecosystem Design

Date: 2026-08-22
Status: Approved design direction; written for maintainer review before implementation planning

## 1. Goal

Phase D2 proves that Rakit's schema capability architecture is genuinely adapter-driven by extracting the existing Pydantic implementation from `rakit-web` into a dedicated first-party schema package and adding msgspec as the first second implementation.

D2 intentionally accepts a breaking cleanup because Rakit has not been publicly released and has no external consumers to preserve. The objective is to establish the correct package boundary now rather than carry compatibility debt into later releases.

## 2. Locked Principles

1. **Pydantic remains the default schema experience**, because it provides the most familiar and ergonomic starting point for most Python users.
2. **Default does not mean architectural dependency.** `rakit-core` and `rakit-web` must not depend on Pydantic- or msgspec-specific APIs.
3. **Schema engine ownership moves into dedicated packages.** Pydantic and msgspec are peers above `rakit-core`.
4. **Breaking cleanup is allowed.** The old `rakit_web.schema.PydanticSchemaAdapter` ownership may be removed without a compatibility re-export or deprecation shim.
5. **Capability follows proven semantics.** msgspec is not required to advertise the same capability set as Pydantic. It advertises only contracts it truly satisfies.
6. **Pydantic must preserve its currently advertised semantics.** The migration may not silently reduce Pydantic capability support.
7. **Native schema types stay native.** Pydantic uses `BaseModel`; msgspec uses `msgspec.Struct`. D2 does not create a `RakitSchema` base class or schema DSL.
8. **Adapter selection is explicit.** Installed integrations and configured/active integration are distinct concepts. Rakit must not select an adapter through arbitrary import/discovery order.
9. **Pydantic is the default selection when no explicit schema adapter is configured and the Pydantic adapter is available.** Multiple installed adapters must not create hidden first-installed-wins behavior.
10. **Automatic `rakit schema use ...` package switching is out of scope for D2.** D2 proves adapter portability first; package-manager mutation UX can be designed later.

## 3. Architectural Target

The desired package graph is:

```text
rakit-core
   ^
   |-- rakit-schema-pydantic
   |-- rakit-schema-msgspec
   |-- rakit-sqlalchemy
   `-- rakit-web
```

`rakit-core` owns only the neutral contracts:

- `SchemaAdapter`
- `PartialInputSchemaAdapter`
- `SchemaField`
- `SchemaValidationIssue`
- `SchemaValidationError`
- canonical schema capability contracts and D1 conformance machinery

`rakit-web` consumes schema adapters only through these contracts. It must not inspect `BaseModel`, `msgspec.Struct`, Pydantic validation errors, msgspec decoding internals, or concrete adapter class names.

## 4. D2 Decomposition

### D2.1 — Schema Package Boundary

Create `packages/rakit-schema-pydantic` and move first-party Pydantic ownership out of `rakit-web`.

The new package owns:

- `PydanticSchemaAdapter`;
- the `schema.pydantic` capability provider;
- the `schema.pydantic` `IntegrationDescriptor`;
- Pydantic-specific validation error translation;
- Pydantic package dependency metadata;
- first-party conformance tests for the Pydantic adapter.

The old `rakit_web.schema` Pydantic implementation is removed. There is no compatibility shim or re-export.

`rakit-web` must no longer publish `schema.pydantic` through its entry points.

### D2.2 — msgspec Adapter

Create `packages/rakit-schema-msgspec` as a peer first-party adapter package.

The package owns:

- `MsgspecSchemaAdapter`;
- `schema.msgspec` capability provider;
- `schema.msgspec` `IntegrationDescriptor`;
- msgspec-specific validation/error translation;
- msgspec package dependency metadata;
- first-party conformance tests.

The adapter accepts native `msgspec.Struct` schema classes. It must reject unsupported schema types with an actionable `TypeError` or equivalent deterministic contract error rather than coercing unrelated objects.

### D2.3 — Discovery, Installation, and Default Selection

Both schema packages register their integration descriptor through the existing `rakit.integrations` entry-point mechanism.

Rakit distinguishes:

```text
installed schema integrations
configured/active schema integration
```

If an application explicitly configures a schema adapter, that selection wins and must resolve to an installed compatible integration.

If no schema adapter is explicitly configured, Pydantic remains the default only when `schema.pydantic` is installed. Rakit must not choose msgspec merely because it was discovered first.

If neither an explicit selection nor the default Pydantic adapter is available, the framework fails with an actionable capability/install diagnostic rather than silently selecting an arbitrary implementation.

D2 may add root-facade package metadata/extras needed for good default installation UX, but must not make `rakit-core` or `rakit-web` depend on a concrete schema engine.

The exact distribution UX must preserve this principle:

- default Rakit experience: Pydantic;
- modular Rakit deployments: free to use msgspec without schema-level Pydantic coupling;
- msgspec can be installed explicitly as an alternative/extra;
- D2 does not implement automatic dependency removal or package switching commands.

## 5. Schema Capability Semantics

D2 uses the four canonical schema capabilities established in D1:

- `schema.field-introspection@1`
- `schema.input-validation@1`
- `schema.output-serialization@1`
- `schema.partial-update@1`

Pydantic currently advertises all four; D2 must re-prove all four after package extraction.

msgspec advertises only the subset that passes the same D1 behavioral contracts.

### 5.1 Field Introspection

The adapter exposes stable Rakit `SchemaField` values for fields declared by the native schema type. At minimum, canonical field names must be available in declaration order where the underlying engine provides a meaningful deterministic order.

Optional metadata such as title/description may be absent when the underlying engine does not naturally provide it. Missing optional metadata must not be fabricated.

### 5.2 Input Validation

`validate_input(schema, values)` validates a complete input according to native schema semantics and translates validation failures into `SchemaValidationError` with deterministic `SchemaValidationIssue` entries.

The contract concerns observable validation behavior and Rakit error translation, not engine-specific exception classes.

### 5.3 Output Serialization

`serialize_output(schema, value)` validates/coerces according to the supported native schema semantics and returns a JSON-compatible Rakit transport value where the adapter can do so honestly.

The adapter must not expose engine-private objects as the framework-level serialized result.

### 5.4 Presence-Aware Partial Update

D2 locks the following `schema.partial-update@1` meaning:

- a subset of fields can be validated without requiring omitted required fields;
- missing is distinct from explicit `None`;
- explicit `None` remains present when valid for the field;
- the result contains only fields actually supplied by the caller;
- validation still applies to every supplied field;
- an empty mapping is valid unless some separate, explicit Rakit operation-level rule rejects an empty update.

Examples:

```text
{} -> {}
{"age": None} -> {"age": None}
{"name": "Edo"} -> {"name": "Edo"}
```

This semantic is library-neutral. Pydantic and msgspec must meet it without relying on fragile private APIs or fake full-model construction.

The existing Pydantic implementation must be audited carefully because full `model_validate()` before `exclude_unset=True` can incorrectly require unrelated required fields. If the current implementation violates the D2 contract, D2 must fix the behavior rather than weakening the capability contract.

If msgspec cannot satisfy the partial-update contract with a clean, deterministic adapter implementation, `schema.msgspec` must not advertise `schema.partial-update`.

## 6. Native Schema Types

D2 deliberately avoids a new framework schema DSL.

Conceptually:

```text
Pydantic BaseModel --> PydanticSchemaAdapter --+
                                                +--> SchemaAdapter contract
msgspec.Struct -----> MsgspecSchemaAdapter ----+
```

This preserves each ecosystem's typing/model experience while keeping generated transports and application/runtime layers neutral.

## 7. Error Translation

Each adapter owns translation from native validation failures into:

```python
SchemaValidationError(
    issues=(
        SchemaValidationIssue(location=(...), code="...", message="..."),
        ...
    )
)
```

Requirements:

- locations are deterministic string tuples;
- codes are stable enough for Rakit-level consumers and tests;
- messages are human-readable;
- native exception objects are chained where appropriate for debugging;
- adapters must not leak engine-specific error object shapes into core consumers.

D2 does not require Pydantic and msgspec to produce byte-identical error codes/messages when their native semantics differ. The conformance contract should require equivalent Rakit-level guarantees, not artificial textual parity.

## 8. Selection and Ambiguity Rules

D2 must make schema selection deterministic.

Preferred rules:

1. explicit application/configuration selection;
2. otherwise Pydantic default if the Pydantic integration is installed;
3. otherwise fail with an actionable diagnostic.

Installing msgspec alongside Pydantic does not automatically make msgspec active.

Installed integrations should remain visible to C4 capability discovery even when inactive. This preserves the important distinction between availability and configuration.

D2 must not implement "first entry point returned by metadata wins" or any other order-dependent fallback.

## 9. Package and Installation UX

The package ecosystem should support both a batteries-included default and modular composition.

The root `rakit` distribution may arrange default installation so the ordinary developer experience includes the Pydantic adapter, while advanced users can compose lower-level packages with msgspec without schema-engine coupling in `rakit-core` or `rakit-web`.

The final implementation plan must inspect the current extras vocabulary introduced in C3 and choose the smallest change that preserves one source of truth for install guidance.

D2 should not add a complex schema-package mutation CLI. A future `rakit schema use <adapter>` may be valuable, but it belongs to a later developer-experience decision after real multi-adapter usage exists.

## 10. Conformance Strategy

D1 is the acceptance boundary for D2.

Every first-party schema integration must:

1. advertise canonical capabilities through its `IntegrationDescriptor`;
2. satisfy prerequisite validation;
3. run the exact matching v1 behavioral conformance specs;
4. fail closed for an advertised capability if the harness/spec is absent;
5. be represented in the maintainer conformance matrix.

Pydantic must remain 4/4 unless D2 proves an existing advertisement was dishonest. If that occurs, the correct response is to fix the adapter semantics where feasible; silently dropping a mature advertised capability is not the preferred migration path.

msgspec capability count is an outcome, not a target.

## 11. Testing and Verification Workflow

Follow the established Rakit workflow:

```text
source/package migration first
  -> manual/non-pytest verification
  -> permanent regression/conformance tests
  -> full canonical CI
  -> docs/roadmap closure
  -> exact-head CI
```

D2 test coverage must include:

- Pydantic package extraction without `rakit-web` ownership;
- absence of stale Pydantic-specific imports/entry points in `rakit-web`;
- Pydantic 4/4 conformance including true presence-aware partial updates;
- msgspec conformance for every advertised capability;
- invalid schema-type rejection;
- validation error translation;
- explicit selection behavior;
- Pydantic default behavior;
- dual-installed adapter behavior without order-dependent selection;
- missing-default/invalid-selection diagnostics;
- C4 discovery showing installed schema integrations correctly;
- packaging/artifact verification for the two new distributions;
- dependency compatibility matrices and clean-installed artifact checks.

## 12. Roadmap Integration

The D2 branch also corrects stale canonical roadmap state:

- Phase C becomes `Complete`;
- C4 Capability Discovery becomes `Complete`;
- Phase D becomes the structured adapter-ecosystem program;
- D1 Adapter Contract Hardening becomes `Complete`;
- D2 Schema Adapter Ecosystem becomes the active/next phase until closure;
- D3 Persistence Adapter Ecosystem follows next after D2;
- D4 Web Framework Integrations remains planned with D4.0-D4.6;
- D5 Adapter Authoring DX / SDK remains planned;
- D6 Additional First-party Adapters remains planned.

D2 is marked `Complete` only after implementation, regression verification, full CI, and exact-head closure CI pass.

## 13. D4 Substructure Preserved in Roadmap

The agreed D4 structure remains:

- D4.0 — Web Integration Contract
- D4.1 — Litestar
- D4.2 — FastAPI
- D4.3 — Starlette
- D4.4 — Flask
- D4.5 — Sanic
- D4.6 — Integration DX & Compatibility Matrix

## 14. Acceptance Criteria

D2 is complete only when:

1. `rakit-schema-pydantic` exists as a first-party package and owns Pydantic schema behavior.
2. `rakit-web` no longer owns or re-exports `PydanticSchemaAdapter` and no compatibility shim remains.
3. `rakit-schema-msgspec` exists as a first-party package using native `msgspec.Struct` schemas.
4. `rakit-core` and `rakit-web` remain free of concrete Pydantic/msgspec implementation dependencies.
5. Pydantic re-proves all four canonical schema capability contracts at v1.
6. msgspec advertises and passes only the canonical capabilities it honestly supports.
7. `schema.partial-update@1` is presence-aware: omitted fields are not required, missing differs from explicit `None`, and only supplied fields are returned.
8. Invalid native schema types fail deterministically and actionably.
9. Native validation failures translate to `SchemaValidationError` without leaking engine-specific structures to core consumers.
10. Integration discovery exposes both schema integrations when installed.
11. Explicit schema selection is deterministic; no first-installed/import-order selection exists.
12. With no explicit selection, Pydantic is the default only when the Pydantic integration is available.
13. Missing or invalid selection fails with actionable diagnostics.
14. Root/default installation UX keeps Pydantic as the ordinary developer default without making it a `rakit-core` or `rakit-web` architecture dependency.
15. No automatic schema switching/uninstall CLI is introduced in D2.
16. Package metadata, workspace configuration, artifact checks, and release dry-run include the new schema distributions.
17. Existing C4 capability discovery semantics remain compatible.
18. Existing framework regression suite remains green.
19. Canonical roadmap records C4 and D1 as Complete and the agreed D1-D6/D4.0-D4.6 structure.
20. D2 is marked Complete only on a commit whose full exact-head canonical CI is green.
21. No release, tag, version bump, TestPyPI upload, or PyPI publication occurs as part of D2.

## 15. Non-Goals

D2 does not implement Tortoise ORM, Litestar, FastAPI adapter packaging, public adapter-authoring SDKs, a Rakit schema DSL, automatic package replacement, or `rakit schema use` switching commands.

D2 also does not require Pydantic and msgspec to have identical feature sets or identical native validation semantics. The canonical capability contracts define the interoperability boundary; honest differences are expected and should remain visible.
