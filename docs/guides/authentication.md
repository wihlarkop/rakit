# Authentication

Authentication is optional and backend-neutral. An authenticated Admin receives an `AuthBackend`
and `SessionStore` together; supplying only one is a configuration error.

The built-in flow:

1. renders `/auth/login` and issues a pre-session CSRF token;
2. verifies the login CSRF token and credentials;
3. creates an opaque server-side session;
4. stores only the raw session token in the secure cookie boundary;
5. re-resolves the current `Principal` on every authenticated request.

Re-resolving the principal means role, permission, active-state, and superuser changes can take
effect without freezing authorization at login time.

`rakit-auth-sqlalchemy` supplies `SQLAlchemyAuthPlugin`, an Argon2 password hasher, a SQLAlchemy auth
backend, durable SQLAlchemy sessions, and allow-only RBAC persistence. Applications should import
its operational surface through the public facade:

```python
from rakit.auth.sqlalchemy import (
    Argon2PasswordHasher,
    AuthBase,
    Permission,
    Role,
    SQLAlchemyAuthPlugin,
    User,
    sync_permissions,
)
```

`AuthBase`, `User`, `Role`, and `Permission` are exposed so application bootstrap/operator tooling
can work with the built-in schema without importing implementation-package internals. The
`examples/reference_app` development bootstrap demonstrates this surface together with
`sync_permissions` and `Argon2PasswordHasher`.

For a disposable local demonstration it is acceptable to create `AuthBase.metadata` directly, but
production deployments should apply the package's Alembic migrations instead. Production systems
should also use persistent sessions, stable cryptographic keys, HTTPS, secure cookie settings, and
a production-safe shared login rate limiter.

The executable `examples/builtin_auth` deliberately uses a small in-memory implementation only to
make the backend-neutral authentication protocol easy to inspect.
