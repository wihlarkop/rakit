# Custom Authentication

Custom authentication implements the portable `AuthBackend` and `SessionStore` protocols from
`rakit.core` and supplies both objects to `Admin`.

`AuthBackend.authenticate(identifier, password)` returns an authenticated `Principal` or `None`.
`resolve_principal(subject_id)` is called on authenticated requests so current active/permission
state is authoritative.

A SessionStore creates/resolves/rotates/revokes opaque server-side sessions and declares whether its
configuration is production-safe. Production stores should persist only a hash of the browser token,
enforce idle and absolute expiry, and ensure rotation changes the session id so previous CSRF tokens
cannot survive a privilege-boundary rotation.

Do not expose distinct login responses for unknown users versus wrong passwords. If your backend
normalizes login identifiers, apply the same normalization before rate-limit bucketing.

See `examples/builtin_auth` for protocol shape only; its in-memory session store is intentionally not
production-safe. `rakit.auth.sqlalchemy.SQLAlchemyAuthPlugin` is the official durable reference.
