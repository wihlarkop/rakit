# C4 Capability Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build honest, deterministic capability discovery that separates installed integrations, configured application integrations, and compiler-enforced capabilities while preserving fail-closed validation.

**Architecture:** `rakit-core` owns integration metadata primitives, configured-integration inventory, aggregate `CapabilityAnalysis`, and compiler validation. The `rakit` facade owns installed entry-point discovery, inspection report composition, text/JSON rendering, and CLI commands. First-party distributions publish lightweight `rakit.integrations` descriptors at their natural package boundaries; installed metadata never activates an integration.

**Tech Stack:** Python 3.12+, dataclasses, typing/Protocols, `importlib.metadata`, Click, existing Rakit compiler/plugin architecture, Hatch/PEP 621 entry points, pytest, Ruff, `ty`, uv workspace.

**Spec:** `docs/superpowers/specs/2026-08-21-c4-capability-discovery-design.md`

## Global Constraints

- Rakit has not been publicly released; do not retain unpublished compatibility APIs or aliases solely for backward compatibility.
- Installed integration state must never imply configured or active application state.
- `rakit check TARGET` remains a validator and exits non-zero for missing capability requirements.
- `rakit capabilities` remains an inspector and exits `0` with `valid: false` when capability analysis succeeds but requirements are missing.
- C4 v1 JSON output must include `schema_version: 1`.
- `rakit capabilities` with neither TARGET nor `--installed` is invalid CLI usage.
- Installed discovery uses the `rakit.integrations` entry-point group; do not scan package names heuristically.
- Existing `rakit.servers` runtime entry-point semantics remain unchanged.
- Compiler capability enforcement and configured integration inventory remain separate concepts.
- Auth/storage/server capability requirements must not be invented merely for cosmetic symmetry.
- Installed descriptor failures are explicit: duplicate ids, malformed descriptors, wrong entry-point value type, or entry-point load failures are errors.
- Diagnostics and JSON arrays must use deterministic canonical ordering.
- First-party installed discovery must avoid constructing runtime adapters or performing application/database/network/server side effects.
- Preserve the user's source-first workflow: implement feature/source first, perform non-test/manual verification second, add regression/unit tests third, run full CI last.
- Do not merge, tag, release, version-bump, upload to TestPyPI, or publish to PyPI without explicit maintainer instruction.

---

## File Structure

### New core files

- `packages/rakit-core/src/rakit_core/integrations.py`
  - `IntegrationDescriptor`
  - `ConfiguredIntegration`
  - optional integration metadata lookup helper used by constructor-composed integrations
- Existing `packages/rakit-core/src/rakit_core/capabilities.py`
  - `CapabilityAnalysis`
  - `analyze_capabilities()`
  - retain only capability primitives/helpers still justified after call-site inventory

### Core files to modify

- `packages/rakit-core/src/rakit_core/compiler.py`
  - configured-integration registry on `ApplicationBuilder`
  - install snapshot support
  - aggregate capability validation
  - `CapabilityConfigurationError`
  - compiled diagnostics metadata
- `packages/rakit-core/src/rakit_core/__init__.py`
  - expose only public C4 core contracts intentionally selected for first release

### New facade files

- `packages/rakit/src/rakit/_integration_discovery.py`
  - load and validate `rakit.integrations` entry points
- `packages/rakit/src/rakit/_capability_inspection.py`
  - normalized inspection report dataclasses
  - build configured/installed views
  - deterministic text and JSON serialization

### Facade files to modify

- `packages/rakit/src/rakit/cli.py`
  - add `rakit capabilities`
  - make `rakit check` consume aggregate analysis

### First-party discovery metadata

- Create `packages/rakit-web/src/rakit_web/discovery.py`
- Modify `packages/rakit-web/src/rakit_web/admin.py`
- Modify `packages/rakit-web/pyproject.toml`
- Create `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/discovery.py`
- Modify `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/plugin.py`
- Modify `packages/rakit-sqlalchemy/pyproject.toml`
- Create `packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/discovery.py`
- Modify `packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/backend.py`
- Modify `packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/sessions.py`
- Modify `packages/rakit-auth-sqlalchemy/pyproject.toml`
- Create `packages/rakit-storage-local/src/rakit_storage_local/discovery.py`
- Modify `packages/rakit-storage-local/src/rakit_storage_local/plugin.py`
- Modify `packages/rakit-storage-local/pyproject.toml`
- Create `packages/rakit-server-uvicorn/src/rakit_server_uvicorn/capabilities.py`
- Create `packages/rakit-server-uvicorn/src/rakit_server_uvicorn/discovery.py`
- Modify `packages/rakit-server-uvicorn/src/rakit_server_uvicorn/server.py`
- Modify `packages/rakit-server-uvicorn/pyproject.toml`
- Create `packages/rakit-server-granian/src/rakit_server_granian/capabilities.py`
- Create `packages/rakit-server-granian/src/rakit_server_granian/discovery.py`
- Modify `packages/rakit-server-granian/src/rakit_server_granian/server.py`
- Modify `packages/rakit-server-granian/pyproject.toml`

### Regression tests added after source-first verification

- Modify `packages/rakit-core/tests/test_capabilities.py`
- Modify `packages/rakit-core/tests/test_compiler.py`
- Add `packages/rakit-core/tests/test_integrations.py`
- Replace/extend `packages/rakit/tests/test_capability_cli.py`
- Add `packages/rakit/tests/test_integration_discovery.py`
- Add focused first-party tests in the owning package test suites where metadata/registration behavior belongs
- Update release/artifact tests if entry-point metadata expectations require it

### Documentation/closure

- Add `docs/guides/capability-discovery.md`
- Modify `docs/roadmap.md`
- Modify `CHANGELOG.md`
- Update MkDocs navigation if guide pages are explicitly enumerated in `mkdocs.yml`

---

### Task 1: Add core integration metadata and aggregate capability analysis

**Files:**
- Create: `packages/rakit-core/src/rakit_core/integrations.py`
- Modify: `packages/rakit-core/src/rakit_core/capabilities.py`
- Modify: `packages/rakit-core/src/rakit_core/__init__.py`

**Interfaces:**
- Produces:
  - `IntegrationDescriptor`
  - `ConfiguredIntegration`
  - `integration_descriptor_from(source: object) -> IntegrationDescriptor | None`
  - `CapabilityAnalysis`
  - `analyze_capabilities(requirements, providers) -> CapabilityAnalysis`
- Consumes: existing `Capability`, `CapabilitySet`, `CapabilityProvider`, `CapabilityRequirement`, `CapabilityReport`, and `evaluate_capabilities()`.

- [ ] **Step 1: Implement strict integration metadata values**

Create `rakit_core.integrations` with the following contract:

```python
from dataclasses import dataclass, field

from .capabilities import CapabilitySet


@dataclass(frozen=True, slots=True)
class IntegrationDescriptor:
    integration_id: str
    category: str
    display_name: str
    advertised_capabilities: CapabilitySet = field(default_factory=CapabilitySet)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("integration_id", self.integration_id),
            ("category", self.category),
            ("display_name", self.display_name),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must be a non-empty trimmed string")


@dataclass(frozen=True, slots=True)
class ConfiguredIntegration:
    integration_id: str | None
    category: str
    display_name: str

    @classmethod
    def from_descriptor(cls, descriptor: IntegrationDescriptor) -> "ConfiguredIntegration":
        return cls(
            integration_id=descriptor.integration_id,
            category=descriptor.category,
            display_name=descriptor.display_name,
        )


def integration_descriptor_from(source: object) -> IntegrationDescriptor | None:
    value = getattr(source, "rakit_integration", None)
    if value is None:
        return None
    if not isinstance(value, IntegrationDescriptor):
        raise TypeError("rakit_integration must be an IntegrationDescriptor")
    return value
```

Validation for `ConfiguredIntegration.category` and `.display_name` must use the same non-empty/trimmed rule. A non-`None` `integration_id` must also be non-empty and trimmed.

- [ ] **Step 2: Implement `CapabilityAnalysis` without failure side effects**

Extend `rakit_core.capabilities`:

```python
@dataclass(frozen=True, slots=True)
class CapabilityAnalysis:
    providers: tuple[CapabilityProvider, ...]
    requirements: tuple[CapabilityRequirement, ...]
    reports: tuple[CapabilityReport, ...]
    available: CapabilitySet

    @property
    def valid(self) -> bool:
        return all(report.satisfied for report in self.reports)

    @property
    def missing_requirements(self) -> tuple[CapabilityRequirement, ...]:
        return tuple(report.requirement for report in self.reports if not report.satisfied)
```

Implement deterministic aggregation:

```python
def analyze_capabilities(
    requirements: Iterable[CapabilityRequirement],
    providers: Iterable[CapabilityProvider],
) -> CapabilityAnalysis:
    provider_tuple = tuple(sorted(providers, key=lambda item: item.provider_id))
    requirement_tuple = tuple(sorted(requirements, key=lambda item: item.requirement_id))
    # reject duplicate ids explicitly
    # evaluate every requirement against the same provider tuple
    # union every provider capability into `available`
    return CapabilityAnalysis(...)
```

Reject duplicate provider or requirement ids with `ValueError`; do not silently collapse them.

- [ ] **Step 3: Inventory and simplify the old fail-fast helper**

Search direct uses of `require_capabilities`. If compiler is the only production caller, remove `require_capabilities()` after Task 2 migrates compiler behavior; keep `evaluate_capabilities()` as the single-requirement primitive used by `analyze_capabilities()`. Do not preserve the fail-fast helper solely as unpublished compatibility surface.

- [ ] **Step 4: Export only intentional public contracts**

Update `rakit_core.__init__` only if first-release public convenience imports are useful. Do not export private CLI/report types from core.

- [ ] **Step 5: Run source-level import/compile smoke without pytest**

Run a plain Python snippet against the workspace that constructs two providers and two requirements, calls `analyze_capabilities()`, and asserts:

```python
assert analysis.valid is False
assert tuple(item.requirement_id for item in analysis.missing_requirements) == (
    "example.missing-a",
    "example.missing-b",
)
```

No regression tests are added yet.

- [ ] **Step 6: Commit source implementation**

```bash
git add packages/rakit-core/src/rakit_core/integrations.py \
        packages/rakit-core/src/rakit_core/capabilities.py \
        packages/rakit-core/src/rakit_core/__init__.py
git commit -m "feat(core): add aggregate capability analysis"
```

---

### Task 2: Add configured integration inventory and aggregate compiler failure

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/compiler.py`

**Interfaces:**
- Consumes: `ConfiguredIntegration`, `CapabilityAnalysis`, `analyze_capabilities()` from Task 1.
- Produces:
  - `ApplicationBuilder.register_configured_integration(integration: ConfiguredIntegration) -> None`
  - `ApplicationBuilder.configured_integrations -> tuple[ConfiguredIntegration, ...]`
  - `CapabilityConfigurationError`
  - `CompiledApplication.configured_integrations`
  - `CompiledApplication.capability_analysis`

- [ ] **Step 1: Extend `ApplicationBuilder` configured diagnostics state**

Add a dedicated configured-integration list/registry separate from `_capability_providers`.

```python
_configured_integrations: list[ConfiguredIntegration] = field(default_factory=list)

@property
def configured_integrations(self) -> tuple[ConfiguredIntegration, ...]:
    return tuple(
        sorted(
            self._configured_integrations,
            key=lambda item: (
                item.integration_id is None,
                item.integration_id or "",
                item.category,
                item.display_name,
            ),
        )
    )
```

`register_configured_integration()` must:

- call `_check_not_compiled()`;
- reject duplicate non-null `integration_id` values with `CONFIG_INVALID` and reason `duplicate_configured_integration`;
- permit identity-less custom/unknown records without fabricating an official id.

- [ ] **Step 2: Include configured integrations in plugin rollback snapshots**

Extend `_InstallSnapshot.capture()` and `.restore()` so a plugin that registers an integration and then fails leaves no metadata behind.

- [ ] **Step 3: Define aggregate compiler exception**

Create a `CapabilityConfigurationError(RakitError)` in `compiler.py` that carries both:

```python
analysis: CapabilityAnalysis
configured_integrations: tuple[ConfiguredIntegration, ...]
```

Its `code` remains `ErrorCode.CONFIG_INVALID`, status `500`, and `details` use a deterministic serializable structure:

```python
{
    "reason": "missing_capabilities",
    "available": list(analysis.available.names),
    "providers": [
        {"id": provider.provider_id, "capabilities": list(provider.capabilities.names)}
        for provider in analysis.providers
    ],
    "requirements": [
        {
            "id": report.requirement.requirement_id,
            "status": "satisfied" if report.satisfied else "missing",
            "required": list(report.requirement.required.names),
            "available": list(report.available.names),
            "missing": list(report.missing.names),
            "providers": list(report.provider_ids),
        }
        for report in analysis.reports
    ],
    "missing_requirements": [
        requirement.requirement_id for requirement in analysis.missing_requirements
    ],
    "configured_integrations": [...],
}
```

Human exception text may summarize missing requirement ids, but tooling must never need to parse that text.

- [ ] **Step 4: Replace compiler fail-first capability validation**

Replace the repeated `require_capabilities(...)` calls with:

```python
analysis = analyze_capabilities(capability_requirements, builder.capability_providers)
if not analysis.valid:
    raise CapabilityConfigurationError(
        analysis=analysis,
        configured_integrations=builder.configured_integrations,
    )
```

All requirements must be evaluated before the error is raised.

- [ ] **Step 5: Persist diagnostics on valid `CompiledApplication`**

Extend `CompiledApplication` with:

```python
configured_integrations: tuple[ConfiguredIntegration, ...] = ()
capability_analysis: CapabilityAnalysis | None = None
```

For compiler-produced applications, `capability_analysis` must always be populated. The default remains `None` so deliberately hand-constructed test doubles remain straightforward until regression updates land.

- [ ] **Step 6: Non-test manual compiler smoke**

Use a plain Python source runner to build an `ApplicationBuilder` with two unsatisfied requirements and assert that one `CapabilityConfigurationError` contains both missing ids and all configured integration metadata.

- [ ] **Step 7: Commit compiler source**

```bash
git add packages/rakit-core/src/rakit_core/compiler.py
git commit -m "feat(core): aggregate configured capability diagnostics"
```

---

### Task 3: Register first-party configured integrations honestly

**Files:**
- Create: `packages/rakit-web/src/rakit_web/discovery.py`
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/discovery.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/plugin.py`
- Create: `packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/discovery.py`
- Modify: `packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/backend.py`
- Modify: `packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/sessions.py`
- Create: `packages/rakit-storage-local/src/rakit_storage_local/discovery.py`
- Modify: `packages/rakit-storage-local/src/rakit_storage_local/plugin.py`

**Interfaces:**
- Consumes: `IntegrationDescriptor`, `ConfiguredIntegration`, `integration_descriptor_from()`.
- Produces first-party integration descriptor constants:
  - `STARLETTE_INTEGRATION`
  - `PYDANTIC_INTEGRATION`
  - `SQLALCHEMY_INTEGRATION`
  - `AUTH_SQLALCHEMY_INTEGRATION`
  - `STORAGE_LOCAL_INTEGRATION`

- [ ] **Step 1: Add lightweight descriptors for web/schema**

`rakit_web.discovery` must import only Rakit core capability metadata and define:

```python
STARLETTE_INTEGRATION = IntegrationDescriptor(
    integration_id="web.starlette",
    category="web",
    display_name="Starlette",
    advertised_capabilities=STARLETTE_WEB_CAPABILITIES.capabilities,
)

PYDANTIC_INTEGRATION = IntegrationDescriptor(
    integration_id="schema.pydantic",
    category="schema",
    display_name="Pydantic",
    advertised_capabilities=PYDANTIC_SCHEMA_CAPABILITIES.capabilities,
)
```

If importing existing provider constants would drag heavy runtime modules, move the provider constants into the lightweight discovery/capability module and import them from there instead of duplicating capability names.

- [ ] **Step 2: Record built-in web/schema integrations during `Admin` construction**

Immediately after registering each existing provider, register its configured integration:

```python
self._builder.register_capability_provider(STARLETTE_WEB_CAPABILITIES)
self._builder.register_configured_integration(
    ConfiguredIntegration.from_descriptor(STARLETTE_INTEGRATION)
)
```

Do the same for the selected schema adapter when its `provider` corresponds to first-party Pydantic metadata. For a custom schema adapter with no integration descriptor, register a conservative identity-less record:

```python
ConfiguredIntegration(
    integration_id=None,
    category="schema",
    display_name="Custom / unknown schema",
)
```

Do not infer a custom adapter id from its class/module name.

- [ ] **Step 3: Add SQLAlchemy persistence descriptor and registration**

`rakit_sqlalchemy.discovery` defines `persistence.sqlalchemy` using `SQLALCHEMY_CAPABILITIES.capabilities`. `SQLAlchemyPlugin.configure()` registers both the existing capability provider and `ConfiguredIntegration.from_descriptor(SQLALCHEMY_INTEGRATION)`.

- [ ] **Step 4: Add local storage descriptor and registration**

`rakit_storage_local.discovery` defines:

```python
STORAGE_LOCAL_INTEGRATION = IntegrationDescriptor(
    integration_id="storage.local",
    category="storage",
    display_name="Local storage",
)
```

`LocalStoragePlugin.configure()` registers the configured integration once per plugin installation, not once per named storage backend.

- [ ] **Step 5: Add optional SQLAlchemy auth metadata marker**

`rakit_auth_sqlalchemy.discovery` defines:

```python
AUTH_SQLALCHEMY_INTEGRATION = IntegrationDescriptor(
    integration_id="auth.sqlalchemy",
    category="authentication",
    display_name="SQLAlchemy authentication",
)
```

Both concrete built-in classes expose the same marker without changing core auth protocols:

```python
class SQLAlchemyAuthBackend:
    rakit_integration = AUTH_SQLALCHEMY_INTEGRATION

class SQLAlchemySessionStore:
    rakit_integration = AUTH_SQLALCHEMY_INTEGRATION
```

- [ ] **Step 6: Record constructor-composed auth metadata in `Admin`**

When both `auth_backend` and `session_store` are supplied:

```python
auth_descriptor = integration_descriptor_from(auth_backend)
session_descriptor = integration_descriptor_from(session_store)
```

Rules:

- both `None`: register `ConfiguredIntegration(None, "authentication", "Custom / unknown authentication")`;
- exactly one present: raise `CONFIG_INVALID` with reason `auth_integration_metadata_incomplete`;
- both present with different ids/categories: raise `CONFIG_INVALID` with reason `auth_integration_metadata_conflict`;
- both same descriptor identity: register one configured integration.

Do not change `AuthBackend` or `SessionStore` Protocol requirements.

- [ ] **Step 7: Plain-Python configured inventory smoke**

Exercise:

- default Admin → Starlette + Pydantic configured;
- Admin + SQLAlchemy plugin → persistence added;
- Admin + LocalStorage plugin → storage added;
- built-in SQLAlchemy auth pair → `auth.sqlalchemy` added;
- custom auth pair with no metadata → identity-less custom auth record;
- mismatched marker pair → explicit error.

- [ ] **Step 8: Commit configured first-party source**

```bash
git add packages/rakit-web/src/rakit_web/discovery.py \
        packages/rakit-web/src/rakit_web/admin.py \
        packages/rakit-sqlalchemy/src/rakit_sqlalchemy/discovery.py \
        packages/rakit-sqlalchemy/src/rakit_sqlalchemy/plugin.py \
        packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/discovery.py \
        packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/backend.py \
        packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/sessions.py \
        packages/rakit-storage-local/src/rakit_storage_local/discovery.py \
        packages/rakit-storage-local/src/rakit_storage_local/plugin.py
git commit -m "feat: record configured integration inventory"
```

---

### Task 4: Publish generic installed-integration metadata

**Files:**
- Modify: `packages/rakit-web/pyproject.toml`
- Modify: `packages/rakit-sqlalchemy/pyproject.toml`
- Modify: `packages/rakit-auth-sqlalchemy/pyproject.toml`
- Modify: `packages/rakit-storage-local/pyproject.toml`
- Create: `packages/rakit-server-uvicorn/src/rakit_server_uvicorn/capabilities.py`
- Create: `packages/rakit-server-uvicorn/src/rakit_server_uvicorn/discovery.py`
- Modify: `packages/rakit-server-uvicorn/src/rakit_server_uvicorn/server.py`
- Modify: `packages/rakit-server-uvicorn/pyproject.toml`
- Create: `packages/rakit-server-granian/src/rakit_server_granian/capabilities.py`
- Create: `packages/rakit-server-granian/src/rakit_server_granian/discovery.py`
- Modify: `packages/rakit-server-granian/src/rakit_server_granian/server.py`
- Modify: `packages/rakit-server-granian/pyproject.toml`
- Modify: `uv.lock` only if uv reports metadata lock changes.

**Interfaces:**
- Produces entry-point group `rakit.integrations`.
- Each entry-point value resolves directly to one `IntegrationDescriptor` instance.
- Entry-point name must exactly equal `descriptor.integration_id`.

- [ ] **Step 1: Declare web/schema/persistence/auth/storage entry points**

Add PEP 621 metadata such as:

```toml
[project.entry-points."rakit.integrations"]
"web.starlette" = "rakit_web.discovery:STARLETTE_INTEGRATION"
"schema.pydantic" = "rakit_web.discovery:PYDANTIC_INTEGRATION"
```

and equivalent single-entry declarations for:

```text
persistence.sqlalchemy
auth.sqlalchemy
storage.local
```

- [ ] **Step 2: Factor Uvicorn capability metadata away from heavy runtime import**

Create a lightweight shared constant:

```python
UVICORN_SERVER_CAPABILITIES = ServerCapabilities(
    async_serve=True,
    graceful_stop=True,
    reload=True,
    workers=True,
    app_object=True,
    import_string=True,
)
```

`server.py` consumes that constant rather than declaring a second copy.

`discovery.py` defines:

```python
UVICORN_INTEGRATION = IntegrationDescriptor(
    integration_id="server.uvicorn",
    category="server",
    display_name="Uvicorn",
    advertised_capabilities=UVICORN_SERVER_CAPABILITIES.capability_set,
)
```

The discovery module must not import `uvicorn`.

- [ ] **Step 3: Apply the same shared-metadata pattern to Granian**

Define `GRANIAN_SERVER_CAPABILITIES` from the existing adapter behavior and reuse it in both the runtime adapter and the descriptor. The discovery module must not import `granian`.

- [ ] **Step 4: Add server integration entry points without changing `rakit.servers`**

Each server distribution must contain both groups:

```toml
[project.entry-points."rakit.servers"]
uvicorn = "rakit_server_uvicorn:UvicornServer"

[project.entry-points."rakit.integrations"]
"server.uvicorn" = "rakit_server_uvicorn.discovery:UVICORN_INTEGRATION"
```

Granian follows the equivalent pattern. Do not rename or remove `rakit.servers`.

- [ ] **Step 5: Refresh `uv.lock` only if required**

Run:

```bash
uv lock
uv sync --locked
```

Commit a lockfile change only when workspace metadata actually changes it.

- [ ] **Step 6: Inspect built distributions without pytest**

Build the affected wheels and inspect their entry points or use `importlib.metadata` from a clean workspace install. Verify exactly seven first-party descriptors are visible and `rakit.servers` still exposes Uvicorn/Granian unchanged.

- [ ] **Step 7: Commit installed metadata source**

```bash
git add packages/rakit-web/pyproject.toml \
        packages/rakit-sqlalchemy/pyproject.toml \
        packages/rakit-auth-sqlalchemy/pyproject.toml \
        packages/rakit-storage-local/pyproject.toml \
        packages/rakit-server-uvicorn \
        packages/rakit-server-granian \
        uv.lock
git commit -m "feat: publish installed integration metadata"
```

---

### Task 5: Implement installed discovery and normalized inspection reports

**Files:**
- Create: `packages/rakit/src/rakit/_integration_discovery.py`
- Create: `packages/rakit/src/rakit/_capability_inspection.py`

**Interfaces:**
- Consumes: `IntegrationDescriptor`, `ConfiguredIntegration`, `CapabilityAnalysis`, `CompiledApplication`, `CapabilityConfigurationError`.
- Produces:
  - `InstalledIntegrationDiscoveryError`
  - `discover_installed_integrations() -> tuple[IntegrationDescriptor, ...]`
  - `CapabilityInspectionReport`
  - `inspection_from_compiled(...)`
  - `inspection_from_capability_error(...)`
  - deterministic `.to_dict()` and human renderer.

- [ ] **Step 1: Implement strict installed entry-point discovery**

Use:

```python
from importlib.metadata import EntryPoint, entry_points

INTEGRATION_ENTRY_POINT_GROUP = "rakit.integrations"
```

`discover_installed_integrations()` must:

1. enumerate only `rakit.integrations`;
2. sort entry points deterministically before loading;
3. load each entry point;
4. require an `IntegrationDescriptor` instance, not a factory/callable;
5. require `entry_point.name == descriptor.integration_id`;
6. reject duplicate descriptor ids;
7. wrap load/type/name/duplicate failures in `InstalledIntegrationDiscoveryError` with the failing id/name in the message;
8. return descriptors sorted by `integration_id`.

Do not import arbitrary packages by guessed name.

- [ ] **Step 2: Define normalized report values**

Use dataclasses with explicit conversion instead of serializing arbitrary objects directly. Recommended shape:

```python
@dataclass(frozen=True, slots=True)
class CapabilityInspectionReport:
    schema_version: int
    target: str | None
    valid: bool | None
    configured: ConfiguredInspection | None
    installed: tuple[InstalledIntegrationInspection, ...] | None

    def to_dict(self) -> dict[str, object]: ...
```

`schema_version` is always `1` in C4.

Configured provider records contain only:

```text
id
capabilities[]
```

Requirement records contain:

```text
id
status
required[]
available[]
missing[]
providers[]
```

Configured integration records contain:

```text
id (nullable)
category
display_name
```

Installed records contain:

```text
id
category
display_name
advertised_capabilities[]
```

- [ ] **Step 3: Build configured reports from either valid compile or aggregate capability error**

`inspection_from_compiled(target, compiled, installed=None)` reads `compiled.configured_integrations` and `compiled.capability_analysis`.

`inspection_from_capability_error(target, error, installed=None)` reads the exception's `configured_integrations` and `analysis` directly; it must not parse the exception message.

Both paths produce the same normalized configured model.

- [ ] **Step 4: Implement deterministic human rendering**

Human output must contain the locked sections:

```text
Application: <target>
Status: valid|invalid

Configured integrations:
...

Capability providers:
...

Requirements:
...
```

When installed view is requested, append:

```text
Installed integrations:
...
```

Installed-only mode must not fabricate Application/Status/configured sections.

- [ ] **Step 5: Implement JSON conversion with explicit nulls**

Installed-only JSON must produce exactly the semantic shape:

```json
{
  "schema_version": 1,
  "target": null,
  "valid": null,
  "configured": null,
  "installed": []
}
```

Use explicit dictionaries/lists and canonical array ordering; do not expose dataclass repr or Python enum objects.

- [ ] **Step 6: Plain-Python discovery/report smoke**

Without pytest, exercise:

- fake valid compiled app;
- fake aggregate error with two missing requirements;
- installed-only empty and populated descriptor sequences;
- JSON `schema_version == 1`;
- malformed entry point type failure;
- duplicate descriptor id failure.

- [ ] **Step 7: Commit facade source**

```bash
git add packages/rakit/src/rakit/_integration_discovery.py \
        packages/rakit/src/rakit/_capability_inspection.py
git commit -m "feat: add capability inspection reports"
```

---

### Task 6: Add `rakit capabilities` and upgrade `rakit check`

**Files:**
- Modify: `packages/rakit/src/rakit/cli.py`

**Interfaces:**
- Consumes all Task 5 inspection/discovery APIs and Task 2 `CapabilityConfigurationError`.
- Produces CLI forms locked by the spec.

- [ ] **Step 1: Keep `check` as validator and migrate aggregate errors**

`check()` catches `CapabilityConfigurationError`, prints all missing requirements, then exits non-zero through `click.ClickException`.

Output must identify every missing requirement rather than the former singular `Capability requirement:` shape. It must not call installed discovery.

- [ ] **Step 2: Add optional TARGET `capabilities` command**

Use Click signature equivalent to:

```python
@cli.command()
@click.argument("target", required=False)
@click.option("--installed", is_flag=True, default=False)
@click.option("--json", "json_output", is_flag=True, default=False)
def capabilities(target: str | None, installed: bool, json_output: bool) -> None:
    ...
```

Reject no-target/no-installed invocation with `click.UsageError`.

- [ ] **Step 3: Implement inspector target semantics**

For a target:

```python
try:
    compiled = load_object(target).compile()
except CapabilityConfigurationError as exc:
    report = inspection_from_capability_error(target, exc, installed=installed_view)
else:
    report = inspection_from_compiled(target, compiled, installed=installed_view)
```

Do not convert capability-invalid state into a non-zero exit.

Other import/config errors remain failures and should be surfaced as actionable Click errors rather than being relabelled as missing capabilities.

- [ ] **Step 4: Implement installed-only and combined views**

Call `discover_installed_integrations()` only when `--installed` is requested.

Installed-only:

```text
TARGET=None
configured=None
valid=None
```

Combined target + installed keeps two distinct report sections.

- [ ] **Step 5: Render human or JSON from the same report**

For JSON:

```python
click.echo(json.dumps(report.to_dict(), indent=2))
```

For text, echo only the shared human renderer output. Do not maintain separate data-building code in `cli.py`.

- [ ] **Step 6: Run the complete source-first manual matrix before adding tests**

Run real CLI commands against temporary example targets or the reference app:

```bash
rakit capabilities example:admin
rakit capabilities example:admin --json
rakit capabilities --installed
rakit capabilities --installed --json
rakit capabilities example:admin --installed
rakit capabilities example:admin --installed --json
rakit check example:admin
```

Also run an intentionally invalid target with at least two missing requirements and verify:

```text
rakit capabilities invalid:admin -> exit 0, valid false, both missing requirements visible
rakit check invalid:admin        -> non-zero, both missing requirements visible
```

Verify malformed/duplicate/load-failing fake entry points fail non-zero and installed integrations never appear as configured unless the app actually records them.

If the current environment cannot execute the workspace directly, use a temporary GitHub Actions source-smoke workflow as execution infrastructure, then delete that workflow before regression/final diff acceptance. The smoke itself must use plain Python/CLI commands, not pytest.

- [ ] **Step 7: Record source-first evidence**

Update a concise execution-state note under `docs/superpowers/plans/` with the command matrix, branch SHA, and pass/fail result. Do not leave temporary trigger/debug workflow files in the final diff.

- [ ] **Step 8: Commit CLI source after manual verification passes**

```bash
git add packages/rakit/src/rakit/cli.py \
        docs/superpowers/plans/2026-08-21-c4-capability-discovery-execution-state.md
git commit -m "feat: expose capability discovery CLI"
```

---

### Task 7: Add regression tests after source behavior is verified

**Files:**
- Modify: `packages/rakit-core/tests/test_capabilities.py`
- Modify: `packages/rakit-core/tests/test_compiler.py`
- Create: `packages/rakit-core/tests/test_integrations.py`
- Modify: `packages/rakit/tests/test_capability_cli.py`
- Create: `packages/rakit/tests/test_integration_discovery.py`
- Add/modify focused owning-package tests as required for web/schema/SQLAlchemy/auth/storage/server metadata.
- Modify release/artifact tests only if artifact metadata coverage needs explicit `rakit.integrations` assertions.

**Interfaces:**
- Tests source contracts from Tasks 1–6; no source redesign in this task unless a regression exposes a concrete bug.

- [ ] **Step 1: Replace fail-fast core capability tests with aggregate-analysis coverage**

Add tests equivalent to:

```python
def test_capability_analysis_reports_all_missing_requirements_deterministically():
    analysis = analyze_capabilities(
        (
            CapabilityRequirement.of("z", "missing.z"),
            CapabilityRequirement.of("a", "missing.a"),
        ),
        (),
    )
    assert analysis.valid is False
    assert tuple(r.requirement.requirement_id for r in analysis.reports) == ("a", "z")
    assert tuple(r.requirement_id for r in analysis.missing_requirements) == ("a", "z")
```

Cover duplicate provider ids and duplicate requirement ids.

- [ ] **Step 2: Add configured integration primitive tests**

`test_integrations.py` covers:

- trimmed/non-empty validation;
- descriptor → configured conversion;
- metadata marker lookup;
- invalid marker type rejection;
- identity-less configured integration allowed without fabricated id.

- [ ] **Step 3: Add compiler aggregate/rollback tests**

Cover:

- one error contains every missing requirement;
- structured details include providers/requirements/configured integrations;
- valid compile stores `capability_analysis`;
- duplicate configured id rejected;
- failed plugin install rolls configured inventory back.

- [ ] **Step 4: Add configured first-party integration regressions**

Owning package tests must verify:

- Admin records Starlette/Pydantic;
- custom schema reports unknown instead of fabricated official id;
- SQLAlchemy plugin records persistence integration;
- LocalStorage plugin records one storage integration regardless of backend count;
- built-in SQLAlchemy auth markers match;
- metadata absent on both custom auth pieces stays usable and records custom/unknown;
- one-sided or mismatched auth metadata fails explicitly.

- [ ] **Step 5: Add installed discovery tests with fake entry points**

`test_integration_discovery.py` covers:

- deterministic sort;
- direct descriptor load;
- entry-point name/id mismatch;
- wrong returned type;
- duplicate id;
- load exception;
- zero integrations;
- no package-name scanning fallback.

Inject/factor the entry-point iterable so these tests do not depend on the developer machine's globally installed packages.

- [ ] **Step 6: Expand CLI regression coverage**

`test_capability_cli.py` covers exact semantics:

- configured valid text;
- configured invalid text exits `0` under `capabilities`;
- same invalid target exits non-zero under `check`;
- all missing requirements printed;
- installed-only text;
- target + installed text;
- `--json` schema version `1`;
- installed-only JSON explicit nulls;
- no target/no `--installed` usage failure;
- installed discovery error → non-zero;
- non-capability target error → non-zero;
- deterministic ordering.

Parse JSON in assertions; do not assert JSON via substring only.

- [ ] **Step 7: Verify distribution entry-point metadata**

Add artifact/package metadata assertions that the clean installed distributions expose exactly the intended first-party `rakit.integrations` entries while existing `rakit.servers` entries remain unchanged.

- [ ] **Step 8: Run focused regression suites**

Run:

```bash
uv run pytest packages/rakit-core/tests/test_capabilities.py -q
uv run pytest packages/rakit-core/tests/test_integrations.py -q
uv run pytest packages/rakit-core/tests/test_compiler.py -q
uv run pytest packages/rakit/tests/test_capability_cli.py -q
uv run pytest packages/rakit/tests/test_integration_discovery.py -q
```

Then run all owning-package focused tests changed by Task 7.

- [ ] **Step 9: Commit regression coverage**

```bash
git add packages/*/tests tests/release scripts/check_artifacts.py
git commit -m "test: cover C4 capability discovery"
```

Only include `tests/release` / `scripts/check_artifacts.py` if they genuinely changed.

---

### Task 8: Documentation, roadmap closure, and exact-head verification

**Files:**
- Create: `docs/guides/capability-discovery.md`
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`
- Modify: `mkdocs.yml` only if navigation requires it.
- Modify: `docs/superpowers/plans/2026-08-21-c4-capability-discovery-execution-state.md`

**Interfaces:**
- Consumes verified CLI/source behavior from Tasks 1–7.
- Produces canonical user documentation and C4 completion state.

- [ ] **Step 1: Document installed vs configured semantics**

The guide must explicitly state:

```text
installed != configured != compiler capability provider
```

Include examples for:

```bash
rakit check myapp:admin
rakit capabilities myapp:admin
rakit capabilities --installed
rakit capabilities myapp:admin --installed --json
```

Explain that advertised installed capabilities are potential implementation capabilities, not active app capabilities.

- [ ] **Step 2: Document third-party `rakit.integrations` participation**

Show a minimal descriptor and entry point:

```python
MY_INTEGRATION = IntegrationDescriptor(
    integration_id="persistence.example",
    category="persistence",
    display_name="Example persistence",
    advertised_capabilities=CapabilitySet.of("persistence.read"),
)
```

```toml
[project.entry-points."rakit.integrations"]
"persistence.example" = "example_rakit.discovery:MY_INTEGRATION"
```

State that descriptor discovery never installs or activates the integration.

- [ ] **Step 3: Close C4 roadmap state**

Update roadmap:

```text
Phase C4 capability discovery -> Complete
Phase C overall developer experience/lifecycle ergonomics -> Complete if C4 is the final committed C workstream
Phase D adapter ecosystem -> Next
```

Fix the stale near-term sequence so it begins with D rather than C3/C4 after C4 is complete.

Do not alter later Phase D–P scope except where wording must reference the completed discovery contract.

- [ ] **Step 4: Update CHANGELOG**

Add a concise C4 entry covering:

- aggregate capability analysis;
- configured integration inventory;
- `rakit capabilities` + JSON schema v1;
- generic `rakit.integrations` discovery;
- first-party metadata;
- aggregate `rakit check` diagnostics.

No version bump.

- [ ] **Step 5: Run pre-closure full CI on the implementation head**

Use the repository's normal CI on the exact branch head. Required gates:

- Ruff format;
- Ruff lint;
- `ty`;
- full pytest on Python 3.12, 3.13, 3.14;
- lowest-direct dependencies;
- latest dependencies;
- coverage;
- strict MkDocs;
- artifact validation/dry run;
- generated web-asset reproducibility.

Fix root causes; do not suppress failures merely to make CI green.

- [ ] **Step 6: Commit closure docs**

```bash
git add docs/guides/capability-discovery.md \
        docs/roadmap.md \
        CHANGELOG.md \
        mkdocs.yml \
        docs/superpowers/plans/2026-08-21-c4-capability-discovery-execution-state.md
git commit -m "docs: close C4 capability discovery"
```

Only include `mkdocs.yml` if it changed.

- [ ] **Step 7: Run final exact-head CI after closure commit**

The final evidence must be from the SHA containing source, tests, and closure docs. Do not reuse a green CI run from the pre-closure SHA.

Record:

```text
final head SHA
workflow run id
workflow conclusion
all required job conclusions
```

in the execution-state document only if doing so does not force an endless verification-SHA cycle. If the run id itself is written after CI, treat that note as bookkeeping and verify the resulting docs-only head with the relevant docs/format gates or keep run evidence in the PR body instead. Prefer PR-body evidence to avoid unnecessary head mutation.

- [ ] **Step 8: Audit final diff against `main`**

Confirm:

- no temporary source-smoke workflows;
- no trigger/debug files;
- no changes to canonical CI workflows unless genuinely required by C4;
- no release/tag/version changes;
- only C4 source/tests/docs/package metadata/lockfile changes remain.

- [ ] **Step 9: Create/update draft PR, but do not merge**

PR summary must include:

- installed vs configured invariant;
- aggregate analysis behavior;
- CLI/JSON contract;
- source-first manual evidence;
- focused regression evidence;
- exact-head CI evidence.

Keep the PR unmerged until the maintainer explicitly requests merge.

---

## Plan Self-Review

### Spec coverage

Every locked spec requirement maps to a task:

- aggregate `CapabilityAnalysis` → Tasks 1–2;
- configured integration inventory → Tasks 2–3;
- auth optional diagnostic marker semantics → Task 3;
- generic `rakit.integrations` contract → Tasks 4–5;
- first-party seven descriptors → Task 4;
- installed discovery failure rules → Task 5;
- `rakit capabilities`/`rakit check` separation → Task 6;
- inspector exit `0` with invalid capability graph → Tasks 5–7;
- JSON schema v1 → Tasks 5–7;
- deterministic output → Tasks 1, 2, 5, 7;
- installed never activates configured → Tasks 3–7;
- server runtime registry unchanged → Tasks 4, 6, 7;
- source-first manual verification before tests → Task 6 before Task 7;
- docs/roadmap D-next closure → Task 8;
- exact-head full CI → Task 8.

### Placeholder scan

The plan contains no implementation `TBD`, `TODO`, or unspecified "handle errors" steps. Each error class, registry behavior, CLI form, descriptor id, category, validation rule, and verification gate is explicitly named.

### Type consistency

- Installed metadata uses `IntegrationDescriptor` throughout.
- Configured inventory uses `ConfiguredIntegration` throughout.
- Constructor-composed implementations optionally expose `rakit_integration: IntegrationDescriptor`.
- Compiler analysis uses one `CapabilityAnalysis` value for valid and invalid graphs.
- `CapabilityConfigurationError` carries the same `CapabilityAnalysis` plus configured inventory for invalid-target inspection.
- CLI report composition consumes either `CompiledApplication` or `CapabilityConfigurationError`, but renders through one `CapabilityInspectionReport`.
