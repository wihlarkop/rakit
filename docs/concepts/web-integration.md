# Web Integration

Rakit separates application semantics from the web runtime and the host server:

```text
Rakit application semantics
  Admin, resources, forms, actions, pages, endpoints, APIs, permissions,
  persistence, transactions, storage, and lifecycle declarations
          |
          v
Rakit web runtime
  current reference implementation: Starlette-based Admin.asgi()
          |
          v
Host ASGI application
  FastAPI, Litestar, Starlette, Sanic, or another ASGI-native host
          |
          v
ASGI server
  Uvicorn, Granian, or another server
```

The host framework can change without rewriting Rakit registration or domain
code. This is protocol portability, not a promise that Rakit reimplements its
renderer in every host framework.

## Standalone Rakit

The standalone application remains the smallest path:

```python
from rakit import Admin

admin = Admin(title="Backoffice")
# admin.register(...)

app = admin.asgi()
```

`Admin.asgi()` returns Rakit's current Starlette-based ASGI runtime. It owns
Rakit compilation, request handling, security, application resolution, and
Rakit lifecycle behavior.

## Compose with an ASGI host

When Rakit is part of a larger ASGI service, use the explicit composition root:

```python
from fastapi import FastAPI
from rakit import Admin, compose_asgi

host = FastAPI()
admin = Admin(title="Backoffice")
# admin.register(...)

app = compose_asgi(host, admin, path="/admin")
```

The host portion can be replaced by another ASGI application without changing
the Rakit application definition:

```python
from litestar import Litestar
from rakit import Admin, compose_asgi

host = Litestar(...)
admin = Admin(title="Backoffice")
app = compose_asgi(host, admin, path="/admin")
```

`compose_asgi` is a new lifecycle-owning application. It is intentionally not
called `mount`: direct `host.mount("/admin", admin.asgi())` routing does not by
itself prove that the host drives the child lifespan correctly and is not the
canonical lifecycle-safe D4 integration path.

## Routing and path metadata

The composition root uses exact segment-boundary matching. With
`path="/admin"`:

- `/admin` and `/admin/` reach Rakit as `/`;
- `/admin/products` reaches Rakit as `/products`;
- `/administrator` remains host-owned; and
- `/api/users` remains host-owned.

The Rakit child receives a copied scope. Its `root_path` joins the incoming
root path and `/admin`, so a proxy root `/proxy` produces `/proxy/admin` for
Rakit while the host retains `/proxy`. Query-string bytes are unchanged. When
`raw_path` is present, the composition preserves its encoding while removing
the mounted prefix and rejects inconsistent path metadata explicitly.

HTTP and WebSocket scopes use the same boundary rule. A host WebSocket outside
the prefix is not interpreted or rewritten by Rakit.

## Lifespan and state ownership

The composition root owns the one root ASGI lifespan exchange and drives both
children directly. It does not depend on the host router to invoke a mounted
child lifespan.

Normal startup and shutdown are resource-nesting order:

```text
host startup -> Rakit startup -> ready
Rakit shutdown -> host shutdown
```

Startup is fail-closed. Host failure prevents Rakit startup. If Rakit startup
fails after the host starts, host cleanup is attempted and the root never sends
startup complete. Shutdown attempts host cleanup even when Rakit cleanup fails,
and relevant failures remain observable.

Each child receives its own copied lifespan and request state. Host lifespan
state is visible to host requests; Rakit lifespan state is visible to Rakit
requests; the two child states are not merged or leaked across the boundary.
If the server omits optional ASGI lifespan state, composition preserves that
absence rather than fabricating a shared empty state mapping.

During a root lifespan startup, HTTP and WebSocket dispatch waits until both
children have reached the startup outcome. Failed or stopped compositions
return a composition-level not-ready response/close; a direct call made without
any root lifespan exchange remains an unmanaged ASGI call and is dispatched
normally.

## Security, middleware, and exceptions

Host authentication is not Rakit authentication. Host sessions, user objects,
authorization dependencies, middleware, and exception handlers are not mapped
into Rakit automatically. Rakit continues to own its principal/session
semantics, authorization, CSRF, origin checks, security headers, mutation
authorization, idempotency, operation context, and route protection.

Host-local middleware remains host-local and Rakit-local middleware remains
Rakit-local. Middleware intentionally placed outside the final composition root
can affect both children. Host exceptions remain host-owned and Rakit
exceptions remain Rakit-owned; the composition root is not a universal
exception translator.

## Framework compatibility

The current Rakit provider remains `web.starlette`: it identifies the Rakit web
runtime and its proven web capabilities. A host framework is not a new Rakit
provider merely because it can invoke an ASGI callable. D4 compatibility is
proved through protocol behavior, the internal host-conformance harness, tests,
and documented compatibility evidence. Framework-specific runtime bridges are
deferred until they provide concrete value beyond ASGI composition.

Flask and generic WSGI integration are postponed research and are outside the
D4 closure gate. D4 may close without Flask; no WSGI bridge or Flask support is
implied by this ASGI contract.
