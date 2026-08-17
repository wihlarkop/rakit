# Built-in authentication

This example shows Rakit's built-in login/session flow with a deliberately small in-memory backend.
It is for development and documentation only; `DemoSessionStore.production_safe` is intentionally
false and the credentials are intentionally obvious.

Run the configuration check:

```bash
uv run rakit check examples.builtin_auth.main:admin
```

Start it:

```bash
uv run rakit run examples.builtin_auth.main:admin
```

Open <http://127.0.0.1:8000/auth/login> and sign in with:

- identifier: `admin@example.com`
- password: `demo-password`

For a real application use a durable auth backend/session store such as the SQLAlchemy auth extra;
do not copy the in-memory store into production.
