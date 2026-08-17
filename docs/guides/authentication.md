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
backend, and durable SQLAlchemy sessions. The executable `examples/builtin_auth` uses a deliberately
small in-memory implementation only to make the protocol easy to inspect.

Production deployments should use persistent sessions, stable cryptographic keys, HTTPS, secure
cookie settings, and a production-safe shared login rate limiter.
