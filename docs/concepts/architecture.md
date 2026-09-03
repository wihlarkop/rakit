# Architecture

Rakit is split into small distributions with one-way dependencies. `rakit-core` owns portable
contracts and policy; `rakit-web` adapts those contracts to ASGI/Starlette; persistence, auth,
storage, and server packages plug in explicitly. The `rakit` facade exposes the intended user-facing
imports and optional adapter facades.

Official distributions stay physically flat and capability-oriented rather than nesting concrete
implementations under `rakit-core`. The naming convention is:

- distribution: `rakit-<capability>` or `rakit-<capability>-<implementation>`;
- implementation import package: `rakit_<capability>` or `rakit_<capability>_<implementation>`;
- user facade: `rakit.<capability>` or `rakit.<capability>.<implementation>` when a category has a
  stable public facade.

For example, `rakit-server-granian` implements the neutral `rakit-server` contract and is exposed to
applications through `rakit.server.granian`. `rakit-storage-local` implements `rakit-storage` and is
exposed through `rakit.storage.local`. Existing compact facades such as `rakit.sqlalchemy` remain
valid until a second implementation creates a concrete need for a broader category namespace; Rakit
does not rename public imports speculatively.

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

Web portability is defined at the ASGI boundary. Rakit application semantics and domain registration
remain independent of the host framework; `rakit-web` supplies the current Starlette-based Rakit
runtime, and `compose_asgi(host, admin, path="/admin")` creates the lifecycle-owning composition root
for an ASGI host. See [Web Integration](web-integration.md) for routing, `root_path`, scope/state,
lifespan, and security ownership rules.
