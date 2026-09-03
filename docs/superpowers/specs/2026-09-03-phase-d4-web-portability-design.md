# Phase D4.0 — Web Portability / ASGI Integration Contract

## 1. Context

Rakit has a framework-neutral application and semantic layer, while its current
web implementation is Starlette-based. That distinction is architectural, not
accidental: application registration, resources, forms, actions, pages,
authorization, persistence, transactions, storage, and lifecycle declarations
belong to Rakit; HTTP framework mechanics belong at the web boundary.

The current standalone `Admin.asgi()` application is the reference Rakit web
runtime. It owns meaningful Rakit startup and shutdown work, including logging
configuration, application-resolver lifetime, and the Rakit lifecycle manager.
Consequently, direct framework mounting is not by itself a complete integration
contract. A host can route a child application correctly while still failing to
drive the child's lifespan correctly.

D4.0 establishes the common ASGI composition contract. It deliberately does not
implement native FastAPI, Litestar, Sanic, or Flask adapters. D4.1 and later
phases will provide independent framework proofs against this contract.

The authoritative external protocol references are the
[ASGI Lifespan specification](https://asgi.readthedocs.io/en/latest/specs/lifespan.html),
the [ASGI main specification](https://asgi.readthedocs.io/en/latest/specs/main.html),
and the [ASGI HTTP and WebSocket specification](https://asgi.readthedocs.io/en/latest/specs/www.html).

## 2. Goals

D4.0 will:

1. Define portability as preservation of Rakit application semantics while the
   host ASGI framework changes.
2. Provide a generic, lifecycle-aware ASGI composition root in `rakit-web`.
3. Expose a small public facade for composing a host ASGI application with an
   `Admin` instance.
4. Preserve exact-segment routing, nested `root_path`, query strings, and
   correctly represented `raw_path` values.
5. Isolate host and Rakit scopes and lifespan state.
6. Coordinate host and Rakit startup and shutdown exactly once, with explicit
   fail-closed behavior and deterministic cleanup.
7. Preserve host HTTP and WebSocket behavior outside the configured Rakit
   prefix.
8. Keep host security, middleware, and exception ownership separate from Rakit
   ownership.
9. Provide an internal reusable host-conformance seam for D4.1+.
10. Correct C2 and documentation guidance so the lifecycle-safe path is the
    default.

## 3. Non-goals

D4.0 does not:

- implement `rakit-fastapi`, `rakit-litestar`, or `rakit-sanic` production
  packages;
- add FastAPI, Litestar, Sanic, or Flask dependencies to production Rakit
  packages;
- implement Flask or a WSGI bridge;
- bridge host authentication, dependency injection, sessions, context objects,
  exception handlers, or authorization into Rakit;
- merge OpenAPI schemas or rewrite native host routes;
- redesign generated APIs, persistence, the server package, or the renderer;
- create universal request, response, router, middleware, or web-framework
  abstractions;
- provide a third-party adapter-authoring SDK (that is D5); or
- publish a release, bump a version, create a tag, or change release policy.

Flask/WSGI is explicitly postponed research and is outside the D4 closure gate.

## 4. Terminology

- **Rakit application semantics**: Rakit-owned declarations and behavior,
  including `Admin`, `ModelAdmin`, `ResourceAdmin`, resources, forms, actions,
  pages, endpoints, generated APIs, permissions, authorization, persistence,
  transactions, relationships, storage, dashboard definitions, lifecycle
  declarations, `CompiledApplication`, and application-owned domain code.
- **Rakit web runtime**: the current Starlette-based implementation returned by
  `Admin.asgi()`. It translates Rakit semantics into an ASGI application.
- **Host ASGI application**: the application supplied by FastAPI, Litestar,
  Starlette, Sanic, or another ASGI-native host. The host remains responsible
  for its own routes and framework behavior.
- **Composition root**: the D4.0 ASGI application returned by
  `compose_asgi(host, admin, path=...)`. It owns the root lifespan and dispatches
  each ordinary scope to exactly one child.
- **ASGI server**: the process-level server that invokes the composition root
  and exchanges ASGI messages with it.
- **Rakit prefix**: the configured path segment, such as `/admin`, that selects
  the Rakit child.
- **Child lifespan**: the ASGI lifespan protocol exchange with either the host
  or the Rakit web runtime.

## 5. Historical Rakit framework-agnostic intent

The architecture documentation describes `rakit-core` as the owner of portable
contracts and policy, with `rakit-web` adapting those semantics to the current
ASGI/Starlette runtime. The initial Starlette implementation was chosen as a
concrete web runtime, not as a requirement that application code be written for
Starlette.

The original composition direction is explicit: an application owns an
`Admin`, compiles its graph, and exposes a standalone ASGI application. A host
framework may surround or compose that application at the integration boundary.
FastAPI/Starlette mounting examples were an early integration convenience, but
they did not establish a portable lifecycle contract.

The D4 interpretation is therefore:

> Rakit semantics portability != Rakit renderer reimplementation in every host
> framework.

The renderer remains one current/reference web runtime. Host portability is
proved at the ASGI boundary.

## 6. Runtime vs host-framework distinction

The dependency and ownership graph is:

```text
Rakit application semantics
              |
              v
       Rakit web runtime
       (current reference: Starlette)
              |
              v
       ASGI composition root
          /          \
         /            \
 host ASGI app       Rakit ASGI app
         \            /
          \          /
             ASGI server
```

The composition root does not translate FastAPI, Litestar, or Sanic concepts
into Rakit concepts. It only composes two ASGI applications and coordinates the
protocol they already share.

## 7. Protocol-first ASGI portability decision

ASGI is the D4.0 portability boundary for ASGI-native hosts. The generic
composition implementation will live in `rakit-web`, will depend only on
neutral ASGI typing already available through Rakit's server contracts plus the
existing supported async runtime dependency, and will not import a host
framework.

The first-class supported behavior is therefore a behavioral contract rather
than a collection of adapter classes. A framework may be first-class supported
with little or even zero framework-specific runtime code when its ASGI behavior
maps cleanly and the conformance proof passes.

This means:

> integration equality != adapter-code equality.

The same Rakit semantics and protocol behavior must hold across hosts; the
amount of framework-specific adapter code need not be equal.

## 8. Public DX

The selected public facade is:

```python
from fastapi import FastAPI
from rakit import Admin, compose_asgi

host = FastAPI()
admin = Admin(title="Backoffice")
# admin.register(...)
# admin.register_page(...)

app = compose_asgi(host, admin, path="/admin")
```

The host portion can conceptually become:

```python
from litestar import Litestar
from rakit import Admin, compose_asgi

host = Litestar(...)
admin = Admin(title="Backoffice")
app = compose_asgi(host, admin, path="/admin")
```

The Rakit registration and application definition do not branch on the host
framework. `compose_asgi` is intentionally explicit: it creates a new
lifecycle-owning composition root. It is not named `mount`, because a name that
implies an in-place host operation would obscure the ownership and lifecycle
semantics.

Standalone use remains supported and unchanged in concept:

```python
from rakit import Admin

admin = Admin(title="Backoffice")
app = admin.asgi()
```

## 9. ASGI routing contract

For `http` and `websocket` scopes, the composition root applies exact
segment-boundary matching against the configured absolute prefix.

For `/admin`:

| Incoming `path` | Child | Child `path` |
| --- | --- | --- |
| `/api/users` | host | `/api/users` |
| `/admin` | Rakit | `/` |
| `/admin/` | Rakit | `/` |
| `/admin/products` | Rakit | `/products` |
| `/administrator` | host | `/administrator` |

The host receives an isolated copy with host semantics unchanged. The Rakit
child receives a separate copy with the prefix removed as mount semantics. The
query string is never changed. The original scope object is never mutated.

The Rakit route owns only the configured prefix. Requests outside it, including
host WebSocket paths, remain host-owned. Unsupported or non-routed scope types
are forwarded to the host copy; `lifespan` is the one protocol explicitly owned
by the composition root.

## 10. `root_path` contract

The Rakit child's `root_path` is the incoming `root_path` joined with the
configured prefix. Existing nested deployment information is preserved:

```text
incoming root_path = /proxy
configured prefix  = /admin
child root_path    = /proxy/admin
```

The host copy retains `/proxy`. The join is segment-aware and does not create
duplicate separators. A root prefix of `/` leaves the incoming root path
unchanged.

## 11. Request-scope isolation

The composition root creates an independent shallow scope copy for every child
dispatch. It also copies mutable scope members that the composition can safely
identify, including `state` and `path_params`, before applying Rakit-only
changes. No child is given a scope object that another child can mutate.

The scope transformation is limited to ASGI mount fields. Headers, method,
query string, client/server information, extensions, and other host semantics
remain unchanged. The composition does not add host state to Rakit state or
Rakit state to host state.

## 12. Lifespan ownership

The composition root owns one root `lifespan` exchange. It directly drives a
lifespan exchange with the host child and the Rakit child. It does not rely on a
host router invoking a mounted child's lifespan, because that behavior is not a
portable guarantee.

`Admin.asgi()` continues to own the Rakit runtime's standalone lifespan. In a
composed application, the composition root drives that child exactly once. It
does not wrap the child in a second Rakit lifecycle and does not ask the host to
mount the child as an independently managed lifecycle root.

## 13. Lifespan startup/shutdown ordering

Normal startup is deterministic and resource-nesting friendly:

```text
host startup
Rakit startup
startup.complete to the server
```

Normal shutdown is reverse order:

```text
Rakit shutdown
host shutdown
shutdown.complete to the server
```

Each child is started and stopped at most once per root lifespan exchange. No
request is considered ready by the composition root until both required child
startups have completed successfully.

## 14. Lifespan failure semantics

Startup is fail-closed:

- If host startup fails or is explicitly reported as failed, Rakit startup does
  not run and the composition sends `lifespan.startup.failed` (or propagates an
  unsupported-lifespan signal according to the protocol state machine).
- If host startup succeeds and Rakit startup fails, the composition attempts
  host shutdown rollback, preserves the Rakit failure, and does not send
  `lifespan.startup.complete`.
- An explicit `lifespan.startup.failed` message is a startup failure, not an
  unsupported-lifespan signal.

Shutdown is cleanup-first:

- Rakit shutdown is attempted before host shutdown.
- Host shutdown is attempted even if Rakit shutdown fails.
- A shutdown failure is reported, never silently discarded.
- If both children fail during shutdown, all materially relevant failures are
  preserved with Python 3.12+'s `ExceptionGroup` mechanism.
- Cancellation is not converted into success or hidden by ordinary cleanup
  handling; child tasks are always awaited and no lifecycle task is leaked.

## 15. Lifespan state propagation

The composition preserves incoming outer lifespan/request state as the base for
each child, then maintains separate host and Rakit lifespan-state namespaces.
Requests routed to the host receive the host lifespan state; requests routed to
Rakit receive the Rakit lifespan state. A shallow copy is used at each ASGI
boundary, matching the ASGI lifespan convention and preventing a child from
mutating an unrelated child's state.

The composition does not merge two independent child states into one global
dictionary. Applications remain responsible for choosing namespaced keys, and
the host and Rakit children do not see each other's private state.

## 16. HTTP and WebSocket dispatch

The same exact-prefix rule applies to HTTP and WebSocket scopes. An HTTP scope
inside the Rakit prefix is transformed and sent to the Rakit child. A WebSocket
scope outside the prefix is sent to the host unchanged in semantics. WebSocket
handshake, disconnect, and close messages are not interpreted by the
composition; they remain owned by the selected child.

`raw_path` is optional ASGI data and must remain consistent with the transformed
`path` when present. The implementation preserves raw percent-encoding while
removing the raw representation of the Rakit prefix. If a present `raw_path`
cannot be safely reconciled with the decoded `path`, composition fails
explicitly instead of fabricating an inconsistent child scope. Query bytes are
not part of `raw_path` and remain exclusively in `query_string`.

The current Rakit web runtime has a private Starlette compatibility translation
inside its own boundary: after composition has delivered the required
mount-relative child scope, it can reconstruct a Starlette-internal path for
deeper Rakit-owned mounts such as static assets. This preserves the public ASGI
contract without moving Starlette mechanics into `rakit-core` or changing the
host scope.

## 17. Security ownership

Composition does not merge host security into Rakit:

```text
Host authentication != Rakit authentication
```

Rakit continues to own its principal/session semantics, authorization, CSRF,
origin checks, CSP and security headers, mutation authorization, idempotency,
operation context, and route protection. Host authentication objects, sessions,
middleware, authorization dependencies, and exception handlers are not mapped
automatically. Identity bridges, if ever needed, are explicit opt-in
framework-specific work outside D4.0.

## 18. Middleware ownership

Host-local middleware belongs to the host child and does not automatically wrap
the Rakit child. Rakit-local middleware remains inside the Rakit web runtime.
Middleware intentionally placed outside the final composition root is an outer
boundary and may affect both children; that behavior is explicit and follows
ordinary ASGI composition.

## 19. Exception ownership

Host exceptions remain host-owned and Rakit exceptions remain Rakit-owned. The
composition layer does not become a universal exception translator. It only
handles errors needed to enforce routing/lifespan protocol correctness and
reports lifecycle failures through the ASGI lifecycle messages and Python
exception propagation rules.

## 20. Host/Rakit state isolation

Host state, host framework context, host middleware-local objects, Rakit request
context, Rakit principal/session state, and Rakit resolver/lifecycle state are
separate ownership domains. The composition root copies the incoming state for
each child and overlays only that child's lifecycle state for that child. No
implicit host-to-Rakit identity or request-context bridge exists.

## 21. Capability/discovery implications

No new capability identifier or provider identifier is required in D4.0.
`web.starlette` remains the current Rakit web runtime/provider and continues to
advertise the already-proven Rakit web capabilities. A host framework is not a
Rakit runtime provider merely because it can call an ASGI application.

D4.0 compatibility is represented by the internal conformance model, tests,
documentation, and the compatibility matrix. New capability identifiers will
be added only if a later phase demonstrates a real runtime negotiation need and
the corresponding behavior is proven.

## 22. Framework-switch conformance model

D4.0 adds a reusable internal host-conformance model and runner in `rakit-web`.
It accepts a host composer and an application factory, then exercises protocol
behavior without importing or branching on any host framework. D4.1 and later
phases can supply framework-specific test cases while keeping:

```python
build_admin()
```

free of framework-specific branches.

The harness is internal and intentionally not a stable third-party SDK. It
checks the shared contract: host fallback, Rakit-prefix dispatch, lifecycle
ordering/once-only behavior, and state isolation. Framework-specific phases add
their own installation and host-native proof only when the generic contract
needs it.

## 23. Dependency policy

D4.0 production code must not depend on FastAPI, Litestar, Sanic, or Flask.
`rakit-core` remains free of all web framework dependencies, including
Starlette. The generic implementation belongs to `rakit-web`.

`rakit-web` already uses AnyIO-facing async primitives in its web runtime
surface, while AnyIO is a direct dependency of `rakit-core` and the development
environment. Because D4.0 needs portable task/cancellation orchestration at the
web boundary and must not hardcode `asyncio` there, `rakit-web` will declare an
explicit bounded `anyio` dependency rather than relying on a transitive import.
The supported range is tested at its lowest and latest allowed versions.

No other new runtime dependency is justified.

## 24. Deferred framework-specific native bridges

Native host bridges are deferred until the generic contract is proved. A later
phase may add framework-specific code only where it provides behavior that the
ASGI contract cannot provide, such as an explicit host integration lifecycle
hook, opt-in identity bridge, or framework-native developer experience. Such a
bridge must preserve the same semantic and security boundaries and must pass the
reusable conformance model.

## 25. Postponed Flask/WSGI work

Flask and generic WSGI integration are postponed research. D4.0 does not add a
WSGI bridge, `WsgiToAsgi`, Flask dependency, Flask guidance that implies
support, or WSGI parity claims. The D4 sequence may close after ASGI-native
integration is complete and stable without Flask. WSGI work can be revisited
only in a separately approved phase.

## 26. Alternatives considered/rejected

### Direct host `.mount()` as the canonical path

Rejected for D4.0 because route delegation does not prove that a host starts and
stops the mounted Rakit child, and lifecycle ownership differs across hosts.
Direct mounting remains possible as a host-specific experiment only when that
host explicitly proves the required child-lifespan semantics; it is not the
portable golden path.

### One production adapter per host framework

Rejected as the default because it duplicates renderer and application semantics,
creates dependency and lifecycle drift, and is unnecessary when ASGI maps the
required behavior. Later native bridges remain possible when they add concrete
value.

### Moving ASGI/web mechanics into `rakit-core`

Rejected because it would make the semantic core depend on a web protocol/runtime
boundary and violate the existing package ownership model. Neutral ASGI typing
already available through the server contracts is reused; composition mechanics
stay in `rakit-web`.

### Universal request/response/router abstractions

Rejected as speculative. D4.0 needs scope transformation, child dispatch, and
lifespan orchestration; it does not need to reimplement every web framework
behind Rakit interfaces.

### Merging host and Rakit security or context

Rejected because it would silently couple independently owned authentication,
authorization, sessions, middleware, and exception semantics. Any bridge must be
explicit and opt-in.

## 27. D4 rollout sequence

The approved sequence is:

1. **D4.0 — Web Portability / ASGI Integration Contract**: generic composition,
   lifecycle/state/routing contract, internal conformance harness, and guidance.
2. **D4.1 — Litestar proof**: first independent ASGI-native host proof.
3. **D4.2 — FastAPI proof**: second independent ASGI-native host proof.
4. **D4.3 — Starlette reference integration hardening**: harden the current
   runtime and host integration based on the contract.
5. **D4.4 — Sanic**: only if its behavior maps cleanly and the conformance proof
   is honest.
6. **D4.5 — ASGI Integration DX & Compatibility Matrix**: close ecosystem
   compatibility documentation and developer experience.

Flask/WSGI is outside this sequence and outside the D4 closure gate.

## 28. Acceptance matrix

| Area | D4.0 acceptance evidence |
| --- | --- |
| Semantic portability | `Admin` and application registration remain host-framework independent |
| Package neutrality | No FastAPI/Litestar/Sanic/Flask production import or dependency; no Starlette in `rakit-core` |
| Public composition | `rakit.compose_asgi(host, admin, path=...)` is importable and documented |
| Routing | Host fallback, exact boundary, prefix root, nested routes, query preservation, HTTP/WebSocket dispatch |
| Path metadata | Nested `root_path`, safe `raw_path`, and explicit failure for inconsistent metadata |
| Scope safety | Original, host, and Rakit scopes are isolated; state does not cross children |
| Lifespan | Host then Rakit startup; Rakit then host shutdown; each exactly once |
| Startup failure | Host failure prevents Rakit startup; Rakit failure rolls host back; no ready signal |
| Shutdown failure | Remaining cleanup is attempted and all relevant failures are preserved |
| Lifespan support | Unsupported children are distinguished from explicit/real startup failures |
| Security | Host security is not automatically mapped; Rakit security remains in Rakit |
| Middleware/exceptions | Ownership remains child-local except intentional outer middleware |
| Existing behavior | Standalone `Admin.asgi()` remains compatible |
| C2 guidance | Generated existing-project guidance uses lifecycle-safe composition |
| Capability discipline | Existing `web.starlette` identity remains; no speculative IDs |
| Documentation | Architecture, standalone/composed usage, and Flask postponement are clear |
| Verification | Focused, package, full, multi-Python, dependency, docs, artifact, and CI gates are recorded |
