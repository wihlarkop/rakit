# Phase B Reference Application & DX Hardening Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. Rakit project workflow for this plan is source/feature first, non-test verification second, regression/unit tests last.

**Goal:** Complete Phase B by building a realistic public-API-only reference application and fixing the concrete API/DX friction it exposes.

**Architecture:** Add a multi-file commerce-operations reference app backed by async SQLAlchemy SQLite, built-in SQLAlchemy auth, local private storage, dashboard widgets, actions, relationships, and generated REST. Keep framework changes narrow: extend the existing `rakit.auth.sqlalchemy` facade so persistent auth can be bootstrapped without importing implementation-package internals.

**Tech Stack:** Python 3.12+, Rakit public facade packages, SQLAlchemy async, aiosqlite, Argon2, Starlette/ASGI via Rakit, local private storage, pytest/ruff/ty/MkDocs for final verification.

**Spec:** `docs/superpowers/specs/2026-08-21-phase-b-reference-app-hardening-design.md`

## Global Constraints

- Do not create a release, tag, TestPyPI/PyPI upload, or version bump.
- `examples/reference_app` may import Rakit only through `rakit.*` public namespaces.
- Preserve existing physical package boundaries.
- Do not add new framework abstractions unless reference-app pressure demonstrates a reusable need.
- Implement source/features before adding regression tests.
- Perform structural/manual non-test verification before writing tests.
- Development `create_all` bootstrap must be clearly documented as non-production behavior.
- Seed/bootstrap must be idempotent and must not destroy an existing database.

---

### Task 1: Public SQLAlchemy-auth operational facade

**Files:**
- Modify: `packages/rakit/src/rakit/auth/sqlalchemy.py`
- Modify: `docs/guides/authentication.md`

**Produces:** public imports for auth schema/models/password hashing/permission synchronization required by the reference app.

- [ ] Expand `rakit.auth.sqlalchemy` to export:
  - `AuthBase` aliasing `rakit_auth_sqlalchemy.models.Base`.
  - `User`, `Role`, `Permission`.
  - `Argon2PasswordHasher`.
  - `PermissionSyncResult`, `sync_permissions`.
  - existing `SQLAlchemyAuthPlugin`, `SQLAlchemyIdempotencyStore`.
- [ ] Keep optional-dependency failure routed through the existing `optional_import(..., extra="auth-sqlalchemy")` guard.
- [ ] Update `__all__` to match the public facade exactly.
- [ ] Update the authentication guide with a short operational bootstrap snippet and a production-migrations caveat.
- [ ] Review the facade for import-time side effects and dependency-boundary regressions.

### Task 2: Reference-app data model and persistence bootstrap

**Files:**
- Create: `examples/reference_app/__init__.py`
- Create: `examples/reference_app/models.py`
- Create: `examples/reference_app/database.py`

**Produces:** application-owned SQLAlchemy schema, async engine/session factory, and idempotent development bootstrap.

- [ ] Define `Base`, `Customer`, `Product`, `Order`, and `OrderItem` in `models.py` with explicit `reference_*` table names.
- [ ] Use normal SQLAlchemy relationships between customer/orders and order/order-items/product.
- [ ] Store product image metadata in a type that the current SQLAlchemy/Rakit file-field pipeline can persist honestly; if the adapter requires JSON/descriptors, use the existing supported representation rather than inventing serialization.
- [ ] Create an async SQLite engine targeting `.rakit-reference/reference.sqlite3` and an `async_sessionmaker` in `database.py`.
- [ ] Implement `bootstrap_database(admin)` which:
  - creates `.rakit-reference`.
  - creates application and `AuthBase` metadata tables if absent.
  - compiles the admin and generates its permission catalogue through `rakit.core.generate_permission_catalogue`.
  - calls public `sync_permissions`.
  - seeds deterministic customer/product/order/order-item rows only if absent.
  - hashes `rakit-demo-password` with public `Argon2PasswordHasher`.
  - seeds `admin@example.com` as superuser.
  - seeds `operator@example.com` as non-superuser.
  - creates/loads an `operations` role and grants a limited non-empty subset of generated permissions.
  - commits without deleting pre-existing user data.
- [ ] Implement `dispose_database()` for explicit engine cleanup.
- [ ] Review bootstrap transaction boundaries and rerun-safety manually.

### Task 3: Reference-app resources, filters, relationships, generated REST, and actions

**Files:**
- Create: `examples/reference_app/resources.py`

**Produces:** the core backoffice resource surface.

- [ ] Define `CustomerAdmin`, `ProductAdmin`, `OrderAdmin`, and `OrderItemAdmin` as `ModelAdmin` classes.
- [ ] Configure useful list/detail/filter/search/sort fields for each model.
- [ ] Add `ResourceApiDefinition` to customers/products/orders using only operations honestly supported by the current generated executor.
- [ ] Declare order→customer, order→items, order-item→order, and order-item→product relationships using public `RelationshipDefinition` contracts where SQLAlchemy relationship validation supports them.
- [ ] Configure product image upload using the current public `FileField`/presentation hooks if supported by the ModelAdmin form compiler. If the current public declaration surface cannot attach a file field to an otherwise inferred SQLAlchemy schema without internal imports, record that as B4 friction and implement the smallest reusable public hook before continuing.
- [ ] Add a deterministic record action for orders (`mark_paid`) and bulk action (`mark_processing`) through existing public action contracts.
- [ ] Define safe auth resource admins for public `User`, `Role`, and `Permission` models; never expose `password_hash`, sessions, or idempotency records.
- [ ] Review permission catalogue implications and ensure action/resource identifiers are stable.

### Task 4: Dashboard, custom operations page, storage, and application composition

**Files:**
- Create: `examples/reference_app/dashboard.py`
- Create: `examples/reference_app/main.py`

**Produces:** runnable authenticated ASGI application with dashboard, custom page, and local storage.

- [ ] In `dashboard.py`, implement SQLAlchemy-backed widget loaders for total customers, low-stock products, pending/processing orders, and recent orders.
- [ ] Add `register_dashboard(admin)` that registers widgets and a `main` `DashboardDefinition`.
- [ ] In `main.py`, instantiate `SQLAlchemyAuthPlugin(session_factory)` and pass its backend/session store into `Admin`.
- [ ] Install `SQLAlchemyPlugin(session_factory=session_factory)`.
- [ ] Register `LocalStoragePlugin` with a `product_images` private store under `.rakit-reference/uploads/products`.
- [ ] Register all resource admins.
- [ ] Register dashboard widgets/dashboard.
- [ ] Register `/operations` through `PageDefinition` with a server-rendered `PageResult`.
- [ ] Add a Starlette/ASGI lifespan wrapper if required so `bootstrap_database(admin)` runs before serving requests and `dispose_database()` runs on shutdown without bypassing Rakit's lifecycle.
- [ ] Export both `admin` and runnable `app`.
- [ ] Ensure the module works with `rakit check`, `rakit routes`, and the normal server adapter.

### Task 5: Reference-app operator documentation

**Files:**
- Create: `examples/reference_app/README.md`
- Modify: `README.md`

**Produces:** exact setup/run/login/inspection instructions.

- [ ] Document installation from the repository workspace.
- [ ] Document run command using `uv run rakit run examples.reference_app.main:admin` if the Admin lifecycle is sufficient; otherwise document the ASGI target required by the final composition.
- [ ] Document both deterministic development accounts.
- [ ] Document `.rakit-reference` persistence and how to reset it intentionally.
- [ ] State clearly that metadata `create_all` bootstrap is demo-only and production uses migrations.
- [ ] Show `rakit check` and `rakit routes` commands.
- [ ] Explain which framework capabilities the example demonstrates.
- [ ] Add the reference app to the root README examples/discovery section without turning the README into a duplicate guide.

### Task 6: Non-test verification and DX pressure review

**Files:**
- Modify only source/docs files when verification reveals a concrete issue.

**Produces:** source-complete Phase B implementation before test additions.

- [ ] Run/import-compile review over all new Python modules.
- [ ] Run Ruff formatter/linter and `ty` on changed source.
- [ ] Compile `examples.reference_app.main:admin`.
- [ ] Run `rakit check examples.reference_app.main:admin`.
- [ ] Run `rakit routes examples.reference_app.main:admin` and inspect auth/resource/page/generated REST routes.
- [ ] Bootstrap twice and verify no duplicate baseline data/accounts/roles.
- [ ] Authenticate both seeded accounts using the configured auth backend.
- [ ] Query relationships and role grants directly through SQLAlchemy.
- [ ] Confirm storage roots are created under `.rakit-reference` only.
- [ ] Audit every Rakit import under `examples/reference_app` for the public-namespace rule.
- [ ] If any verification failure exposes reusable DX friction, fix the framework in the smallest public surface possible, re-run the non-test checks, and document the change in the plan notes/PR.

### Task 7: Regression tests after source verification

**Files:**
- Create: `tests/examples/test_reference_app.py`
- Modify/Create focused auth facade tests in the existing package/facade test location discovered during implementation.

**Produces:** regression coverage for the completed source behavior.

- [ ] Add a facade test asserting every intended `rakit.auth.sqlalchemy` export resolves with the optional dependency installed.
- [ ] Add an AST/import-policy test ensuring reference-app Rakit imports use only approved `rakit.*` namespaces.
- [ ] Add reference-app compile/route smoke coverage.
- [ ] Add isolated temporary-directory bootstrap test by making the example's runtime root injectable/configurable through a small public example helper or environment variable if needed; do not monkeypatch framework internals.
- [ ] Assert bootstrap twice is idempotent.
- [ ] Assert both seeded accounts authenticate.
- [ ] Assert the operator has a limited, non-empty permission set and is not a superuser.
- [ ] Assert representative dashboard loaders return the expected widget result types.
- [ ] Keep tests network-free and deterministic.

### Task 8: Phase B closure docs and full quality gate

**Files:**
- Modify: `docs/roadmap.md`
- Modify: `CHANGELOG.md`

**Produces:** completed Phase B with truthful public status and no release action.

- [ ] Mark B2.7 complete because the superseded stale branches are no longer present.
- [ ] Mark B3 complete.
- [ ] Mark B4 complete and summarize only the DX fixes actually implemented.
- [ ] Set the current-position table's next major workstream to Phase C.
- [ ] Add the reference app and auth operational-facade improvement under `CHANGELOG.md` → `Unreleased`.
- [ ] Run `bun run css:build` and verify no diff if docs/source additions contain utility-looking text outside the scoped Rakit web source tree.
- [ ] Run `uv run ruff format --check .`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run ty check`.
- [ ] Run `uv run pytest`.
- [ ] Run `uv run pytest --cov`.
- [ ] Run `uv run mkdocs build --strict`.
- [ ] Run `uv run python scripts/check_artifacts.py`.
- [ ] Run release-test/artifact dry-run coverage through CI.
- [ ] Open a PR from `phase-b-reference-app-hardening` to `main` and require the full Python 3.12/3.13/3.14 + lowest/latest + artifact + CSS reproducibility gates to pass.
- [ ] Merge only after the final head is fully green.
- [ ] Do not tag or publish a release.
