# C1 Friendly CRUD and Lifecycle Ergonomics — Design

## Status

Approved implementation direction for Phase C1.

## Context

Phase B's realistic `examples/reference_app` proved that Rakit's public surfaces are coherent, but it also exposed repetitive composition work for ordinary mutable model resources:

- a `ModelAdmin` declares read/query/API policy;
- the same resource then needs a separate `Admin.register_write(...)` call;
- SQLAlchemy applications manually construct `SQLAlchemyMutationService` and repeat model, resource id, identity field, permission names, token service, form schema, and writable fields;
- application startup, readiness, and shutdown are registered by reaching through `admin.lifecycle` even though those hooks are part of ordinary application composition.

C1 removes this proven boilerplate without changing Rakit's safety model.

## Goals

1. Allow an ordinary mutable `ModelAdmin` to declare an explicit write policy next to its read/query policy.
2. Let the selected model adapter materialize the concrete mutation service from that neutral write policy.
3. Preserve explicit writable fields, forms, concurrency policy, authorization, transactions, storage behavior, and fail-closed adapter capability checks.
4. Add small `Admin` lifecycle convenience methods for startup, readiness checks, and shutdown.
5. Convert the reference application to the new public path so it remains the acceptance pressure for the API.
6. Keep existing `Admin.register_write(...)` and `Admin.register_write_resource(...)` working as advanced/manual escape hatches.

## Non-goals

C1 does not:

- generate forms automatically from ORM metadata;
- infer writable fields from every mapped column;
- make read registration implicitly writable;
- introduce a universal ORM or universal mutation adapter;
- hide transaction ownership;
- auto-install persistence/auth/storage plugins;
- redesign actions, relationships, generated REST, or authentication;
- add project scaffolding (`rakit init` is C2);
- rename existing public APIs.

## Design choice

### Recommended approach: neutral write declaration + adapter write provider

A `ModelAdmin` may opt into writes with a neutral `ResourceWriteDefinition`:

```python
class ProductAdmin(ModelAdmin):
    resource_id = "products"
    path = "/products"
    label = "Products"
    singular_label = "Product"
    model = Product
    list_fields = ("id", "sku", "name", "status")
    detail_fields = ("id", "sku", "name", "status")

    write = ResourceWriteDefinition(
        form_schema=PRODUCT_FORM,
        writable_fields=("sku", "name", "price_cents", "inventory_count", "status", "image"),
        version_field="version",
        success_message="Product saved.",
        htmx_refresh_targets=("rakit:dashboard-refresh",),
    )
```

`Admin.register(ProductAdmin)` remains the single resource registration call. The resource is writable only because `write` is explicitly declared; `write = None` remains read-only.

The adapter runtime that claims the model may expose a `ResourceWriteServiceProvider`. If the resource declares `write` but the selected adapter has no provider, registration fails closed with a configuration error. Rakit must never silently downgrade the resource to read-only.

### Alternatives rejected

#### Full automatic CRUD from ORM metadata

This would be shorter, but it weakens Rakit's explicit writable allowlist, makes form semantics adapter-driven, and pushes the framework toward a universal-ORM abstraction. Rejected.

#### SQLAlchemy-only helper in application code

A helper such as `sqlalchemy_write(...)` would reduce some boilerplate, but it would make the public `ModelAdmin` lifecycle depend on the current first adapter and provide no honest extension point for future adapters. Rejected in favor of a neutral declaration plus adapter provider.

#### Keep `register_write(...)` as the only path

This preserves the current design but does not solve the friction C1 exists to address. The manual path remains available for advanced cases.

## Public contracts

### `ResourceWriteDefinition`

Location: `rakit_core.admin_types`, re-exported from `rakit`.

Frozen declaration with:

```python
@dataclass(frozen=True, slots=True)
class ResourceWriteDefinition:
    form_schema: FormSchema
    writable_fields: tuple[str, ...]
    version_field: str | None = None
    success_message: str | None = None
    htmx_refresh_targets: tuple[str, ...] = ()
```

Validation rules:

- `form_schema` must be a `FormSchema`;
- `writable_fields` must be non-empty, unique, non-empty strings;
- every writable field must exist in the form schema;
- every listed field must be writable in the form schema;
- `version_field`, when present, is a non-empty string;
- refresh targets are unique non-empty strings.

Identity fields are deliberately not part of the declaration. Identity is an adapter/model fact, not an application write policy, and the SQLAlchemy adapter already has safe identity introspection.

`ResourceAdmin` gains:

```python
write: ResourceWriteDefinition | None = None
```

Read-only behavior remains the default.

### Adapter write-provider contract

Add framework-neutral runtime contracts alongside `ResourceAdapterRuntime`:

```python
@dataclass(frozen=True, slots=True)
class ResourceWriteServiceContext:
    admin_id: str
    resource_id: str
    definition: ResourceWriteDefinition
    token_service: TokenService

class ResourceWriteServiceProvider(Protocol):
    def build(self, context: ResourceWriteServiceContext) -> object: ...
```

`ResourceAdapterRuntime` gains:

```python
write_service_provider: ResourceWriteServiceProvider | None = None
```

The returned object must satisfy the existing write-route mutation-service contract. `Admin` validates the provider result before binding it.

The context always carries a token service because ordinary web writes require authenticated, secret-backed Admin composition. If authentication/secret requirements are not met, existing write registration safety checks remain authoritative.

### SQLAlchemy provider

`SQLAlchemyPlugin._claim(...)` returns a runtime with a SQLAlchemy write provider bound to the claimed model and session factory.

The provider:

- derives the single identity field with `inspect_model(model)`;
- passes the explicit `form_schema` and `writable_fields` unchanged;
- uses Admin's canonical token service;
- passes `version_field` unchanged;
- uses `resource_id` from the declaration context;
- derives delete and force-overwrite permissions as:
  - `<admin_id>.resources.<resource_id>.delete`
  - `<admin_id>.resources.<resource_id>.force_overwrite`
- returns `SQLAlchemyMutationService`.

No model column becomes writable merely because SQLAlchemy reports it writable.

### `Admin.register(...)` behavior

After the normal adapter claim and resource registration succeed:

1. resolve `admin_cls.write`;
2. if `None`, do nothing;
3. require a model-backed resource and a selected adapter write provider;
4. build a write token service from the same configured Admin secret/key id used by the existing write runtime;
5. ask the adapter provider to build the mutation service;
6. call the existing `Admin.register_write(...)` path with the declaration's form/presentation values.

This intentionally reuses `register_write(...)` rather than creating a second transport/security pipeline.

If a declaration cannot be honored, registration raises a precise configuration error. There is no silent fallback to read-only.

### Manual compatibility path

These remain public and supported:

```python
admin.register_write(...)
admin.register_write_resource(...)
```

They are the escape hatch for custom mutation services, unusual authorization behavior, custom hooks/scoping, or non-model resources.

Declaring `ModelAdmin.write` and then manually registering another write binding for the same resource is a duplicate configuration error; the application must choose one composition path.

## Lifecycle ergonomics

`Admin` gains thin convenience methods:

```python
def on_startup(self, callback: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]: ...
def on_shutdown(self, callback: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]: ...
def add_health_check(
    self,
    name: str,
    check: Callable[[], Awaitable[bool]],
    *,
    critical: bool,
    timeout_seconds: float = 2.0,
    cache_seconds: float = 5.0,
) -> None: ...
```

`on_startup` and `on_shutdown` return the callback unchanged, so they work both as direct registration methods and decorators. They delegate to the existing `LifecycleManager`; startup remains fail-fast and shutdown remains LIFO/log-and-continue.

`add_health_check` delegates to the current lifecycle health-check implementation and does not change liveness/readiness semantics.

The underlying `admin.lifecycle` object remains public for advanced use.

## Reference application target

The reference app should become:

```python
for resource_admin in RESOURCE_ADMINS:
    admin.register(resource_admin)

admin.on_startup(_bootstrap)
admin.add_health_check("database", _database_ready, critical=True, timeout_seconds=2.0, cache_seconds=1.0)
admin.on_shutdown(dispose_database)
```

`ProductAdmin` and `OrderAdmin` own their `ResourceWriteDefinition`. The application no longer creates a second `TokenService` or resource-specific `SQLAlchemyMutationService` factories solely for ordinary CRUD composition.

## Error handling

C1 preserves fail-closed behavior.

Configuration errors include these reasons through the existing configuration error boundary:

- invalid write declaration;
- write declaration on a resource without a write-capable adapter;
- provider returns an invalid mutation service;
- missing auth/secret configuration required by the existing write routes;
- duplicate write binding.

No failure may silently remove mutation routes or weaken concurrency/authorization behavior.

## Backward compatibility

C1 is additive:

- existing read-only `ModelAdmin` subclasses behave unchanged;
- existing applications using `Admin.register_write(...)` behave unchanged;
- existing adapters that return only `data_source` / generated executor remain valid for read-only resources;
- only a resource that explicitly declares `write` requires the adapter write-provider capability.

## Verification strategy

The project workflow for this phase remains source-first:

1. implement core/adapter/web/reference-app source;
2. perform non-test review, import/type/lint review, and inspect resulting reference-app composition;
3. add focused regression tests only after source is stable;
4. run the full repository CI matrix and release gates.

Focused regression coverage must include:

- declaration validation;
- read-only resources remain read-only;
- declarative writes are materialized through an adapter provider;
- missing provider fails closed;
- SQLAlchemy provider derives identity and canonical permission names correctly;
- manual `register_write(...)` remains supported;
- lifecycle convenience methods preserve startup/shutdown/health semantics;
- reference-app subprocess smoke remains green using only the new composition path.

## Documentation and roadmap

Update the reference-app README and public roadmap when C1 passes final verification. Mark C1 complete and move the `Next` pointer to C2 only after the C1 integration PR lands on `main`.
