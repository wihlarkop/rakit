# Plan 02 bounded design decisions

Derived from docs/design/2026-07-19-rakit-framework-design.md (sections 4-11, 15, 27-28, 44)
to fill gaps the plan text (docs/plans/2026-07-19-02-read-only-resources-ui.md) leaves
underspecified. These are binding for every task's implementer unless a task brief overrides
one explicitly. Document these in the final review/plan-02/summary.md "Plan deviations /
underspecified requirements" section verbatim.

## 1. RouteDefinition has no handler; routes are not yet wired to Starlette

Confirmed by code inspection: `rakit_web.admin.Admin.asgi()` currently builds its Starlette
app from 3 hardcoded routes and never reads `self.compiled.routes` at all. `RouteDefinition`
(core) is a framework-neutral (path, methods, name, owner_id) tuple used only for collision/
reserved-path validation in `compile_application`. This is intentional per design section
2/6 (core stays ORM/web-framework neutral) -- core must not carry Starlette callables.

Decision: keep `RouteDefinition` exactly as-is (core-side, handler-less, validation-only).
Add the resource_id -> handler association entirely on the *web* side:

- `rakit_web/resource_routes.py` builds a `ResourceBinding` (per-resource: `definition`,
  `service: ResourceService`, `parse_query`, `templates`) and a small dict of Starlette
  `Route` objects for `{path}` (list) and `{path}/{id}` (detail), plus `{path}/_count` if
  deferred counting is enabled for that resource (Task 7).
- `Admin` stores `self._resource_bindings: dict[str, ResourceBinding]` populated during
  `register()`, and `Admin.asgi()` is generalized to also mount each binding's routes
  (in addition to the existing hardcoded `/`, `/_system/health`, `/_system/ready`).
- `request.app.state.rakit` (referenced by the plan's own Task 6 test snippet as
  `request.app.state.rakit.resources[...]`) is set once in `asgi()` to a small object/dict
  exposing `resources: dict[str, ResourceBinding]`.

## 2. ApplicationBuilder / CompiledApplication gain a `resources` primitive

Mirrors the existing `add_route`/`routes` pair. Add to `rakit_core.compiler`:

- `ApplicationBuilder._resources: list[ResourceDefinition]`, `.resources` read-only property,
  `.add_resource(definition: ResourceDefinition) -> None` (checks not-compiled, rejects
  duplicate `resource_id`, mirrors `add_route`'s pattern; use a new
  `ErrorCode.CONFIG_DUPLICATE_RESOURCE`).
- `CompiledApplication.resources: tuple[ResourceDefinition, ...]` field.
- `_InstallSnapshot` gains `resources: list[ResourceDefinition]` capture/restore, matching
  `routes` handling exactly, since resource registration must be transactional under
  `ApplicationBuilder.install()` the same way route registration already is.
- `compile_application()` returns `CompiledApplication(builder.routes, builder.plugins,
  builder.resources)`.

This keeps `ResourceDefinition` (already defined in `definitions.py`, unused until now)
core-side and framework-neutral, matching Task 5's own test:
`admin.compile().resources[0].resource_id == "users"`.

## 3. Adapter claim mechanism (ModelAdmin -> DataSource)

Plan Task 5 says: "asks installed adapters to claim the model, and fails when zero or
multiple adapters claim it." Mechanism (not specified by the plan). Cross-task dependency
note: the plan's own Task 5 test snippet (`admin.register(UserAdmin)` with no preceding
`admin.install(SQLAlchemyPlugin(...))` call) is illustrative/incomplete like every other
plan-shown test in this document -- a real claim-based registration cannot succeed with zero
adapters installed, so Task 5's actual test must install a working adapter plugin first. That
means the "register a claim callback" primitive has to exist and be exercised *before* Task 5's
test can pass, which pulls a small piece of what looks like Task 5's file (`compiler.py`) work
one task earlier:

- **Task 4** adds to `ApplicationBuilder` (`rakit_core/compiler.py`): `_adapters: dict[str,
  Callable[[type], DataSource | None]]` and `register_adapter(name: str, claim: Callable[[type],
  DataSource | None]) -> None` (checks not-compiled, rejects duplicate adapter name with a new
  `ErrorCode.CONFIG_DUPLICATE_ADAPTER`; `_InstallSnapshot` gains `adapters` capture/restore,
  matching the existing `_plugin_conflicts` transactional pattern). `SQLAlchemyPlugin.configure(builder)`
  calls `builder.register_adapter("sqlalchemy", self._claim)`, where `self._claim(model)` calls
  `inspect_model(model)` (catching the "not a SQLAlchemy model" exception and returning `None`
  on failure) and, on success, returns `SQLAlchemyDataSource(model=model,
  session_factory=self._session_factory)`. Task 4 adds a direct test of `_claim`/`register_adapter`
  (e.g. `test_plugin.py`) independent of the full `Admin`/`ApplicationBuilder` registration flow,
  since Task 5's `ModelAdmin`/`ResourceAdmin`/`admin_types.py` types don't exist yet at Task 4 time.
- **Task 5** adds `ApplicationBuilder.add_resource`/`.resources` and `CompiledApplication.resources`
  (see decision 2) and `Admin.register(admin_cls)`, which iterates `self._builder._adapters.values()`,
  collects every non-`None` claim result, and raises if the count is 0
  (`ErrorCode.CONFIG_ADAPTER_NOT_FOUND`) or >1 (`ErrorCode.CONFIG_ADAPTER_AMBIGUOUS`). Task 5's
  test extends the plan's illustrative snippet by installing a `SQLAlchemyPlugin` (reusing Task 4's
  `session_factory`/`User` test fixtures) before calling `admin.register(UserAdmin)`.

## 4. Session/DI scope for read-only datasources (bounded -- do not build general
   per-request DI resolution in this plan)

No per-HTTP-request `ServiceResolver` scope currently exists anywhere in `rakit_web`
(confirmed: `Admin` only opens/closes a single *application*-scoped resolver across the whole
process lifespan; nothing opens a REQUEST-scoped resolver per incoming request yet). Building
general request-scoped DI resolution for HTTP handlers is out of this plan's scope (Plan 02 is
read-only; write-path unit-of-work/transactions are later-plan territory per roadmap
"Explicit transaction policies" / "Operation-scoped DI and unit of work").

Decision: `SQLAlchemyDataSource` owns its own session lifecycle per call
(`async with self._session_factory() as session: ...` inside `list()`/`detail()`), constructed
once at adapter-claim time with a plain `async_sessionmaker` closed over by the plugin. It does
NOT go through `ServiceResolver`/`ServiceScope.REQUEST`. `SQLAlchemyPlugin` additionally
registers the `async_sessionmaker` as an `APPLICATION`-scoped DI value
(`registry.add_value(async_sessionmaker, self._session_factory, scope=ServiceScope.APPLICATION)`)
purely so other application code/tests can resolve it later -- Plan 02 itself does not consume
it that way for the read routes.

## 5. Templates: override precedence and layout

Design section 27 precedence: (1) resource-specific user override, (2) generic user override,
(3) theme/plugin template, (4) built-in template. Bounded implementation for Plan 02 (no theme
system yet -- step 3 collapses into step 4 until a theme system exists):

- `Admin.__init__` gains `template_dirs: tuple[Path, ...] = ()` (user override roots, checked
  in order, first match wins).
- Built-in loader is `PackageLoader("rakit_web", "templates")`.
- Resolution order for a given logical template name (e.g. `resources/list.html` for resource
  `users`): try `resources/users/list.html` in each user dir, then `resources/list.html` in
  each user dir, then `resources/users/list.html` in the built-in package, then
  `resources/list.html` in the built-in package. Implement via a small custom Jinja `Loader`
  or a `ChoiceLoader` built from a precomputed ordered list of `FileSystemLoader`/
  `PackageLoader` instances -- implementer's choice, document whichever is chosen.
- `Jinja2Templates` (starlette.templating) wraps the resulting `Environment`.

## 6. Cache-Control scope

"Admin HTML responses use `Cache-Control: no-store`" (global constraint) applies to every
response this plan's `resource_routes.py` returns (list/detail/table/count fragments). It does
NOT retroactively touch the pre-existing hardcoded `/` home route or `/_system/health`/`ready`
JSON routes -- those are unmodified by this plan's file list.

## 7. Error codes

Reuse existing `ErrorCode.RESOURCE_NOT_FOUND` for `ResourceService.detail()` 404s. Add new
codes following the existing `"<domain>.<snake_case>"` convention as needed, e.g.
`CONFIG_DUPLICATE_RESOURCE`, `CONFIG_ADAPTER_NOT_FOUND`, `CONFIG_ADAPTER_AMBIGUOUS`,
`RESOURCE_QUERY_INVALID_SORT_FIELD`, `RESOURCE_QUERY_INVALID_FILTER_FIELD`,
`RESOURCE_QUERY_UNSAFE_COUNT`. Implementers should add codes to `ErrorCode` as they are needed
rather than pre-declaring all of them here.

## 9. `rakit.sqlalchemy` facade re-exports (folded into Task 4)

`packages/rakit/src/rakit/sqlalchemy.py` currently only calls
`require_module("rakit_sqlalchemy", extra="sqlalchemy")` and re-exports nothing. Design
section 44 mandates `from rakit.sqlalchemy import SQLAlchemyPlugin` as the public surface, and
no task in the plan's file lists explicitly revisits this facade file. Since Task 4 is the task
that "Produces: SQLAlchemyPlugin", folding a two-line facade update into Task 4 (add
`from rakit_sqlalchemy.plugin import SQLAlchemyPlugin` inside the existing `optional_import`
context manager block, plus `__all__`) is the smallest bounded fix that satisfies the design
doc's public-import contract without expanding Task 4's actual scope (adapter + plugin
implementation).

## 10. `ResourceAdmin` (non-`ModelAdmin`) data source acquisition

Design section 9.2: "The initial custom resource target is read-only list and detail over an
arbitrary data source." Task 5's own file list only shows a `ModelAdmin` test (adapter-claim
path via an installed SQLAlchemy plugin). A raw `ResourceAdmin` subclass has no `model`
attribute to claim against, so it needs a different, direct way to supply its `DataSource`.
Bounded decision: `ResourceAdmin` gains an optional class attribute
`data_source: DataSource | None = None`. `Admin.register(admin_cls)`'s dispatch:
1. if `issubclass(admin_cls, ModelAdmin)` -> adapter-claim path (decision 3);
2. elif `admin_cls.data_source is not None` -> use it directly, no adapter involved;
3. else -> raise `RakitError(code=ErrorCode.CONFIG_RESOURCE_MISSING_DATA_SOURCE, ...)`.
This keeps `ResourceAdmin` genuinely usable standalone (matching the design doc) without
inventing a second claim/registration mechanism for arbitrary data sources.

## 11. Where do allowed sort/filter fields and identity fields come from? (Task 6)

`ResourceQuery.from_params()` (Task 2, merged) takes explicit `allowed_sort_fields`/
`identity_fields` parameters -- by design the CALLER supplies the whitelist, not the query
module itself. But nothing in Plan 02's task list adds a per-resource field-configuration DSL
(`list_fields`, explicit column declarations, etc. -- that's design doc section 12/13's fuller
"Fields, schemas, forms" system, not scoped into this plan). The most bounded, plan-faithful
interpretation for a read-only `0.1` slice: the whitelist IS the full set of fields the data
source actually introspected -- i.e. "whitelisted" means "the data source knows about and can
safely read this field," with no additional developer-authored hiding/security layer yet (that
is design section 13's "Field security and presentation," explicitly not part of Plan 02).

Decision: additively extend the `DataSource` Protocol (`rakit_core/datasource.py`, Task 3,
already merged) with two more required attributes: `fields: tuple[str, ...]` (every field the
source can sort/filter/search on) and `identity_fields: tuple[str, ...]` (for the tie-breaker
append). This is a small, non-breaking, purely additive Protocol change:
- `SQLAlchemyDataSource` (Task 4, already merged) already computes exactly this via
  `self._metadata.fields`/`self._metadata.identity_field` (singular in `0.1`, wrap in a
  1-tuple) -- expose them as `self.fields`/`self.identity_fields` properties, no new logic.
- Every existing `FakeDataSource`/test-double `DataSource` implementation across already-merged
  Task 3/4/5 test files needs these two attributes added (mechanical -- add two class/instance
  attributes with a fixed tuple value, e.g. `fields = ("id", "name")`, `identity_fields =
  ("id",)`; no test *behavior* or assertion should change).
- `ResourceService` (Task 3, already merged) gains a read-only `data_source` property
  (`return self._data_source`) so Task 6's route factory can read `.fields`/`.identity_fields`
  without Admin needing a second parallel tracking dict.
- Task 6's route factory builds `ResourceQuery.from_params(..., allowed_sort_fields=set(
  binding.service.data_source.fields), identity_fields=binding.service.data_source.identity_fields)`.

This is the only way Task 6 can call `ResourceQuery.from_params()` at all for an arbitrary
resource without inventing a second, separate field-declaration mechanism this plan never
asked for. Full field-level hiding/security (design section 13) remains explicitly future work.

## 12. Search scope, count-policy branches, and joined-count safety (Task 7)

**Search**: `ResourceQuery.search` (Task 2, merged) is a single `str | None` with no mode
selector (no exact/prefix/contains choice carried by the query itself, unlike sort/filter
which have explicit operators). Bounded decision: implement `contains`-only free-text search
in `0.1`, OR-combined across every field in `DataSource.fields` (the same whitelist Task 6
already wired up for sort -- reused here rather than inventing a second, separate
"searchable fields" concept this plan's tasks never ask for). Exact/prefix search modes and
per-field search configuration are deferred -- design section 15 lists them as directions, not
requirements, and nothing in Plan 02's task list adds a mode-selector to `ResourceQuery` or the
list UI.

**Count policies**: Task 4 (merged) implemented `CountPolicy.EXACT` only, by explicit
instruction, deferring `DEFERRED`/`DISABLED` to this task. Implement them now in
`SQLAlchemyDataSource.list()`:
- `DISABLED`: no count query at all; fetch `limit + 1` rows, `has_next = len(rows) > limit`,
  trim to `limit` before returning, `total_count = None`.
- `DEFERRED`: `list()` itself returns `total_count = None` and `has_next`/`has_previous` derived
  the same way as `DISABLED` (fetch `limit + 1`, since the point of DEFERRED is to avoid paying
  for a count on the initial page render) -- a *separate* count is fetched only when the
  dedicated `/{resource_path}/_count` HTMX route (added this task, `resources/_count.html`
  fragment) is hit, which runs the same EXACT count query Task 4 already built, reused as-is.

**Joined-resource count safety** ("Count joined resources by distinct identity or a derived
identity subquery; reject unsafe inference instead of returning a wrong total" -- plan Task 7
step 3): Plan 02 never adds relationship/join support to `SQLAlchemyDataSource` (relationship
editing is explicitly out of this plan's scope per the roadmap -- `ModelAdmin`'s "0.1 goal" of
complete relationship editing, design section 14, is a later plan's territory; Task 4/6/7's
`SQLAlchemyDataSource` only ever queries a single mapped table). Since no join-producing code
path exists anywhere in this plan's implementation, there is nothing for this safety rule to
guard against yet -- do not build speculative join-detection/rejection logic against a feature
that doesn't exist in this codebase. Note this explicitly as "not applicable -- no join support
exists in Plan 02" in the final summary rather than silently skipping it.

## 13. Typed filter coercion stays at the SQLAlchemy adapter boundary (Task 7 follow-up)

The public URL parser continues to produce backend-neutral `Filter` values from URL text, and
`ResourceQuery`/`ResourceService` remain ORM-neutral and type-agnostic. `SQLAlchemyDataSource`
coerces each filter value immediately before constructing the mapped-column predicate, using the
actual mapped SQLAlchemy column type. Statement construction precedes `session_factory()`, so an
invalid value becomes a stable `RakitError(code=validation.failed, status_code=400)` without
opening a session or exposing parser, driver, or SQLAlchemy details.

The bounded coercion rules are: string/text stays text; integer, finite float, finite `Decimal`
for `Numeric`, case-insensitive `true`/`false` only for boolean, ISO date, ISO datetime, UUID, and
SQLAlchemy Enum persisted values (including configured aliases and `values_callable`). A
timezone-aware `DateTime(timezone=True)` requires an aware ISO
datetime, while `DateTime(timezone=False)` requires a naive one. `IN` builds a new converted list
item-by-item (leaving the frozen query/filter input untouched); `is_null` preserves its existing
boolean semantics. `contains` is accepted only for mapped string/text types.

This is an open adapter boundary rather than a closed built-in-type switch: a custom SQLAlchemy
type may define `rakit_coerce_filter_value(value: str) -> object`. That explicit hook runs before
a `TypeDecorator`'s declared implementation fallback and should raise `ValueError`, `TypeError`,
or `ArithmeticError` for invalid input; the adapter converts those failures into the same safe
public error. No Python evaluation, imports, arbitrary constructors, SQLite affinity, or database
casts participate in conversion.

## 8. Static assets (Task 8)

Mount `StaticFiles` under the already-reserved `/_system` prefix (e.g. `/_system/static/...`)
so it can never collide with a `RouteDefinition`-validated path (reserved-prefix check already
rejects any resource/page from claiming `/_system/*`). Content hash: compute a short sha256
digest of each bundled asset file's bytes at import time in `rakit_web/assets.py`, expose a
`static_url(name: str) -> str` helper returning e.g. `/_system/static/rakit.<hash8>.css`, and
mount both the hashed and the underlying `StaticFiles` app so the hashed URL resolves.
Long-lived immutable cache headers on this mount only; dynamic admin pages keep `no-store`
(unaffected, different route).

Task 8 implementation records:

- HTMX is the byte-for-byte upstream `v2.0.10` distribution from commit `bdc7d7d`, licensed
  under 0BSD. The bundled provenance notice records the upstream tagged source/license URLs,
  SHA-256, and official-documentation-matching SHA-384 SRI value. The license and provenance
  files are package data in both wheel and sdist.
- Only content-hashed aliases are public. `ImmutableStaticFiles` translates a known hashed alias
  to the underlying packaged source file, adds the immutable cache policy, and rejects raw,
  missing, unknown, and traversal paths with controlled 404 responses.
- The Jinja `static_url` global prefixes ASGI `root_path` at render time, so the same local assets
  resolve both standalone and when Rakit is mounted (for example under FastAPI `/admin`). Resource
  detail/count URLs, search actions, and sort links use the same standard mount-path contract
  instead of outer-router route-name lookup, which cannot resolve child route names after mounting.

## 14. Example package naming, dependencies, and engine ownership (Task 8)

The plan file list's `examples/fastapi-sqlalchemy/` spelling conflicts with the executable import
contract `examples.fastapi_sqlalchemy.main`. Task 8 uses only the importable underscore package
`examples/fastapi_sqlalchemy/`; no redundant hyphenated duplicate exists.

The workspace root remains a non-buildable virtual workspace coordinator, preserving exactly the
eight official distributions under `packages/*`. Its optional `examples` extra declares FastAPI,
aiosqlite, uvicorn, and the workspace `rakit[sqlalchemy]` dependency. The repository-private
examples are intentionally imported by setting `PYTHONPATH` to the repository root for real CLI
commands (and the equivalent explicit test import path); they are not packaged as a ninth release
distribution. Both example READMEs document the PowerShell boundary.

The implemented public SQLAlchemy plugin accepts `session_factory`, not the design sketch's
future `engine=..., owned=False` form. The FastAPI example therefore creates the engine and
session factory in application code, passes only the public session-factory contract to Rakit,
and disposes the engine in the FastAPI lifespan. This preserves application ownership without
inventing a later-plan ownership API.

## 15. Canonical identities and deeply immutable query inputs (final review)

`RecordIdentity` stores a copied, recursively frozen mapping. UUID components are canonicalized
at this boundary to lowercase hyphenated strings, so a UUID obtained from a data source produces
the same stable JSON/token representation as the value decoded from its URL. The identity codec
turns malformed base64, malformed JSON, and wrong-shaped payloads into one controlled identity
decode error; raw decoder details are not part of the public contract.

`Filter.value` uses the same recursive freeze rules. Mappings become immutable copied mappings,
list-like values become tuples, and set-like values become immutable sets. `IN` values are always
stored as tuples. This prevents both caller aliasing and mutation through a frozen model while
preserving deterministic serialization and equality. Duplicate explicit sorts in the same
direction collapse to one entry; contradictory directions for one field are rejected.

The core package does not inspect ORM metadata. `SQLAlchemyDataSource` converts decoded identity
components to their mapped column types before opening a session or constructing a predicate.
Integer, string, and UUID identities therefore bind with their actual Python types under the
strict PostgreSQL dialect, and conversion failures become a stable public validation error.

## 16. Runtime-equivalent route collision rules (final review)

Route validation compares backend-neutral path segments, not only literal route strings. Static
and dynamic segments overlap when a real request could match both, regardless of placeholder
names, and conflicting routes are rejected per HTTP method during compilation. The built-in
`rakit.home` route is represented by a normal `RouteDefinition`, so a resource claiming `/` is
validated by the same mechanism instead of being silently shadowed.

One intentional router-priority case remains valid: static routes owned by a resource and
registered before that same resource's dynamic detail route (for example `/{path}/_count` before
`/{path}/{identity}`). Reversing that order, using different owners, or registering two dynamic
patterns remains a collision. This preserves the existing public count URL without weakening
cross-resource safety or changing the public URL contract.

## 17. Adapter ordering versus explicit UI sorting (final review)

Stable pagination is an adapter invariant. `SQLAlchemyDataSource.list()` appends every missing
identity column to the SQL `ORDER BY`, even when callers construct `ResourceQuery` directly, and
does not mutate the frozen query. An identity field already present in the explicit sort appears
only once. The rule applies uniformly to EXACT, DEFERRED, and DISABLED count policies.

Adapter-added/default identity ordering is deliberately not exposed as a selected user sort.
Templates derive selected state and `aria-sort` only from the explicit URL query: primary
ascending/descending sorts render `ascending`/`descending`, unsorted columns render `none`, and
additional sorted columns render `other`.

## 18. Safe query-state reconstruction and error rendering (final review)

Web controls rebuild query strings from the parsed, validated `ResourceQuery`, not from arbitrary
raw pairs. Sort links and search forms preserve repeated filters, relevant explicit sorting,
`per_page`, and count policy while dropping only `page`; malformed reconstruction is rejected as
a controlled client error. The same generated controls work standalone and through ASGI
`root_path` mounts.

The list route resolves the selected `_table.html` override once and passes that selection to both
the full page and HTMX fragment. Resource-specific and generic overrides therefore have identical
precedence in both paths. `is_null` accepts only case-insensitive `true` or `false`; all other
spellings fail before service/database execution. Every resource error response is `no-store`,
uses stable public text, and does not expose codec, Pydantic, driver, or SQLAlchemy details.

Generic free-text search excludes SQLAlchemy `Enum` columns. Enum values remain available through
the explicit typed-filter path, avoiding backend-dependent string-search behavior on PostgreSQL.

## 19. Executable README example contract (final review)

The README's primary example is an executable public-contract smoke test. It supplies a
`SecretValue` placeholder and all required `ModelAdmin` attributes (`resource_id`, `path`,
`label`, and `singular_label`). The test extracts that exact fenced block, substitutes only an
in-memory mapped model/engine fixture, executes it, and compiles the application without starting
the lifespan or connecting to a database. This keeps documentation drift visible without adding
a ninth distribution or any runtime/network side effect.

## 20. Fail-closed compiled resource field policy (external review round 2)

Every resource declares nonempty `list_fields` and `detail_fields`; `filter_fields`,
`search_fields`, and `sort_fields` default to empty. Registration copies those declarations into
an immutable backend-neutral `ResourceFieldPolicy`. Compilation validates the policy against the
associated datasource before accepting routes. The web layer uses the policy independently for
rendering and query controls, and adapters receive the same policy and enforce it again for direct
`ResourceQuery` callers. Identity fields remain valid internal ordering fields without becoming
displayed or user-queryable by implication.

Datasource validation is also a compile-time boundary: read capability, callable list/count/detail
operations, nonempty unique fields and identities, and known policy fields are required. Failures
use stable safe `config.invalid_resource_policy` or `config.invalid_datasource` errors.

## 21. SQLAlchemy mapped attributes and supported identities (external review round 2)

SQLAlchemy metadata exposes mapper attribute name, database column name, and column type as separate
values. All ORM expression lookup uses mapper attribute names from `mapper.column_attrs`; renamed
database columns are an internal persistence detail and never become API field names.

Plan 02 supports exactly one identity attribute whose effective type is Integer/BigInteger,
String-compatible, UUID, or a safe `TypeDecorator` wrapper around one of those types. Composite and
unsupported scalar identities fail adapter claim/registration with the distinct stable
`config.unsupported_identity` error instead of looking like an unmapped model.

## 22. Plan 02 public core facade (external review round 2)

`rakit.core` is the identity-preserving public facade for Plan 02's backend-neutral datasource,
identity, query, policy, and resource-service contracts. Importing it must not import optional
SQLAlchemy support. The facade is typed through the `rakit` distribution's `py.typed` marker and is
verified from an ordinary isolated wheel installation.

## 24. `ResourceQuery.identity_tie_breakers` (external review round 3)

`ResourceQuery.from_params(identity_fields=(...))`'s public composition contract conflicted with
the SQLAlchemy adapter's `sort_fields`-policy validation of `query.sorting`: an identity field
that is not itself user-sortable would fail policy validation purely because it had been folded
into `.sorting` as an internal tie-breaker. Fixed by adding a separate, immutable
`identity_tie_breakers: tuple[Sort, ...]` member to `ResourceQuery`. `from_params()` now records
tie-breakers there instead of merging them into `.sorting`; `.sorting` holds only explicit,
user-requested (and therefore policy-validated) sorting. `SQLAlchemyDataSource._validate_query_policy`
validates `.sorting` against `sort_fields` exactly as before (unaffected -- a directly constructed
explicit sort on an unlisted identity field is still rejected) and separately checks that every
`identity_tie_breakers` field names a real column (defence against an unchecked `getattr`), but
never against the `sort_fields` whitelist. `_effective_sorting` combines, in order and each only
if not already present: explicit `.sorting`, then `.identity_tie_breakers`, then the adapter's own
`self.identity_fields` invariant (unconditional, for queries built by direct `ResourceQuery(...)`
construction that never went through `from_params()` at all) -- so identity ordering is appended
after explicit sorting, appears exactly once, and is never exposed as selected UI sorting (the web
layer already derived selected-sort state from the URL/explicit `.sorting`, not from any merged
list, so no web-layer change was needed).

## 25. Effective-Python-type identity acceptance (external review round 3)

**Superseded by section 27 (round 4).** The round-3 fix below still correctly rejects Enum
identities, but its "trust the unwrapped `impl` when `python_type` raises `NotImplementedError`"
fallback, and its `rakit_identity_codec` custom-object opt-in, were both found to be fail-open in
round 4 and have been removed -- see section 27 for the corrected, narrower rule. This entry is
kept for history; do not implement anything described below as still current.

`sqlalchemy.Enum` is a `String` subclass, so `_validate_identity_type`'s `isinstance(type_,
String)` check wrongly accepted an Enum primary key -- its persisted Python value (an
`enum.Enum` member, or a plain string with no stable case mapping) cannot be encoded into a
`RecordIdentity`/URL token. Fixed by rejecting `Enum` unconditionally (both Python-Enum-backed
and plain-string-enum) before the base-type check, for both direct types and `TypeDecorator`-
unwrapped implementations. A `TypeDecorator` gets one further check: even when its `impl`
unwraps to a supported base type, an explicit `python_type` override to something other than
int/str/UUID (a genuine custom domain object, e.g. a `TypeDecorator[String]` returning a `Money`
value) is also rejected -- checked via the decorator's *own* effective `python_type` (a
`NotImplementedError` from an unoverridden `python_type` is treated as "no override claimed" and
falls back to trusting the unwrapped `impl`, since SQLAlchemy does not implicitly delegate
`TypeDecorator.python_type` to `impl`). A `TypeDecorator` may opt out of all of the above via an
explicit `rakit_identity_codec` attribute (mirroring `rakit_coerce_filter_value`'s shape, but a
distinct name and boundary) -- a deliberate, explicit contract for a genuine custom identity type,
never inferred. `_detail_statement`'s identity-value coercion was moved off the shared
`_coerce_filter_item` (which checks the *filter*-specific `rakit_coerce_filter_value` hook) onto a
new dedicated `_coerce_identity_component` (checks `rakit_identity_codec` instead), so identity
decoding has its own boundary rather than silently inheriting filter semantics.

## 26. Fail-closed `search_fields`/`filter_fields` semantics (external review round 3)

`SQLAlchemyDataSource._apply_search()` silently skipped any declared `search_fields` entry that
wasn't string-typed, so a policy like `search_fields=("id",)` for an integer column accepted
`?search=...` input but applied no predicate, returning the whole table -- indistinguishable from
"matched everything." Fixed by validating `search_fields`/`filter_fields` semantics once, at
`SQLAlchemyDataSource.__init__` (i.e. at adapter-claim/registration time, before any resource
compiles or serves a request): every `search_fields` entry must be string-typed (excluding
`Enum`, matching the existing search-vs-Enum exclusion); every `filter_fields` entry must have a
supported coercion path (the same type dispatch `_coerce_known_value` already handles, or an
explicit `rakit_coerce_filter_value` hook) -- anything else (e.g. `LargeBinary`) now fails
registration instead of only failing at the first request that happens to filter on it. A mixed
valid+invalid declaration rejects the whole policy (the first invalid field raises, nothing is
partially applied); a resource with no `search_fields` remains valid. `SQLAlchemyPlugin._claim`
catches the new `UnsupportedFieldPolicyError` and raises a stable `RakitError` (`config.
unsupported_field_policy`) naming only the resource/model/field/policy -- no SQL, column names,
or values.

## 23. Canonical accessible pagination URLs (external review round 2)

Previous and Next controls are ordinary full-page links inside a labelled pagination `nav`, with
the current page marked using `aria-current`. Unavailable links are omitted. URLs are reconstructed
only from the validated `ResourceQuery` and validated explicit sort sequence; they preserve repeated
filters, search, complete explicit multi-sort, bounded `per_page`, count policy, and ASGI
`root_path`, while changing only `page`. The same canonical serializer is used for deferred-count
URLs so rejected raw query parameters are never reflected into generated controls.

## 27. No custom identity domain objects in Plan 02; TypeDecorator identities require an
    explicit, exact int/str/UUID `python_type` (external review round 4 -- supersedes section 25)

Round 3's `rakit_identity_codec` opt-in and its "`NotImplementedError` from an unoverridden
`python_type` means trust the unwrapped `impl`" fallback were both fail-open: (a) the codec hook
was accepted whenever merely non-`None`, with no callable/shape validation, and only a decode
direction was ever wired through the datasource -- the web layer's `_identity_values()` still
only recognises already-int/str/UUID values, so an accepted custom-object identity produced an
empty `detail_url` with no encode path at all; (b) a `TypeDecorator` overriding only
`process_result_value()` (never `python_type`) hit the "no override claimed, trust `impl`"
branch and was silently accepted despite returning an un-encodable custom object -- exactly the
vulnerability the `python_type`-override check was supposed to catch.

Fixed per the reviewer's preferred bounded plan: **remove custom identity domain-object support
from Plan 02 entirely**, matching the approved v0.1 guarantee of int/string/UUID primary keys
with no larger custom-identity API invented in this plan. `rakit_identity_codec` is gone --
`_coerce_identity_component` no longer checks for it. A `TypeDecorator` now:
- must unwrap (`impl`) to a supported base type (`Integer`/`String`/`Uuid`, never `Enum`) --
  unchanged, defence in depth, not the sole check;
- **must explicitly declare `python_type`** -- a `NotImplementedError` (no override at all) is
  now rejected outright, never trusted via `impl`;
- is accepted only when that declared `python_type` is *exactly* `int`, `str`, or `UUID` (not a
  subclass, not a custom object).

A direct (non-decorator) type is unaffected: still `Integer`/`String`/`Uuid`, never `Enum`.
`SafeStringIdentity` (the existing "safe wrapper" test fixture) was updated to explicitly declare
`python_type -> str`, since an unoverridden decorator is no longer accepted by omission. If a
future plan wants genuine custom-identity-object support, it must implement a full bidirectional
codec (`encode(domain_value) -> int | str | UUID` and `decode(url_scalar) -> domain_value`)
propagated through both the datasource *and* the web layer's `_identity_values()`/detail-URL
construction, not a decode-only hook -- that is explicitly out of Plan 02's scope.

## 28. Identity tie-breakers are restricted to the datasource's actual identity fields, ascending,
    with no null-placement override (external review round 4)

Round 3 exempted `identity_tie_breakers` from the `sort_fields` whitelist entirely, checking only
that a tie-breaker's field was *some* known column on the model -- so a caller constructing
`ResourceQuery` directly could order by any known field, including a sensitive one (e.g.
`password_hash`), merely by placing it in `identity_tie_breakers` instead of `sorting`, bypassing
the whitelist meant to gate exactly that. "Exempt from the sort whitelist" was never meant to mean
"any known field" -- it was meant to mean "this datasource's own actual identity field(s)".

Fixed: `_validate_query_policy` now checks every `identity_tie_breakers` entry against
`self.identity_fields` (not `self.fields`), and additionally requires `direction is
SortDirection.ASC`, `nulls is NullPlacement.AUTO`, and no field named more than once within
`identity_tie_breakers` -- any tie-breaker failing any of these is rejected with the same stable
`validation.failed` / "Query field is not allowed" error as an unknown sort/filter field. The
adapter's own unconditional append of `self.identity_fields` in `_effective_sorting` (the
"adapter invariant" from section 17) is unchanged and still guarantees stable ordering even for a
`ResourceQuery` built without going through `from_params()` at all.

## 29. Explicit adapter hooks are validated as genuinely callable at claim time, not merely
    non-`None` (external review round 4)

`_is_filterable_type`'s `rakit_coerce_filter_value` check previously only tested `is not None`,
so a malformed declaration such as `rakit_coerce_filter_value = object()` passed registration and
only failed once a request actually tried to filter on that field (`_coerce_filter_item`'s own
`callable(...)` check already existed at *that* layer, but registration-time validation didn't
mirror it). Fixed: `_is_filterable_type` now checks `callable(custom_coercer)`, not merely
`custom_coercer is not None` -- a non-callable hook fails claim/registration with the same
`config.unsupported_field_policy` error as any other unsupported `filter_fields` declaration,
before any resource compiles or serves a request. Since section 27 removes the identity codec
hook entirely, there is no analogous identity-side hook left to validate.
