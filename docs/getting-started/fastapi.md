# FastAPI Host Composition

FastAPI remains the host application. Rakit owns its Admin ASGI subtree and its Rakit lifecycle;
your application owns the engine and its FastAPI lifespan. Compose the two ASGI applications at one
explicit root so both lifespans are coordinated.

```python
from fastapi import FastAPI
from rakit import Admin, ModelAdmin, compose_asgi
from rakit.sqlalchemy import SQLAlchemyPlugin

admin = Admin(title="Operations", debug=True)
admin.install(SQLAlchemyPlugin(session_factory=session_factory))


class UserAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


admin.register(UserAdmin)
host = FastAPI()
app = compose_asgi(host, admin, path="/admin")
```

`compose_asgi` owns the combined lifespan: the host starts before Rakit, and Rakit shuts down before
the host. Direct `host.mount("/admin", admin.asgi())` is not lifecycle-safe for
the D4 contract because FastAPI does not execute mounted child lifespan events;
use the explicit composition root instead.

D4.2's real FastAPI proof exercises this composition boundary with the locked
FastAPI `0.139.2` / Starlette `1.3.1` resolution, lowest-direct FastAPI
`0.133.0` / Starlette `1.3.1`, and latest FastAPI `0.141.1` / Starlette `1.6.0`.
These are bounded tested resolutions, not a claim that every version allowed
by `fastapi>=0.116` is supported; D4.5 owns the compatibility-range policy.

See `examples/fastapi_sqlalchemy` for the executable version, including SQLAlchemy engine creation,
seed data, FastAPI lifespan ownership, and disposal.

Run that example with:

```bash
uv run uvicorn examples.fastapi_sqlalchemy.main:app --reload
```

Rakit's route generation is mount-aware: links, forms, redirects, and static assets preserve the
host application's mount prefix.
