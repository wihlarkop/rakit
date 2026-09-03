# Rakit

> A composable Python framework for building admin panels, internal tools, dynamic dashboards, and APIs over any data source.

Rakit is an early-stage Python framework designed around explicit composition. Developers assemble
resources, pages, actions, endpoints, dashboards, adapters, themes, authentication, storage, and
application services without coupling the domain core to one web framework or ORM.

## Status

Rakit is in alpha release hardening. The codebase targets synchronized `0.1.0a1` artifacts, but the
release remains **unreleased** until the maintainer explicitly creates a release tag. Public APIs
may still evolve under the documented pre-1.0 compatibility policy.

## Design principles

- Secure by default, with security treated as a first-class system concern.
- Framework-agnostic core with a standalone ASGI runtime.
- Explicit registration, plugin activation, dependency injection, and lifecycle.
- One operation pipeline shared by HTML admin, custom endpoints, and generated APIs.
- Backend-neutral contracts with typed, capability-aware adapters.
- Progressive enhancement: server-rendered HTML works without JavaScript; HTMX improves supported flows.
- Batteries included, but replaceable through documented contracts.
- Fully typed public packages with reviewed import surfaces.

## Implemented alpha scope

- Standalone Starlette-based ASGI application with lifecycle-safe ASGI host composition.
- SQLAlchemy CRUD with relationships, filters, search, sorting, and pagination.
- Custom resources, pages, actions, endpoints, dashboards, and widgets.
- Optional SQLAlchemy authentication, Argon2 password hashing, sessions, and allow-only RBAC.
- Pydantic v2 validation and Jinja form rendering.
- HTMX progressive enhancement and bundled Tailwind CSS.
- Portable file storage with a secure private LocalStorage reference backend.
- Explicit DI scopes, transactions, events, deadlines, and cooperative cancellation.
- Optimistic concurrency, idempotency, signed destructive confirmations, and CSRF.
- CSP-safe light/dark/system themes and built-in accessibility quality gates.
- Structured logging, health/readiness, graceful shutdown, Uvicorn and Granian server adapters.
- Reusable adapter contracts plus release-level integration/security regression tests.

## Quick start

```python
from rakit import Admin, ResourceAdmin
from rakit.core import DataSourceCapabilities, PageResult, RecordIdentity


class Products:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult(
            items=({"id": 1, "name": "Clamp"},),
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=1,
        )

    async def count(self, query):
        return 1

    async def detail(self, identity: RecordIdentity):
        return {"id": 1, "name": "Clamp"}


class ProductAdmin(ResourceAdmin):
    resource_id = "products"
    path = "/products"
    label = "Products"
    singular_label = "Product"
    data_source = Products()
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


admin = Admin(title="Workshop", debug=True)
admin.register(ProductAdmin)
app = admin.asgi()
```

Validate and run:

```bash
rakit check myapp:admin
rakit run myapp:admin
```

## Example direction

The SQLAlchemy registration pattern remains executable and is preserved as a compatibility-tested
reference. Application code owns the engine lifecycle and gives Rakit a session factory.

```python
from rakit import Admin, ModelAdmin, SecretValue
from rakit.sqlalchemy import SQLAlchemyPlugin
from sqlalchemy.ext.asyncio import async_sessionmaker

admin = Admin(
    admin_id="operations",
    title="Operations",
    secret_key=SecretValue("replace-with-a-real-secret-at-least-32-bytes"),
)

session_factory = async_sessionmaker(engine, expire_on_commit=False)
admin.install(SQLAlchemyPlugin(session_factory=session_factory))


class UserAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id",)
    detail_fields = ("id",)


admin.register(UserAdmin)
app = admin.asgi()
```

## Official examples

Executable journeys live under `examples/`:

- `minimal` — smallest read-only custom data source;
- `fastapi_sqlalchemy` — FastAPI host composition + SQLAlchemy adapter;
- `builtin_auth` — built-in login/session protocol shape;
- `relationships` — portable relationship declarations;
- `internal_tools` — page, action, service registration, endpoint;
- `custom_datasource` — explicit third-party-style DataSource capabilities;
- `dashboard` — eager/lazy/failing widgets;
- `storage` — named private LocalStorage round trip.

Each official journey has an exact run/check command in its README.

## Documentation

The user documentation is built with MkDocs Material:

```bash
uv run mkdocs serve
uv run mkdocs build --strict
```

Start at [`docs/index.md`](docs/index.md). The repository roadmap remains in
[`docs/roadmap.md`](docs/roadmap.md). Task-by-task implementation plans under `docs/plans/` are
maintainer-local execution material and are not a public compatibility commitment.

## Package layout

```text
rakit
rakit-core
rakit-web
rakit-sqlalchemy
rakit-auth-sqlalchemy
rakit-storage
rakit-storage-local
rakit-server
rakit-server-uvicorn
rakit-server-granian
```

Official packages use synchronized versions and a one-way dependency direction.

## Compatibility

Rakit uses Semantic Versioning. During `0.x`, documented public APIs receive deprecation guidance
when practical; security/correctness fixes may require a faster change. See
[`docs/reference/compatibility.md`](docs/reference/compatibility.md).

Minimum Python version: **3.12**.

## Security

Use production-safe key/session/rate-limit stores, trusted host/proxy configuration, HTTPS, CSP,
CSRF, safe upload policy, and release security regression tests. Vulnerabilities should be reported
privately according to `SECURITY.md`, not through a public issue.
