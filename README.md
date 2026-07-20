# Rakit

> A composable Python framework for building admin panels, internal tools, dynamic dashboards, and APIs over any data source.

Rakit is an early-stage Python framework designed around explicit composition. Developers assemble resources, pages, actions, endpoints, dashboards, adapters, themes, authentication, storage, and application services without coupling the domain core to one web framework or ORM.

## Status

Rakit is currently under active design and early development. The initial design baseline has been approved, but public APIs may still change before the first stable release.

## Design principles

- Secure by default, with security treated as a first-class system concern.
- Framework-agnostic core with a standalone ASGI runtime.
- Explicit registration, plugin activation, dependency injection, and lifecycle.
- One operation pipeline shared by HTML admin, custom endpoints, and future generated APIs.
- Backend-neutral contracts with typed, capability-aware adapter escape hatches.
- Progressive enhancement: server-rendered HTML works without JavaScript; HTMX improves the experience.
- Batteries included, but every battery is replaceable.
- Fully typed public packages with stable, documented import paths.

## Planned v0.1 highlights

- Standalone or mountable Starlette-based ASGI application.
- SQLAlchemy CRUD with relationships, filters, search, sorting, and pagination.
- Custom resources, pages, actions, endpoints, dashboards, and widgets.
- Built-in optional SQLAlchemy authentication and allow-only RBAC.
- Pydantic v2 validation and a Jinja-based form engine.
- HTMX progressive enhancement and bundled Tailwind CSS.
- Local private file storage through a portable storage contract.
- Explicit DI scopes, transactions, events, deadlines, and cooperative cancellation.
- Optimistic concurrency, idempotency, signed destructive confirmations, and CSRF.
- Structured logging, health/readiness endpoints, and graceful shutdown.
- Unit, contract, integration, and example smoke tests.

## Example direction

```python
from rakit import Admin, ModelAdmin
from rakit.sqlalchemy import SQLAlchemyPlugin

admin = Admin(
    admin_id="operations",
    title="Operations",
)

admin.install(
    SQLAlchemyPlugin(
        engine=engine,
        owned=False,
    )
)


class UserAdmin(ModelAdmin):
    model = User


admin.register(UserAdmin)

app = admin.asgi()
```

The exact API remains provisional until implementation begins.

## Repository documentation

- [Framework design](docs/design/2026-07-19-rakit-framework-design.md)
- [Roadmap](docs/roadmap.md)

The framework design and roadmap are public documentation and are committed to
the repository. Task-by-task implementation plans under `docs/plans/` are
local, maintainer-only working documents used to drive development — they are
not committed, are not published documentation, and are not a public API or
compatibility commitment. The design specification and the shipped public API
are the source of truth; a plan describes how a change was built, not a
guarantee of what it produces.

## Intended package layout

```text
rakit
rakit-core
rakit-web
rakit-sqlalchemy
rakit-auth-sqlalchemy
rakit-storage
rakit-storage-local
rakit-server-uvicorn
```

Official packages are planned to use synchronized versions and a strict one-way dependency graph.

## Compatibility direction

Rakit uses Semantic Versioning. During `0.x`, public APIs should still receive deprecation warnings and migration guidance whenever practical. After `1.0`, breaking public API changes are reserved for major releases.

Minimum Python version: **3.12**.

## Security

Rakit is intended to be secure by default. Production deployments will require persistent cryptographic keys, secure cookies, trusted host/proxy configuration, CSRF protection, restrictive response caching, and successful startup validation.

Security vulnerabilities should eventually be reported privately through the process documented in `SECURITY.md`, rather than through public issues.
