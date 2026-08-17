# Architecture

Rakit is split into small distributions with one-way dependencies. `rakit-core` owns portable
contracts and policy; `rakit-web` adapts those contracts to ASGI/Starlette; persistence, auth,
storage, and server packages plug in explicitly. The `rakit` facade exposes the intended user-facing
imports and optional adapter facades.

The composition root is `Admin`. Registration builds an immutable compiler graph containing
resources, pages, actions, endpoints, routes, permissions, capability requirements, and plugin
metadata. Compilation rejects ambiguous adapters, route collisions, unsupported capabilities, and
unsafe operation combinations before the app starts serving requests.

Adapters advertise capabilities rather than making Rakit infer guarantees from method names. That
principle applies to data sources, operation executors, transaction/unit-of-work integration, and
storage. Unknown capabilities fail closed.

The web layer is progressively enhanced: built-in HTML remains usable without JavaScript and local
HTMX/UI assets add partial updates where supported. Core contracts never depend on HTMX, Jinja,
Starlette, or SQLAlchemy.
