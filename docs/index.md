# Rakit

Rakit is a composable Python framework for admin panels, internal tools, dashboards, and APIs.
Its core is framework-neutral; the built-in web runtime is ASGI/Starlette-based and adapters add
persistence, authentication, storage, and server integrations explicitly.

## v0.1 alpha scope

The `0.1.0a1` line includes resources, query controls, SQLAlchemy CRUD, relationships, built-in
authentication and allow-only RBAC, forms, actions, pages, typed endpoints, dashboards, local
private storage, themes, accessibility contracts, lifecycle/health checks, and server adapters.

Start with [Installation](getting-started/installation.md), then build your
[First Admin](getting-started/first-admin.md). FastAPI users can mount the same Admin through the
[FastAPI integration](getting-started/fastapi.md).

!!! note "Alpha compatibility"
    Rakit is pre-1.0. Public surfaces are documented by stability category in the
    [Public API reference](reference/public-api.md) and compatibility rules live in the
    [Compatibility reference](reference/compatibility.md).
