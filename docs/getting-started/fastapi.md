# FastAPI Integration

FastAPI remains the host application. Rakit owns its Admin ASGI subtree; your application owns the
engine and its lifecycle.

```python
from fastapi import FastAPI
from rakit import Admin, ModelAdmin
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
app = FastAPI()
app.mount("/admin", admin.asgi(), name="rakit-admin")
```

See `examples/fastapi_sqlalchemy` for the executable version, including SQLAlchemy engine creation,
seed data, FastAPI lifespan ownership, and disposal.

Run that example with:

```bash
uv run uvicorn examples.fastapi_sqlalchemy.main:app --reload
```

Rakit's route generation is mount-aware: links, forms, redirects, and static assets preserve the
host application's mount prefix.
