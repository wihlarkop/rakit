# Changelog

All notable user-facing changes to Rakit are recorded here.

The project follows Semantic Versioning. Until a release is actually tagged, changes stay under
`Unreleased`; the maintainer assigns the final version/date at release time.

## [Unreleased]

### Added

- Initial Rakit framework implementation across runtime/compiler, resources, SQLAlchemy,
  authentication/RBAC, forms and writes, relationships, actions, pages, endpoints, dashboards,
  local storage, themes, accessibility, server adapters, reusable adapter contract suites, official
  examples, documentation, governance, and verification tooling.
- A complete UI maturity pass covering the application shell, design tokens, reusable components,
  resource list/detail/form flows, bulk and action workflows, relationships/uploads, auth/system
  surfaces, custom pages, responsive behavior, keyboard/accessibility hardening, and final visual
  polish.
- Granian as an explicit optional server adapter alongside Uvicorn.
- User-facing adapter facades including `rakit.server.granian`, neutral `rakit.storage`, and
  `rakit.storage.local` while keeping implementation distributions independently installable.
- Release-level integration/security regressions and clean-artifact verification foundations.
- Reproducible generated-CSS verification and broader installed-artifact checks for bundled web
  runtime assets and optional server adapters.
- A documented `rakit_` namespace invariant for framework-owned persistence and independent Rakit
  migration version tables.
- A realistic `examples/reference_app` that composes SQLAlchemy persistence, built-in auth/RBAC,
  optimistic CRUD, relationships, private uploads, filters/search, record and bulk actions, custom
  pages, dashboard widgets, generated REST reads, lifecycle bootstrap, and readiness through public
  Rakit APIs.
- Public startup lifecycle callbacks that run fail-fast before the runtime enters `READY`.
- Public operational SQLAlchemy-auth facade exports for auth schema bootstrap, users, roles,
  permissions, password hashing, permission synchronization, and durable idempotency storage.
- Public domain-action composition exports and a high-level `Admin.register_write(...)` helper for
  enabling ordinary resource write forms without constructing transport-level bindings.
- Declarative ordinary CRUD through `ResourceWriteDefinition` on `ModelAdmin`, with adapter-owned
  write-service materialization, an explicit writable-field allowlist, read-only-by-default
  semantics, and fail-closed capability checks. SQLAlchemy now supplies the first write-service
  provider for this neutral contract.
- Friendly lifecycle composition through `Admin.on_startup(...)`, `Admin.on_shutdown(...)`, and
  `Admin.add_health_check(...)`, delegating to the existing lifecycle manager without changing
  startup, readiness, or shutdown semantics.
- `rakit init` project scaffolding for new and existing applications, with interactive and
  deterministic non-interactive flows, `standard` and `minimal` starters, Uvicorn/Granian choices,
  `uv`-based dependency guidance, safe dry-runs, additive existing-project integration, and
  generated starters that use the current declarative CRUD/lifecycle APIs.
- A typed internal installation vocabulary shared by optional-dependency diagnostics and `rakit init`,
  producing deterministic `uv add` guidance for Rakit extras while keeping application-owned
  packages such as database drivers explicit.
- Capability-specific missing-dependency errors for SQLAlchemy, SQLAlchemy authentication, local
  storage, Uvicorn, and Granian facades without masking transitive `ModuleNotFoundError` failures.
- Capability discovery through `rakit capabilities`, with separate configured-application and
  installed-environment views, deterministic human-readable output, JSON schema version 1, strict
  `rakit.integrations` entry-point validation, and lightweight first-party discovery metadata for
  web, schema, persistence, authentication, storage, Uvicorn, and Granian integrations.
- Tag-gated trusted-publishing workflow preparation without a release tag or publish action.

### Changed

- Optional capability installation is normalized to exactly six public extras: `uvicorn`, `granian`,
  `sqlalchemy`, `auth-sqlalchemy`, `storage-local`, and `standard`. The `standard` bundle is now
  server-neutral and database-driver-neutral, server choice stays explicit, and the unpublished
  `server-uvicorn` alias has been removed.
- Standard scaffolds now select `rakit[standard,uvicorn]` or `rakit[standard,granian]` explicitly and
  keep `aiosqlite` as a separate application dependency instead of hiding either server or driver
  selection inside the `standard` extra.
- Capability validation now evaluates the complete configured requirement graph before failing, so
  `rakit check` reports every missing capability requirement in one run while remaining fail-closed.
  Installed integration metadata never implies configured or active application state.
- Missing first-party server adapter guidance now reuses the canonical typed installation vocabulary
  and emits `uv add` commands instead of maintaining separate package-install strings.
- Official examples prefer the `rakit` facade for public contracts and adapters instead of importing
  implementation packages directly when an ergonomic facade exists.
- Reference application bootstrap is additive and application-owned; Rakit continues to keep ORM
  models, domain transitions, database-driver selection, and application migration policy outside
  the framework core.
- The reference application now uses one-call declarative resource registration for ordinary
  Product and Order CRUD plus the public lifecycle facade, removing application-level mutation
  service/token boilerplate while retaining explicit forms, writable fields, concurrency, and
  permissions.
- SQLAlchemy Core now provides native `Table`-based persistence capability parity for scoped
  relationships, root-unit-of-work graph writes, and atomic optimistic concurrency without ORM
  model emulation.

### Security

- Fail-closed configuration, host/proxy, CSRF, permission re-check, concurrency, idempotency,
  confirmation, upload/path, private-file, production-error, and shutdown/readiness verification
  gates.
- Project scaffolding fails closed on conflicting generated files, unmanaged content in a new-project
  target, ambiguous existing-package placement, and missing `uv` before requested dependency
  installation; dry-run performs no filesystem mutation or dependency subprocess.
