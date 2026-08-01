# Plan 02 progress ledger

Task 1: complete (commits c92dfd0..15ada68, review clean — Minor only: identity.py:14 validator
  lacks type annotations, identity.py:29-30 decode() doesn't wrap json.JSONDecodeError/
  binascii.Error in a purpose-built error, test coverage doesn't include malformed-base64/
  mixed-type-values cases. Not blocking, noted for final review roll-up.)
Task 2: complete (commits 15ada68..55bd786, review clean — Minor only: ResourceQuery is
  directly constructible bypassing the sort whitelist (by design, from_params is the
  boundary), duplicate explicit sort fields e.g. "id,-id" aren't deduplicated. Not blocking.)
Task 3: complete (commits 55bd786..ab9c9df, review clean — Minor only: 404 message duplicates
  identity in both message text and details dict, MissingDataSource test fixture duplicates
  FakeDataSource's unused list() body. Not blocking.)
Task 4: complete (commits ab9c9df..2b84b55, review clean — Minor only: EXACT count subquery
  built after order_by is applied (dead ORDER BY in subquery, harmless), sort direction
  compared via .value == "desc" instead of enum equality (style), _claim/constructor both
  call inspect_model (negligible double work). Not blocking. Adds ApplicationBuilder
  .register_adapter/_adapters primitive to compiler.py (design-decisions.md section 3) plus
  ErrorCode.CONFIG_DUPLICATE_ADAPTER, ahead of Task 5's own compiler.py changes.)
Task 5: complete (commits 2b84b55..5f146a3, one fix round — Important finding fixed: retyped
  ApplicationBuilder._adapters/register_adapter against DataSource Protocol instead of object,
  removing an unverified cast() in Admin.register(). Re-review clean. Remaining Minor, not
  blocking: ModelAdmin.model access unguarded (raw AttributeError vs RakitError for the other
  4 attrs), no direct test for CONFIG_DUPLICATE_RESOURCE or resource-registration rollback
  under a failed plugin configure(). Adds admin_types.py (ResourceAdmin/ModelAdmin),
  ApplicationBuilder.add_resource/.resources, CompiledApplication.resources, Admin.register().)
Task 6: complete (commits 5f146a3..e584037, review clean — Minor only: template candidate
  ordering diverges from exact design-section-5 sequence once a theme tier exists (collapses
  to correct order today, no theme system yet), full-page list.html's embedded _table.html
  include doesn't resolve resource-specific overrides (only the standalone fragment route
  does), malformed identity token on /users/<garbage> yields 500 not 404 (codec.decode()
  raises non-RakitError exceptions), 404 JSON response lacks Cache-Control: no-store,
  base.html references /_system/static/htmx.min.js which 404s until Task 8 (expected/noted).
  Not blocking. Extends DataSource Protocol with fields/identity_fields (design-decisions.md
  section 11); adds resource_routes.py, base/list/_table/detail.html, Admin.asgi() real route
  wiring, template_dirs override precedence, RakitError->HTTP exception handler.)
Task 7: complete after typed-filter follow-up (original commits e584037..fb3bd88 plus the focused
  follow-up commit). The unresolved Important finding is fixed at the SQLAlchemy adapter boundary:
  mapped metadata now converts URL text for integer/float/Numeric/boolean/date/datetime/UUID/Enum/
  string fields and `IN` items before predicate construction; invalid values return a stable 400
  `RakitError` before session creation; custom SQLAlchemy types have an explicit safe conversion
  hook; SQLAlchemy Enum persisted names include alias-aware `omit_aliases=False` and
  `values_callable` coverage; `contains` is string-only; PostgreSQL-dialect bind inspection prevents SQLite affinity from
  masking regressions; input queries remain unchanged. Focused SQLAlchemy/web, full pytest, Ruff,
  and ty verification are recorded in task-7-typed-filter-report.md. Remaining Minor (not blocking):
  sort-header links drop active filter params, search form drops active filter params
  (page-reset itself works fine); comparison operators beyond the new string-only `contains` rule
  are not further type-restricted; id-default-sort-header is cosmetic only. Adds
  DISABLED/DEFERRED count policies + search to
  SQLAlchemyDataSource, GET {path}/_count route + _count.html, URL filter/search/count_policy
  parsing in parse_query(), sort-header/search-form UI in _table.html.
Task 8: complete (commit c957b96). Added content-hashed local CSS/HTMX assets,
  immutable and traversal-safe static serving, wheel/sdist resource coverage, mount-aware template
  and resource URLs, an in-memory minimal read-only example, and a FastAPI + application-owned
  SQLAlchemy-engine example mounted at `/admin`. HTMX v2.0.10 source/license provenance verified
  against the authoritative tagged upstream release; 0BSD license and provenance notice bundled.
  Naming ambiguity resolved in favour of importable `examples/fastapi_sqlalchemy/`. Focused RED
  captured (11 expected failures); focused GREEN is 11 passed. Final verification: 256 tests,
  Ruff format/check, ty, diff-check, required CLI commands, wheel/sdist inspection, and isolated
  Python 3.12 installed-wheel resource routes all pass. Full evidence: task-8-report.md.
Task 8 independent-review follow-up: complete (commit 7de96c0). Fixed mounted search
  and sort controls to retain ASGI `root_path`; reverted the root Hatch package so the workspace
  remains virtual and `uv build --all-packages` produces exactly the eight official wheel/sdist
  pairs; documented/tested explicit repository `PYTHONPATH` for private example CLI imports; and
  expanded wheel/sdist tests to enumerate base, list, detail, `_table`, and `_count` templates.
  TDD RED showed `/users` escaping `/admin` and the extra `rakit_workspace` artifact; focused
  follow-up GREEN is 12 passed, full suite is 257 passed, Ruff/ty/diff-check are clean.
Plan 02 final whole-branch review fix wave: complete (commits 134535c, 371b2d4, 0b83409,
  652117d, and 21a499c). Fixed canonical UUID identities and safe
  mapped-PK coercion; deep immutable identity/filter inputs; runtime-equivalent route collision
  checks including built-in home; adapter-enforced identity tie-break ordering; query-state-
  preserving mounted/standalone controls; full-page table override parity; valid `aria-sort`;
  executable README contract coverage; and all requested minor hardening. Focused RED/GREEN
  evidence is in `plan-02-final-review-fixes-report.md`. Final verification: 302 tests passed,
  Ruff format/check passed, ty passed, `uv build --all-packages` produced exactly eight wheels and
  eight sdists at version `0.1.0a1`, every artifact contained `py.typed` and all nine required web
  resources, all four real example CLI checks passed, and the whole-branch diff-check was clean.
Plan 02 final Important multi-column-sort follow-up: implementation complete in commit `be4fec3`.
  Sort-header links now toggle an existing explicit field in place or append a newly clicked field,
  serialize the complete normalized explicit sequence, retain validated filters/search/per-page/
  count-policy state, and omit only page. Adapter-added identity ordering remains absent from the
  URL until the user explicitly clicks the identity column. TDD RED was exactly 2 failures for the
  standalone and mounted sequence-loss cases; focused GREEN was 2 passed, and the full query-UI
  file was 24 passed. Final rerun: query-UI 24 passed, full suite 304 passed, Ruff format/check and
  ty passed, and whole-branch diff-check/status were clean. Exact evidence is in the final-review
  report.
Plan 02 exact locked-development gate follow-up: complete. Added `fastapi>=0.116` only to the
  root workspace `dev` dependency group, preserved the user-facing `examples` extra, and refreshed
  only the corresponding root dev entries in `uv.lock`. TDD RED was 1 intended missing-dev-
  dependency failure with the official-runtime-dependency boundary already passing; focused GREEN
  was 2 passed. The exact `uv sync --all-packages --dev --locked` sequence now passes without
  `--extra`, followed by Ruff, ty, and 306 tests. A fresh ordinary-wheel install resolved 16
  packages with FastAPI absent, every official wheel's `Requires-Dist` excluded FastAPI, and no
  official package `pyproject.toml` changed.
Plan 02 external review round 2 implementation: complete in focused commits `7cdf81c`, `7d9c04f`,
  `c53764d`, and `cc07343`. Added immutable fail-closed field policy and compile-time datasource
  validation; mapper-attribute SQLAlchemy metadata with explicit supported identity types; the
  typed, optional-adapter-free `rakit.core` facade; and accessible canonical pagination controls.
  TDD covered sensitive-field non-exposure and direct-query bypasses, renamed mapped attributes,
  identity-type claim/registration behavior, runtime/type/installed-wheel facade imports, and
  first/middle/last pagination standalone and mounted under every count policy. Exact final-gate
  evidence is recorded in `plan-02-external-review-round2-report.md`.
Plan 02 external review round 3: complete in commit `440c36d`. Fixed three CHANGES-REQUESTED
  findings: (1) ResourceQuery.identity_tie_breakers separated from policy-validated `.sorting`
  so from_params(identity_fields=...) composes with a narrower adapter sort_fields policy
  without reopening the de5dec5 bypass; (2) SQLAlchemy identity acceptance now checks effective
  Python type (int/str/UUID), unconditionally rejecting Enum (Python-Enum-backed and plain-
  string alike) and TypeDecorators whose python_type override differs, with an explicit opt-in
  rakit_identity_codec hook and a dedicated _coerce_identity_component boundary separate from
  filter coercion; (3) SQLAlchemyDataSource.__init__ now fail-closed validates search_fields
  (string-only, excl. Enum) and filter_fields (must have a coercion path or hook) at adapter-
  claim time instead of silently no-op'ing unsupported search fields at request time. Also adds
  a worktree-local .uv-cache/ (gitignored) working around a sandbox permission denial on the
  shared user uv cache. TDD: 19 new tests across rakit-core/rakit-sqlalchemy/rakit-web,
  full suite 376/376 passing, ruff format/check clean, ty check clean (0 real diagnostics; the
  only io-access-denied entries are the pre-existing disposable .tmp-pytest-final-findings/ and
  a same-cause locked scratch dir this round could not remove either, both git-invisible/
  untracked). Full unrestricted verification (uv sync/build, 8 wheels+8 sdists at 0.1.0a1,
  py.typed + templates/static/license/provenance present, minimal install excludes
  SQLAlchemy/FastAPI, sqlalchemy extra installs, both examples + rakit check/routes, rakit.core
  facade import) all passed at HEAD 440c36d. A fresh independent whole-branch review (34-commit
  diff, main...HEAD) found zero Critical/Important findings -- Ready to merge: Yes, with two
  Minor non-blocking notes (redundant double inspect_model in SQLAlchemyPlugin._claim; standard
  Starlette debug-traceback behavior for non-RakitError exceptions under debug=True, unrelated
  to Plan 02 scope).
Plan 02 external review round 2 Important follow-up: implementation complete in focused commits
  `de5dec5`, `55140d1`, and `f0e51f5`. Direct SQLAlchemy queries can no longer opt into identity sorting unless
  the identity is explicitly declared in `sort_fields`; adapter-added identity tie-break ordering
  remains internal and exactly once. Malformed ResourceAdmin field declarations now normalize at
  registration or fail as safe non-echoing `config.invalid_resource_policy` errors without partial
  resource registration. TDD RED was 7 failures with 2 positive controls already passing; focused
  GREEN was 9 passed, broader affected regression was 55 passed, CLI regression was 2 passed, and
  Ruff/ty passed. A subsequent web integration RED showed parser-injected identities returning 400;
  identity insertion now occurs only inside the adapter after validation. The focused list/count,
  renamed-attribute, and query-UI regression passed 32/32. Exact evidence is in
  `plan-02-external-review-round2-report.md`.
Plan 02 external review round 4: fixes for three CHANGES-REQUESTED findings against the round-3
  commit (440c36d). (1) Removed custom identity domain-object support from Plan 02 entirely,
  per the reviewer's preferred bounded fix: `rakit_identity_codec` is gone (it was fail-open --
  accepted whenever merely non-None, no shape validation, no encode direction ever wired through
  the web layer's `_identity_values()`). A TypeDecorator identity now MUST explicitly declare
  `python_type` (a `NotImplementedError` from an unoverridden `python_type` is now rejected,
  not trusted via impl -- this was the other fail-open path: a decorator overriding only
  `process_result_value()` without `python_type` was silently accepted) and is accepted only
  when that declared type is exactly int/str/UUID. (2) `identity_tie_breakers` are now
  validated against `self.identity_fields` (not `self.fields`), ASC-only, `NullPlacement.AUTO`-
  only, no duplicates -- closing a bypass where a caller could order by a sensitive known field
  (e.g. password_hash) by placing it in identity_tie_breakers instead of sorting. (3)
  `_is_filterable_type` now checks `callable(rakit_coerce_filter_value)`, not merely
  `is not None`, so a malformed hook (e.g. `= object()`) fails registration instead of only
  failing at the first request that uses it. See design-decisions.md sections 27-29 (27
  supersedes section 25). 12 new/changed tests, full suite 388/388 passing, ruff format/check
  and ty check clean (0 real diagnostics). Full clean-filesystem verification ran in a fresh
  detached worktree (.claude/worktrees/plan-02-final-verification, removed after use): uv sync,
  ruff format/check, ty check, pytest (388/388), uv build (8 wheels+8 sdists at 0.1.0a1),
  minimal/extra installs, both examples + rakit check/routes, git diff --check -- every command
  exited 0 with zero io-access-denied entries (no locked scratch directories in a fresh
  worktree). A fresh independent whole-branch review (no prior branch context, 35-commit
  main...HEAD diff) verified all three findings against the tip-commit code and tests directly
  (not the design doc's self-description) and found zero Critical/Important findings -- Ready
  to merge: Yes. Two Minor notes: redundant double inspect_model() in
  SQLAlchemyPlugin._claim/SQLAlchemyDataSource.__init__ (unchanged from round 3, still
  harmless); resource_routes.py's _identity_values() silently drops a non-int/str/UUID identity
  value instead of raising, currently unreachable since only int/str/UUID identities are
  accepted, but inconsistent with the fail-closed philosophy applied elsewhere -- noted, not
  fixed (no live vulnerability, cosmetic consistency only).
Plan 02 external review round 5: fixes for two remaining CHANGES-REQUESTED findings against the
  round-4 commit (dfa5e4b), independently reproduced against the actual implementation. (1)
  `_coerce_identity_component` still converted decoded identity URL text via a TypeDecorator's
  unwrapped storage `impl`, not its round-4-validated `python_type` -- a legitimate wrapper
  whose storage representation differs from its effective Python type (e.g. TypeDecorator[UUID]
  backed by String) got a str where its own process_bind_param expects a UUID, failing at
  execution despite passing claim-time validation. Fixed via a new
  `_coerce_by_effective_python_type`, keyed on the already-validated python_type; non-decorator
  columns unaffected; rakit_identity_codec remains removed. (2) `_is_filterable_type` accepted
  any `rakit_coerce_filter_value` hook that was merely `callable(...)`, regardless of call-
  signature compatibility with the documented `(value: str) -> object` contract -- a zero-arg or
  two-required-arg hook passed registration and only failed on the first request. Fixed via a
  new `_accepts_one_positional_argument` helper using `inspect.signature(...).bind("probe")`
  (never invokes the hook), fail-closed on TypeError/ValueError. See design-decisions.md
  sections 30-31 (refining 27 and 29). TDD: 10 new/changed tests including real-execution round
  trips (not just compiled-statement inspection) for both findings, full suite 400/400 passing,
  ruff format/check and ty check clean (0 real diagnostics; only pre-existing io-access-denied
  entries on git-invisible locked scratch dirs). Fix commit: cb8e6e8.

# Plan 03 progress ledger

Plan 03 (Authentication, Authorization, and Security) started 2026-07-23 on branch
`worktree-plan-03-authentication-authorization-security` from approved main HEAD
`81a24b56b95454b960ea4a239dd8d684f7be807c` (Plan 02, merged and closed out).

Task 1 (`225ee05`): `TokenService`/`KeyRing`/`SigningKey` in `rakit_core.crypto` --
purpose/admin/version-separated HKDF-SHA256 key derivation, HMAC-SHA256 signing,
constant-time verification. Fails closed on purpose mismatch, version mismatch,
unknown key ID, expiry, and signature tampering. 10 new tests. Adds `cryptography`
as a rakit-core runtime dependency.

Task 2 (`4818a72`): `Principal`/`SessionRecord`/`AuthBackend`/`SessionStore` in
`rakit_core.auth`; `PermissionRequirement`/`AuthorizationDecision`/
`AuthorizationPolicy` in `rakit_core.permissions`. 6 new tests.

Fix (`7e83c6a`, found by automated security review immediately after Task 2):
`PermissionRequirement.permissions` rejected empty at construction --
`all(())`/`any(())` are Python-truthy, so an empty requirement would have
vacuously matched every principal. See plan-03-design-decisions.md section 4.

Fix (`24e22bb`): dropped `SessionRecord.csrf_token` before any consumer depended
on it -- a CSRF token is a `TokenService`-derived value bound to `session_id`,
not stored session state. See plan-03-design-decisions.md section 2.

Task 3 (`4811380`): `User`/`Role`/`Permission`/`Session` models (own
`DeclarativeBase`) plus the forward-only initial Alembic migration
(`0001_initial_auth`) in `rakit-auth-sqlalchemy`. `User`/`Permission` gained
explicit `__init__` overrides so secure defaults are visible immediately at
construction (`mapped_column(default=...)` alone only applies at INSERT time).
7 new tests; alembic upgrade smoke check passes against `sqlite:///:memory:`.
Adds `alembic`/`argon2-cffi` as rakit-auth-sqlalchemy dependencies.

Task 4 (`b243882`): `Argon2PasswordHasher` (argon2-cffi, off-loop via
`anyio.to_thread.run_sync` bounded by a `CapacityLimiter`) and
`SQLAlchemySessionStore` (opaque tokens, only `sha256(token)` persisted,
idle/absolute expiry enforced on every resolve, rotate/revoke). 17 new tests.

Task 5 (`2f23243`): `generate_permission_catalogue()` (rakit-core) derives
`{admin_id}.access` and unconditional per-resource CRUD keys from compiled
resources; `sync_permissions()`/`BuiltinAuthorizationPolicy` (rakit-auth-sqlalchemy)
implement allow-only RBAC with orphan-preserving sync (never deletes). 12 new
tests.

Fix (`cd8341a`): `sync_permissions()` returns `PermissionSyncResult(added,
updated, orphaned)` instead of `None`, for the Task 8 CLI to report.

Task 6 (`36dc1f8`): `/auth/login` (GET+POST) and `/auth/logout` (POST), wired
into `Admin.asgi()` only when both `auth_backend` and `session_store` are
configured. Non-enumerating 401 for unknown-identifier/wrong-password.
HttpOnly+Secure(unless debug)+SameSite=Lax session cookie; non-HttpOnly
double-submit CSRF cookie. Per-(admin,identifier-hash,IP) login rate limiting
(in-memory, documented development-only). 16 new tests. Adds
`python-multipart` as a rakit-web dependency.

Task 7 (`f68f4a4`): `SecurityMiddleware` applied unconditionally to every
`Admin.asgi()` -- trusted-host validation (400), mutation Origin/Referer
validation (403), declared-Content-Length body-size limit (413, chunked
requests documented as not yet bounded), and response security headers
(CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP,
X-Frame-Options, Cache-Control: no-store) without overriding route-set
headers. `resolve_client_ip()` only trusts X-Forwarded-For from a configured
trusted-proxy CIDR. `validate_production_config()` fails closed on a
wildcard allowed-host, disabled CSP, or overbroad trusted-proxy CIDR
whenever `debug=False`. 14 new tests. Required migrating every rakit-web
test fixture's Host header from httpx's `testserver` convention to
`localhost` (already the existing default `allowed_hosts` entry) -- a
test-fixture change, not a product behavior change; see
plan-03-design-decisions.md section 14.

Task 8 (`c73a617`): `rakit createsuperuser <target> --email ... [--username
...]` (hidden/confirmed password prompt, Argon2id hash, resolves the
target's installed `SQLAlchemyPlugin` session factory from the compiled DI
registry -- no separate auth plugin needed) and `rakit permissions sync
<target>` (generates the catalogue from compiled resources, reports
added/updated/orphaned). Both exit non-zero with a clear stderr message for
a duplicate email, missing SQLAlchemy plugin, or schema mismatch. 4 new
tests. Adds the optional `rakit[auth-sqlalchemy]` extra, lazily imported.

All eight Plan 03 tasks complete. Full suite 488/488 passing, ruff
format/check and ty check clean across the whole workspace after each task.

Fresh independent whole-branch review (`041b258`..HEAD): zero Critical,
two Important findings. Fix (`df604cb`): closed an Origin/Referer
null-hostname bypass (a literal `Origin: null` or scheme-less value was
silently accepted instead of rejected) and fixed IPv6 loopback host
matching (`[::1]` was silently unreachable in the default `allowed_hosts`).
3 new regression tests, all failing against pre-fix code. Second finding
("the auth stack is built but not enforced anywhere") is an explicit,
correct scope observation matching the plan's own task list -- documented
prominently in design-decisions.md section 19 so it is never misread as
"the admin is now protected." Full suite 491/491 passing after the fix.

Fix (`f82a7fb`, found during the first clean-worktree packaging
verification pass, not by the independent review): the Alembic migration
files lived at the package root, outside `src/`, so hatchling's wheel
target silently excluded them from a real `pip install
rakit-auth-sqlalchemy` -- only the sdist happened to include them. Moved
both under `src/rakit_auth_sqlalchemy/`; added a regression test asserting
the *built wheel* (not just the sdist) contains them. Full suite 491/491
passing after the fix.

Next: re-run clean-filesystem verification at the new HEAD, regenerate
the review package, stop for external review.

Plan 03 external review round 2 (CHANGES REQUESTED): five findings, all fixed.
  The reviewer rejected round 1's characterization of "auth built but not
  enforced" as an acceptable documented scope note -- correctly, since Plan 04
  adds writes and no later v0.1 plan is dedicated to turning the primitives
  into route protection.

  Finding 4 (`67c62f6`): hardened the token trust boundary. TokenService.verify()
  assumed json.loads returns a dict; a token whose decoded header was a JSON
  list/null/string/number raised AttributeError, and CsrfService caught only
  ValueError -- so attacker-controlled malformed input escaped as a 500. Now
  every non-dict JSON root is rejected, header fields are shape-validated
  (non-empty purpose/key_id, exactly-int version, finite issued_at<=expires_at)
  before signature comparison, and _b64decode uses validate=True (the default
  silently discarded out-of-alphabet characters). issue_in() validates its own
  inputs; SigningKey/KeyRing reject empty and duplicate key IDs. 54 new tests.

  Finding 3 (`84d92b8`): isolated Rakit's Alembic revision history into
  `rakit_auth_alembic_version` in both offline and online contexts, so it no
  longer collides with a host application's own `alembic_version` table.
  Installed-wheel integration test seeds a host history, runs the Rakit
  upgrade, and asserts the host's row is untouched and a rerun is idempotent.

  Finding 5 (`77373e9`): completed production security validation. Minimum
  32-byte root secret (SecretValue("x") previously passed); a runtime_checkable
  RateLimiter Protocol with self-declared production_safe, rejected at
  Admin.__init__ when debug=False and auth is configured (the in-memory
  development limiter was silently used in production); LRU-bounded limiter
  storage with a threading.Lock (unique keys were retained forever); positive
  constructor validation; and rejection of a partial auth configuration
  (exactly one of auth_backend/session_store), which previously disabled auth
  silently. 38 new/changed tests.

  Finding 2 (`e6d6e05`): made CSRF and origin protection real. Same-origin
  validation now canonicalizes scheme+host+effective-port for both the request
  and the submitted Origin/Referer -- hostname-only comparison had accepted
  https://localhost:4443 and http://localhost:9999 against a plain
  http://localhost request. Logout now actually verifies CSRF (constant-time
  double-submit match plus session-bound token verification; a forged matching
  pair from another session is rejected). rotate() now issues a genuinely new
  session_id, preserves the original absolute-expiry boundary, and revokes the
  previous row, so a pre-rotation CSRF token stops being valid. 37 new/changed
  tests including adversarial origin cases and mounted-root_path behavior.

  Finding 1 (`d13461a`, `af4fe00`, `93a4478`): implemented full enforcement.
  SQLAlchemyAuthBackend (normalized identifier, Argon2 verification,
  role-granted non-orphaned permissions, superuser semantics, last_login_at,
  and a dummy-hash path so unknown/inactive users cost the same time as a real
  verification). AuthBackend gained resolve_principal(subject_id);
  PrincipalMiddleware calls it every request so deactivation and permission
  changes take effect immediately rather than freezing at login.
  AuthorizationMiddleware gates each request by admin-relative path:
  /auth/login, /auth/logout, /_system/* explicitly public; resource routes
  require {admin_id}.resources.{resource_id}.read; everything else requires
  {admin_id}.access. Unauthenticated -> 303 to this admin's own mounted login
  path; authenticated-but-forbidden -> stable 403. Public facade
  rakit.auth.sqlalchemy.SQLAlchemyAuthPlugin plus the Plan 03 core contracts
  through rakit.core, all with preserved identity and lazy optional imports.
  A no-auth Admin stays explicitly public; a partial one is rejected. 60 new
  tests including a real-database end-to-end createsuperuser -> login ->
  authenticated request chain.

  See plan-03-design-decisions.md sections 21-26. Full suite 636/636 passing,
  ruff format/check and ty check clean across the whole workspace.

Plan 03 round-2 independent review: "Ready to merge: Yes", zero Critical at
  the tip, all five round-2 findings confirmed genuinely fixed with
  revert-failing regression tests. Three Important and two latent-fail-open
  Minor findings fixed on top.

  Self-found Critical (`3124866`, fixed before the review reported it): my
  own bypass-probing of the new enforcement middleware found `is_public_path`
  using a bare `startswith`, so any path merely beginning with a public root
  (e.g. a resource at `/auth/loginaudit`) skipped authorization entirely.
  Login/logout now match exactly, only `/_system` has `/`-boundary
  descendants, and any dot segment -- literal or percent-encoded -- is never
  public. The reviewer independently reproduced the same defect against the
  pre-fix HEAD.

  Important fixes (`781932d`): SecurityMiddleware's own 400/403/413
  rejections went through the raw `send` and so carried none of the security
  headers the middleware exists to add -- now routed through the header
  wrapper. The CSRF token's 4h TTL against a 14-day session made logout
  permanently 403 once it lapsed, with no re-issue path -- DEFAULT_CSRF_TTL
  is now 14 days and configurable, with a test pinning that tokens still
  expire. `/auth/login`, the only unauthenticated state-changing endpoint,
  had no CSRF defence for a client omitting both Origin and Referer -- it
  now issues a pre-session double-submit token (HttpOnly cookie + hidden
  field) verified constant-time before credentials are read, so a forged
  POST never reaches the backend nor burns a rate-limit slot.

  Minor fail-open fixes (`dd1489f`): `PermissionRequirement.matches()`
  honoured `is_superuser` before checking `authenticated`, and
  `build_requirement_resolver()` returned the first rather than longest
  matching resource prefix. Both unreachable today, both wrong-by-default
  for authorization primitives.

  Accepted Minor findings, each with rationale in design-decisions.md
  section 27: `BuiltinAuthorizationPolicy` still not invoked by the
  middleware (deliberate -- becomes load-bearing when a later plan needs the
  structured decision for audit logging); only `/_system` is
  compiler-reserved (a Plan 00/01 compiler concern); `createsuperuser`'s
  duplicate check uses the un-normalized email (CLI ergonomics, unique
  constraint still holds); no password-strength check, no session revocation
  on re-login, no audit logging (features the approved plan does not
  specify).

  Full suite 650/650 passing, ruff format/check and ty check clean.

Plan 03 round-4 external review fixes are implemented in six focused product
commits plus one installed-artifact regression commit:

- `702f05e`: the initial auth migration is genuinely forward-only; downgrade
  refuses before altering revision state, tables, or data.
- `1a7d758`: trusted proxy CIDRs are compiled once and client IP resolution
  validates and canonicalizes every hop while walking the chain from the
  trusted right-hand edge.
- `276f428`: security middleware enforces the body limit on cumulative ASGI
  bytes and login parsing has bounded fields, values, and multipart parts.
- `4881eca`: session lifetimes are validated during construction against the
  public token TTL ceiling, and failed CSRF issuance revokes its new session.
- `aa962d4`: production auth requires a session store whose safety declaration
  is exactly `True` and whose required operations have compatible signatures.
- `9d372d2`: migration tests no longer disable Rakit log capture, and installed
  artifact tests resolve third-party dependencies while still selecting local
  unpublished Rakit wheels through `--find-links`.
- `b37e751`: the installed-wheel migration test seeds every auth relation and
  proves downgrade refusal preserves both Rakit and host Alembic histories.

Focused and affected-package suites passed after each change. Final detached
whole-workspace and installed-artifact verification is pending the fresh
independent round-4 review.

The fresh independent review found two Important edge cases and no Critical
findings at `d7748d4`: duplicate X-Forwarded-For header fields were not joined,
and a 5,000-digit Content-Length escaped as Python's integer conversion
`ValueError`. Both received revert-failing direct-ASGI regressions and are fixed
by parsing every forwarded header field in wire order and comparing normalized
digit length before integer conversion. The affected `rakit-web` suite passes
435/435. The review's remaining Minor observation was also fixed with a
revert-failing test: production session-store methods must be coroutine
functions, so a synchronous implementation cannot pass construction and fail
at its first `await`. Final whole-branch verification remains pending.

Plan 03 round-5 external-review fixes are implemented with TDD:

- `864abdf`: `RateLimiter.check` is async, awaited exactly once, returns an
  actual bool, and receives the same canonical identifier as the backend.
- `43a15cd`: dummy Argon2 initialization is retryable single-flight; 50 cold
  callers share one hash operation.
- `c098f7b`: trusted XFF chains parse lazily right-to-left, unresolved chains
  return secured 400, and no client falls into a shared proxy bucket.
- `f5b7481`: SQLAlchemy store safety derives from its bind; unbound and all
  SQLite factories are development-only, and plugin factory identity is fixed.
- `408b0c8`: raw ASGI Host/Origin/Referer cardinality is enforced and
  coexisting Origin plus Referer are both validated.
- `6989221`: limiter core unit tests avoid per-call event-loop creation while
  route/protocol tests retain public async-await coverage.

The source-worktree gate passes 974 tests with Ruff format/check and ty clean.
Fresh review and detached installed-artifact verification remain pending.

The independent review then identified a stale-capability Important: an
`async_sessionmaker` can be rebound after store construction. The store now
derives its read-only `production_safe` property from the current bind on each
validation, and the core protocol models that property as read-only. A
reconfiguration from a shared async engine to SQLite is proven to fail the
production validator.

The same review found one further Important failure oracle: dummy-hash
initialization errors affected only unknown/inactive identifiers. Authentication
now requires successful dummy initialization before querying any identifier, so
a persistent/transient initializer failure has the same external outcome for
known and unknown accounts while retaining retry-after-failure behavior.
