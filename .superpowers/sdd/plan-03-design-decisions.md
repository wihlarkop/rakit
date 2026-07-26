# Plan 03 Design Decisions

Authentication, Authorization, and Security. Cross-references `docs/plans/2026-07-19-03-authentication-authorization-security.md` and `docs/design/2026-07-19-rakit-framework-design.md` sections 21-25.

## 1. `TokenService` token shape and key derivation (Task 1)

A compact, Rakit-internal `header.payload.signature` shape (base64url of
JSON header/claims, HMAC-SHA256 signature) -- not a general-purpose JWT
implementation, since the framework design explicitly says Rakit does not
implement custom cryptography but also does not need JWT's broader
interoperability surface for internal purpose-separated tokens.

Key derivation: HKDF-SHA256 with `info = "rakit:{admin_id}:{purpose}:v{version}"`,
binding `admin_id` and `purpose` *into the derived key itself*, not just
checked after verification. This means a token signed for one admin or
purpose cannot even be verified against a different admin's/purpose's
derived key -- rather than relying solely on a claims comparison after MAC
verification succeeds.

`SigningKey.__repr__` deliberately omits the secret; the raw secret is only
ever accessed via `SecretValue.get_secret_value()` inside `_derive_key`.

## 2. `SessionRecord` carries no CSRF token (Task 2, refined before Task 6)

Originally speced with a `csrf_token: str` field. Removed before any
consumer depended on it: a CSRF token is not session state, it is a
`TokenService`-derived value (purpose `"csrf"`) bound to `session_id`,
freshly issued/verified without any database read. Storing it in
`SessionRecord`/the sessions table would have required rotating it in
lockstep with session rotation for no benefit -- `CsrfService` (Task 6)
derives it independently, keyed only on `session_id`.

## 3. `UserProvider` is not a separate core Protocol

The framework design (section 21) lists `IdentityProvider`/`UserProvider`
alongside `AuthBackend`/`SessionStore`/`Principal` as core auth contracts.
Task 2's own test/interface examples only exercise `Principal` and
`PermissionRequirement`, and `AuthBackend.authenticate()` already covers
the full surface `rakit-web` needs (identifier+password -> `Principal`).
A separate `UserProvider` protocol would only be meaningful once a second
`AuthBackend` implementation needs to share user-lookup logic independent
of password verification -- that doesn't exist yet. `rakit-auth-sqlalchemy`
realizes "user provider" as its own concrete `User` model and queries
rather than a core-level Protocol. Revisit if/when a second backend
implementation is added.

## 4. Empty `PermissionRequirement.permissions` is rejected at construction

Caught by automated security review immediately after the Task 2 commit:
`all(())` and `any(())` both evaluate to Python-truthy, so
`PermissionRequirement(mode="all", permissions=())` would vacuously match
*every* principal, including an unauthenticated one, once `matches()` ran
its `all()`/`any()` over an empty list. Fixed via a Pydantic field
validator rejecting an empty `permissions` tuple at construction time --
the failure surfaces wherever the requirement is defined, not deep inside
an authorization check.

## 5. `User`/`Permission` need explicit `__init__` overrides for secure defaults (Task 3)

`mapped_column(default=True)` (etc.) only applies at **INSERT** time in
SQLAlchemy's declarative mapping -- a freshly constructed `User(email=...,
password_hash=...)` object has `user.is_active is None` until flushed,
not `True`. The plan's own required test
(`test_user_defaults_are_secure`) asserts the secure default is visible
immediately after construction, with no database round trip. Fixed by
giving `User`/`Permission` explicit `__init__` overrides that
`kwargs.setdefault(...)` the secure values before calling
`super().__init__(...)` -- the column-level `default=` is kept too, as
defense in depth for any row inserted outside the ORM constructor (e.g.
raw SQL, a future bulk-insert path).

## 6. Auth migrations use a dedicated `DeclarativeBase`, plain-sync Alembic env (Task 3)

`rakit_auth_sqlalchemy.models.Base` is a separate `DeclarativeBase` from
any application-owned metadata, so this package's Alembic migrations only
ever touch its own tables (`rakit_auth_*`), regardless of what ORM models
the host application defines.

`alembic/env.py` uses a plain synchronous engine (`engine_from_config`),
not an async one. This is deliberate and bounded: migrations are a
one-off maintenance operation, not part of the request path, so running
them with a sync driver (e.g. `postgresql+psycopg://` in production,
`sqlite:///` for the smoke test) is standard Alembic practice even for an
otherwise-async application. `RAKIT_AUTH_SQLALCHEMY_URL` overrides
`alembic.ini`'s own `sqlalchemy.url` so no real credential needs to live
in a checked-in file; the smoke-test default (`sqlite:///:memory:`)
leaves nothing on disk.

## 7. Password hashing concurrency bound (Task 4)

`Argon2PasswordHasher` runs `hash()`/`verify()` through
`anyio.to_thread.run_sync`, bounded by a shared `anyio.CapacityLimiter`
(default 4). Argon2 is intentionally slow (that's the point), so running
it inline would stall the event loop; an *unbounded* number of concurrent
`to_thread.run_sync` calls would instead exhaust worker threads under a
login-flood -- the limiter bounds concurrent hashing without adding a
separate queue/backpressure abstraction.

## 8. `SQLAlchemySessionStore` timestamp normalization (Task 4)

SQLite's `DateTime(timezone=True)` round-trips as timezone-*naive* (SQLite
has no native timezone-aware column type) even though the column is
declared timezone-aware. Comparing a timezone-aware `datetime.now(UTC)`
against a naive value read back from the database raises `TypeError`.
Fixed via `_as_aware()`, which treats a naive value read from the database
as UTC. PostgreSQL's `TIMESTAMP WITH TIME ZONE` does not have this
problem; the normalization is a no-op there (values already carry
tzinfo).

## 9. Permission catalogue generation is bounded to what's actually compiled (Task 5)

`generate_permission_catalogue()` always emits `{admin_id}.access` and,
for every compiled `ResourceDefinition`, all four CRUD permission keys
(`read|create|update|delete`) -- **unconditionally**, even though Plan
02/03 only ever implement `read`. This is deliberate: it keeps permission
keys stable across the later plans that add write operations, rather than
growing the catalogue (and forcing every deployment to re-run
`permissions sync`) the moment create/update/delete ship.

Pages/actions/endpoints parameters exist on the function today but are
always called with empty tuples, since `CompiledApplication` does not yet
populate `.pages`/`.actions`/`.endpoints` (`PageDefinition`,
`EndpointDefinition`, `ActionDefinition` already exist in
`rakit_core.definitions` as forward-declared contracts, unused by the
compiler until later plans wire them in). The function is already shaped
to generate their keys once that happens.

Field- and relationship-level permission keys are **not** generated:
`ResourceFieldPolicy` has no per-field permission configuration to derive
them from yet. Out of scope until a later plan introduces one.

## 10. `sync_permissions()` never deletes; "updated" counts every touched row (Task 5)

Per the framework design ("synchronization adds and updates definitions
but does not silently delete old permissions"), a permission whose
generating definition disappears is marked `orphaned = True`, never
deleted -- a `Role` may still reference it, and deleting the row would
silently revoke that grant with no record of what was removed or when.

`PermissionSyncResult.updated` counts every existing key present in the
new catalogue, including ones whose label/group didn't actually change
(the sync always writes `label`/`group`/`orphaned = False` for a matched
key). This is a deliberate simplification: computing a true "did anything
change" diff would need to compare against prior values, which the
function doesn't otherwise need to load.

## 11. `BuiltinAuthorizationPolicy` does no database access (Task 5)

Permission resolution happens once, when `Principal.permissions` is
populated during authentication -- `authorize()` only evaluates the
already-resolved `frozenset[str]` against a `PermissionRequirement`. This
keeps every authorization check O(1) with no query, at the cost of a
stale `Principal` not reflecting a mid-session permission change until
the session is re-authenticated (matching "sessions support rotation" as
the mechanism for picking up privilege changes, per section 22).

## 12. Login/logout wiring: CSRF cookie is a double-submit cookie, not yet embedded in forms (Task 6)

Login sets two cookies: `rakit_session` (`HttpOnly`, `Secure` unless
`debug=True`, `SameSite=Lax`) and `rakit_csrf` (deliberately **not**
`HttpOnly`, since the double-submit pattern requires client-side code to
read it and echo it back on a mutation). Full form-embedded CSRF hidden
fields across every POST form are Plan 04's concern (the write pipeline)
-- Plan 03 only needs to *issue* and *verify* the token; there are no
forms yet beyond login/logout that mutate state.

Unknown identifier and wrong password return byte-identical 401 responses
("Invalid credentials.") -- deliberately non-enumerating, per the
framework design and the plan's own required test.

`LoginRateLimiter` is explicitly documented as development-only
(in-memory, single-process); a production deployment needs a shared store
(Redis or equivalent) for the limit to hold across worker processes. This
mirrors the framework design's own callout for "development-only shared
stores" as a production-validation concern -- validated in Task 7's
`validate_production_config`, though the limiter store itself isn't yet
swappable (no `RateLimitStore` protocol exists to inject an alternative;
that's a bounded gap, not a silent one).

## 13. `Admin` gains `auth_backend`/`session_store` params; wiring is opt-in per instance (Task 6)

`build_auth_routes()` is only added to the compiled ASGI app when *both*
`auth_backend` and `session_store` are supplied to `Admin.__init__`. An
`Admin` constructed without them behaves exactly as it did before this
plan -- no `/auth/login`/`/auth/logout` routes exist, no cookies are ever
set. The `CsrfService`'s `TokenService` is derived from the admin's own
`secret_key` via `TokenService.single_key(key_id="primary", ...)`; if auth
is configured but no `secret_key` is set (only possible when `debug=True`,
since `RakitConfig` itself requires one otherwise), `Admin.asgi()` raises
a clear `RakitError` rather than constructing a `TokenService` from
nothing.

## 14. `SecurityMiddleware` is unconditional; test fixtures had to migrate off `testserver` (Task 7)

Unlike auth wiring, `SecurityMiddleware` (trusted-host validation, mutation
Origin/Referer validation, body-size limit, response security headers) is
applied to **every** `Admin.asgi()` output, whether or not authentication
is configured -- the framework design states security middleware is a core
`rakit-web` feature, not opt-in. `SecurityConfig.allowed_hosts` already
defaulted to `("localhost", "127.0.0.1", "[::1]")` since Plan 00/01, but
nothing enforced it until this plan.

This meant every existing rakit-web test (and the two example smoke
tests) that used httpx's conventional `base_url="http://testserver"` would
now receive a 400 (untrusted host) on every request. Rather than adding
`"testserver"` to the framework's default allowed-hosts list (which would
bake a test-only value into a security default -- unacceptable), every
affected test's `base_url` was changed to `"http://localhost"`, which
already matches the existing default. This is a pure test-fixture change:
no product behavior was altered to make tests pass.

## 15. Body-size limit only inspects `Content-Length`; chunked requests are unbounded (Task 7)

`SecurityMiddleware`'s request-size limit rejects (413) a request whose
declared `Content-Length` exceeds the configured maximum (default 10 MiB).
It does **not** enforce a limit on the actual bytes streamed for a request
that omits `Content-Length` (e.g. `Transfer-Encoding: chunked`) or lies
about it. True streaming enforcement would require wrapping `receive()`
and counting bytes as they arrive, which this plan's scope did not extend
to. This is a deliberate, documented, bounded gap -- not a silent one --
appropriate for Plan 07 ("hardening") to close, consistent with the
framework's stated non-goal of "silent fallback when a backend lacks a
requested capability": here the capability gap itself is stated, not
silently assumed away.

## 16. Trusted-proxy client-IP resolution never trusts an untrusted peer (Task 7)

`resolve_client_ip()` only honours `X-Forwarded-For` when the *direct*
connecting peer's IP falls inside one of the configured `trusted_proxies`
CIDRs. An untrusted direct peer's `X-Forwarded-For` claim is ignored
entirely -- accepting it from anyone would let any client spoof its own
rate-limit identity by setting an arbitrary header. `trusted_proxies`
defaults to `()` (nothing trusted), matching "proxy headers are never
trusted automatically" from the framework design.

`validate_production_config()` additionally rejects a `trusted_proxies`
CIDR wider than 2**16 addresses (e.g. `"0.0.0.0/0"`) as an almost-certain
misconfiguration in production.

## 17. `createsuperuser`/`permissions sync` reuse `SQLAlchemyPlugin`'s DI registration; no separate auth plugin (Task 8)

Rather than inventing a distinct `AuthSQLAlchemyPlugin` that re-registers
`async_sessionmaker`, both CLI commands resolve the *same*
`async_sessionmaker` that installing `rakit_sqlalchemy.plugin.SQLAlchemyPlugin`
already registers into the compiled DI registry (`ApplicationBuilder.registry`).
This matches real usage: the built-in auth schema and the application's
own resources typically share one database connection/session factory.
If no `SQLAlchemyPlugin` is installed, `resolver.require(async_sessionmaker)`
raises `KeyError`, caught and reported as a clear, actionable CLI error
(non-zero exit) rather than a raw traceback.

`createsuperuser` additionally distinguishes a duplicate email (exit 1,
"already exists") from a schema/migration mismatch (`OperationalError`/
`ProgrammingError`, exit 1, "has the migration been applied?") -- the
plan's required negative-path coverage for both failure modes.

## 18. Security review summary (Task 8 checkpoint, before packaging)

- **Fail-open vs. fail-closed**: `PermissionRequirement` (finding #4 above),
  `BuiltinAuthorizationPolicy` (default deny), field-policy validation
  (Plan 02, unchanged), identity coercion (Plan 02, unchanged) all fail
  closed. No new fail-open path was introduced by this plan; the one found
  (empty permissions) was fixed before merge.
- **AuthN/AuthZ boundaries**: `AuthBackend.authenticate()` never
  distinguishes "unknown user" from "wrong password" in its return value
  or the login route's response; `BuiltinAuthorizationPolicy` denies
  unauthenticated principals unconditionally before checking permissions.
- **Session/token/cookie handling**: opaque random tokens
  (`secrets.token_urlsafe(32)`), only `sha256(token)` persisted, `HttpOnly`
  + `Secure` (unless debug) + `SameSite=Lax` cookies, idle and absolute
  expiry enforced on every `resolve()`, rotation invalidates the previous
  token, revoke is idempotent.
- **CSRF/origin protection**: double-submit CSRF cookie issued at login;
  `SecurityMiddleware` independently validates Origin/Referer on unsafe
  methods regardless of CSRF-token wiring (defense in depth, since Plan 03
  has no form yet that echoes the CSRF cookie back).
- **Secret/credential redaction**: `SecretValue` (Pydantic `SecretStr`)
  throughout; `SigningKey.__repr__` never exposes its secret;
  `createsuperuser`'s password prompt is hidden and confirmed, and the
  plaintext password is never echoed or logged (only the Argon2id hash is
  persisted).
- **Privilege escalation / bypass paths**: `identity_tie_breakers`-style
  bypasses (Plan 02) don't apply here; `PermissionRequirement`'s
  superuser bypass is explicitly configurable per `AuthorizationPolicy`
  instance (`superuser_bypass: bool`), not hardcoded true.
  `_resolve_session_factory`/CLI commands run one transaction each, not
  reachable from any HTTP route.
- **SQL/query safety**: all queries use the ORM's parameterized query
  builder (`select(...).where(...)`); no raw SQL string interpolation
  anywhere in this plan's code.
- **Arbitrary import/eval/pickle**: none introduced. `load_object()` in
  the CLI (pre-existing from Plan 00/01) resolves a `module:attribute`
  spec the operator supplies on their own command line -- not
  attacker-controlled input in any deployed request path.
- **Error information leakage**: `RakitError.to_public_dict()` (pre-existing)
  continues to gate what's exposed; CLI errors print to stderr with
  actionable but non-sensitive detail (no stack traces, no credentials).
- **Debug vs. production behavior**: `validate_production_config()` fails
  closed on a wildcard allowed-host, a disabled CSP, or an overbroad
  trusted-proxy CIDR whenever `debug=False`; `RakitConfig`'s own validator
  (Plan 00) already requires a persistent `secret_key` in that case.
- **Replay/expiry/rotation**: `TokenService` tokens carry `expires_at` and
  are rejected past it; sessions have both idle and absolute expiry;
  `rotate()` exists for privilege-change flows (not yet auto-invoked by
  any route in this plan, since no privilege-changing operation exists yet
  beyond login itself -- login already creates a fresh session, so nothing
  needs rotating at that point).
- **Transaction/session ownership**: every SQLAlchemy interaction in this
  plan opens its own `async with session_factory() as session: ... await
  session.commit()` block -- no session is held open across an await
  boundary outside that block, no shared/ambient session.
- **Concurrency**: `Argon2PasswordHasher`'s capacity limiter (finding #7);
  `LoginRateLimiter`'s in-memory store is per-process (documented
  limitation, not a correctness bug for a single-process deployment).
- **Mounted ASGI root_path**: `_mounted_path()` (auth_routes.py) reuses the
  same `request.scope["root_path"]` prefixing pattern `resource_routes.py`
  already established in Plan 02, so login/logout redirects and cookie
  paths remain correct when `Admin.asgi()` is mounted under a prefix.
- **Optional dependency isolation**: `cryptography` is a **hard** rakit-core
  dependency (not optional -- see design section 24, key management is
  part of `0.1` and used even without an ORM). `alembic`/`argon2-cffi` are
  `rakit-auth-sqlalchemy`-only. `rakit[auth-sqlalchemy]` is a new optional
  extra on `rakit`, lazily imported only inside `createsuperuser`/
  `permissions sync`; importing `rakit` or compiling a plain `Admin` never
  imports either.

No Critical or Important security finding remains open as of this
checkpoint; the one Important finding (empty `PermissionRequirement`) was
fixed immediately (see #4).

## 19. Fresh independent whole-branch review findings and fixes

A fresh reviewer with no prior context on this branch (given the full
diff, the plan document, the design doc's auth/security sections, and this
document) found zero Critical findings and two Important findings:

1. **Origin/Referer null-hostname bypass** -- `_host_from_url()` returned
   `None` for a literal `Origin: null` (sent by sandboxed cross-origin
   iframes) or a malformed/scheme-less value, and the guard
   `source_host is not None and source_host not in allowed_hosts` then
   *skipped* rejection for exactly that value shape -- the one a
   cross-origin attacker's request would actually carry. Fixed: a present
   source that doesn't resolve to a hostname is now treated as a mismatch
   (absence of both headers remains accepted, unchanged). 3 new regression
   tests (null origin, scheme-less origin, plus an unrelated IPv6
   host-matching bug the same review pass surfaced -- `[::1]` was silently
   unreachable because `.split(":")[0]` truncated it to `"["`). All three
   fail against the pre-fix code. See commit `df604cb`.

2. **The auth stack is built but not enforced anywhere -- by design, not by
   omission.** This is an explicit scope finding, not a code defect: no
   concrete `AuthBackend` implementation exists in this plan (only the core
   `Protocol`), and no middleware resolves the session cookie into a
   `Principal` or gates any route. The home route and every Plan 02
   resource route remain fully public after this plan. This matches
   Plan 03's own task list precisely -- Task 6 says login "Consumes: auth
   backend" (an app-supplied implementation, not one this plan ships), and
   no task in this plan's scope adds route-level permission enforcement.
   **This is stated here explicitly so it is never read as "the admin is
   now protected" by anyone integrating this plan.** Wiring a concrete
   `AuthBackend` (e.g. one backed by `rakit-auth-sqlalchemy`'s `User` model
   and `Argon2PasswordHasher`) and enforcing `PermissionRequirement`s per
   route is deferred to a later plan, consistent with "do not invent
   later-plan functionality."

Minor findings (accepted as-is, not fixed): login/`createsuperuser`
identifiers are not case-normalized (email uniqueness is case-sensitive);
`SecurityMiddleware`'s `max_body_size` is not yet exposed as an `Admin`
constructor parameter (only its documented 10 MiB default is used). Both
are cheap to add later and neither is a live vulnerability.

## 20. Alembic migrations were missing from the installed wheel (found during packaging verification)

`alembic.ini` and `alembic/` originally lived at the package root
(`packages/rakit-auth-sqlalchemy/`), outside `src/`. hatchling's wheel
target only packages `src/rakit_auth_sqlalchemy`, so a real `pip install
rakit-auth-sqlalchemy` from the built wheel silently lacked both files --
the sdist happened to include them (it bundles the whole source tree by
default), masking the gap in every test that ran `alembic` directly
against the source tree rather than an installed wheel. Neither the plan's
own required tests nor the independent code review caught this, since
inspecting *built artifact contents* is a packaging-verification concern,
not a code-review one.

Fixed by moving both under `src/rakit_auth_sqlalchemy/` (Alembic's
`%(here)s/alembic` `script_location` needed no change, since it's already
relative to `alembic.ini`'s own location). Added a regression test
asserting the *built wheel* -- not just the sdist -- contains
`alembic.ini`, `alembic/env.py`, and the initial migration.

---

# External review round 2 (CHANGES REQUESTED)

The external reviewer reconstructed the complete Plan 00-03 repository from
the actual `main...HEAD` patches and independently reproduced five findings
against the tip code. Section 19's characterization of "the auth stack is
built but not enforced" as an acceptable, documented scope note was
**rejected** -- and correctly so: Plan 04 adds write operations, and no
later plan in the v0.1 roadmap is dedicated to turning the primitives into
route protection. Sections 21-26 record the fixes.

## 21. Token trust boundary hardened against malformed input (round 2, finding 4)

`TokenService.verify()` assumed `json.loads` always returns a dict. A
syntactically valid token whose decoded header was a JSON list, null,
string, or number raised `AttributeError` (`.get()` on a list) instead of
a stable `ValueError`. `CsrfService.verify()` caught only `ValueError`, so
this attacker-controlled shape escaped as an unhandled 500.

Fixed:
- `_decode_json_object()` rejects any non-dict JSON root for both header
  and payload, before any field access.
- `_validate_header()` requires `purpose`/`key_id` to be non-empty
  strings, `version` to be **exactly** `int` (not `bool`, not `float`),
  `issued_at`/`expires_at` to be finite non-`bool` numbers with
  `issued_at <= expires_at` -- all raising the same stable
  `ValueError("malformed token")`, and all *before* signature comparison.
- `_b64decode()` now passes `validate=True`. `urlsafe_b64decode`'s default
  (`validate=False`) silently **discards** out-of-alphabet characters, so
  `"not-valid-base64!!!"` previously decoded to *something* rather than
  raising -- a real fail-open in the decode path, not just a cosmetic gap.
- `issue_in()` validates its own inputs: non-empty purpose, positive TTL
  bounded to 365 days, JSON-serializable dict claims.
- `SigningKey` rejects an empty `key_id`; `KeyRing` rejects duplicate key
  IDs across active+previous.

`peek_header()` shape-validates too, so it never hands back a malformed
dict to a caller that (per its own docstring) shouldn't trust it as an
authenticated claim but may still read `key_id` from it.

## 22. Rakit auth Alembic history isolated from the host's (round 2, finding 3)

`env.py` used Alembic's default `alembic_version` table in both offline and
online contexts. A host application running its own Alembic migrations
against the same database already owns that table name, so the two revision
histories would fight over a single "current revision" row -- an upgrade for
either would fail trying to locate a revision ID belonging to the other.

Fixed: both `context.configure()` calls pass
`version_table="rakit_auth_alembic_version"`. Verified by an
installed-wheel integration test that seeds a host `alembic_version` table
with an unrelated revision, runs the Rakit upgrade, and asserts the host's
row is untouched while Rakit's own table reaches head (and that a rerun is
an idempotent no-op).

## 23. Production security validation completed (round 2, finding 5)

Three separate gaps, all fixed:

**Weak root secret.** `SecretValue("x")` passed production validation --
`RakitConfig` required a secret to be *present* when `debug=False` but never
checked its strength. Now rejected below 32 encoded bytes, matching the
HKDF-SHA256 output length every derived key depends on.

**Development limiter silently used in production.** `Admin` created the
explicitly development-only in-memory `LoginRateLimiter` by default even at
`debug=False`. A new `runtime_checkable RateLimiter` Protocol carries a
self-declared `production_safe: bool`; `LoginRateLimiter` declares `False`,
and `validate_rate_limiter_for_production()` (wired into `Admin.__init__`)
rejects any limiter not declaring `True` whenever `debug=False` **and** auth
is configured. A caller supplies their own shared-store limiter to opt in.
Documenting a limitation is not the same as validating against it.

**Unbounded limiter memory.** The limiter retained every unique key
forever -- 10,000 distinct identifiers meant 10,000 permanent dict entries.
Now bounded by `max_tracked_keys` (default 10,000) with LRU eviction via
`OrderedDict`, plus positive-value constructor validation for
`max_attempts`/`window_seconds`/`max_tracked_keys`, and a `threading.Lock`
guarding all mutations so concurrent `check()` calls can't lose counts.

**Partial auth configuration.** `Admin` now rejects exactly one of
`auth_backend`/`session_store` being supplied. Previously this silently
disabled auth entirely -- the exact fail-open shape this plan is supposed
to prevent.

## 24. CSRF and origin protection made real (round 2, finding 2)

**Origin comparison was hostname-only.** `SecurityMiddleware` compared just
the hostname against `allowed_hosts`, so `https://localhost:4443` and
`http://localhost:9999` both passed against a plain `http://localhost`
request -- scheme and port were discarded entirely. Same-origin validation
now canonicalizes `(scheme, host, effective-port)` for *both* the request
and the submitted Origin/Referer and compares them exactly. This is
deliberately a different check from allowed-host validation, which remains
hostname-only by design; conflating the two was the root cause. Default
ports (80/443) compare equal to an omitted port; comparison is
case-insensitive; IPv4, hostname, and bracketed IPv6 forms all work.

**CSRF was never verified anywhere.** `CsrfService.verify()` existed but no
request path called it -- logout performed no CSRF check at all. Logout now
requires a submitted token (form field `csrf_token` or `X-CSRF-Token`
header) that both matches the `rakit_csrf` cookie byte-for-byte
(`hmac.compare_digest`) **and** independently verifies as a genuine
`CsrfService` token bound to the current `session_id`. The second check
matters: a matching cookie/submitted pair alone would also accept a forged
pair copied wholesale from a different session. CSRF is enforced only when
an active session exists -- logging out with no session is a safe no-op with
nothing to protect.

**Rotation didn't rotate.** `SessionStore.rotate()` kept the same
`session_id` and only swapped the token hash. Since CSRF tokens bind to
`session_id`, a pre-rotation CSRF token stayed valid forever after
rotation. `rotate()` now creates a genuinely new session (new `session_id`,
new raw token), **preserves the original `absolute_expires_at`** so
rotation can't extend a session past its absolute deadline, and revokes the
previous row. The `SessionStore` Protocol docstring now states the
new-`session_id` requirement as a contract, not an implementation detail.

## 25. Authentication and authorization actually enforced (round 2, finding 1)

This is the finding that made round 1's "documented scope note" untenable.

**Concrete backend.** `SQLAlchemyAuthBackend` resolves the normalized
email identifier, verifies via `Argon2PasswordHasher`, loads role-granted
non-orphaned permissions, preserves superuser semantics, and updates
`last_login_at`. A missing *or* inactive user pays the same Argon2 cost as
a real verification (a lazily-cached dummy hash) before rejecting, so
response timing doesn't distinguish "no such user" from "wrong password"
from "inactive" -- the non-enumeration guarantee has to hold in timing, not
just in the response body. `User.email` is stored normalized (stripped,
lowercased) so the unique constraint actually prevents case-variant
duplicates and login lookup always matches.

**Per-request principal resolution.** `AuthBackend` gained a second
required method, `resolve_principal(subject_id)`. `PrincipalMiddleware`
calls it on **every** request rather than trusting anything cached in the
session row, so a deactivated user or a changed permission set takes effect
on the next request instead of staying frozen at login. Any failure --
unknown/revoked/expired session, subject no longer active -- yields
`ANONYMOUS_PRINCIPAL`, never a partially-authenticated state.

**Route authorization.** `AuthorizationMiddleware` gates each request
against a requirement resolved from its admin-relative path:
`/auth/login`, `/auth/logout`, and `/_system/*` are explicitly public;
resource list/detail/count require
`{admin_id}.resources.{resource_id}.read`; everything else requires
`{admin_id}.access`. Unauthenticated requests get a 303 to this admin's
own mounted login path (never an attacker-supplied target, so it can't
become an open redirect); authenticated-but-forbidden requests get a
stable 403.

Gating login itself would redirect-loop the admin into unusability, which
is why the public list is explicit rather than inferred. The mount prefix
is stripped before matching (`admin_relative_path`), so a mounted admin
gates the right routes and redirects to its own mounted login path.

**Read-only permission split.** All three resource routes share the single
`.read` permission. Plan 03 ships read-only resources; there is no
create/update/delete route to gate differently yet. The permission
catalogue already generates all four CRUD keys (see section 9) so the key
space stays stable when Plan 04 adds writes.

**Public facade.** `rakit.auth.sqlalchemy.SQLAlchemyAuthPlugin` composes a
matching backend + session store + hasher, lazily imported behind the
`rakit[auth-sqlalchemy]` extra. `rakit.core` now also re-exports the Plan
03 core contracts with preserved identity (`Principal`,
`ANONYMOUS_PRINCIPAL`, `SessionRecord`, `AuthBackend`, `SessionStore`,
`PermissionRequirement`, `AuthorizationDecision`, `AuthorizationPolicy`,
`PermissionDefinition`, `PermissionCatalogue`,
`generate_permission_catalogue`, `TokenService`, `KeyRing`, `SigningKey`)
-- none of which were reachable through the public facade before this
round. Importing `rakit` or `rakit.core` still never imports
`rakit_auth_sqlalchemy`, `argon2`, `alembic`, or `sqlalchemy`.

**No-auth mode.** An `Admin` with neither `auth_backend` nor
`session_store` remains explicitly, unchanged public -- neither middleware
is installed. That configuration is a supported choice; a *partial* one is
not (see section 23).

## 26. Shared path and cookie helpers

`mounted_path` was duplicated in `auth_routes.py` and `resource_routes.py`;
both now import it from `rakit_web._paths`. Session/CSRF cookie names moved
to `rakit_web.security.cookies` so the enforcement middleware and the login
routes cannot drift apart on a cookie name -- a divergence there would
silently break authentication rather than fail loudly.
