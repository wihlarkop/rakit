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
the host. Direct `host.mount("/admin", admin.asgi())` is not the canonical lifecycle-safe D4 path
unless a host integration separately proves its child-lifespan behavior.

See `examples/fastapi_sqlalchemy` for the executable version, including SQLAlchemy engine creation,
seed data, FastAPI lifespan ownership, and disposal.

Run that example with:

```bash
uv run uvicorn examples.fastapi_sqlalchemy.main:app --reload
```

Rakit's route generation is mount-aware: links, forms, redirects, and static assets preserve the
host application's mount prefix.
