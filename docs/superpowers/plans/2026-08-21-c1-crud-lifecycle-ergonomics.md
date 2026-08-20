# C1 Friendly CRUD and Lifecycle Ergonomics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. This repository's maintainer workflow for C1 is source-first: implementation and non-test verification precede new regression tests.

**Goal:** Make ordinary model CRUD and application lifecycle composition substantially less repetitive while preserving explicit write policy, adapter ownership, authorization, concurrency, and fail-closed behavior.

**Architecture:** `ResourceWriteDefinition` is a neutral opt-in declaration on `ResourceAdmin`; the adapter runtime may expose a write-service provider that materializes the existing mutation service. `Admin.register(...)` reuses the existing secure `register_write(...)` pipeline. Thin lifecycle methods delegate to the existing `LifecycleManager` rather than creating a second lifecycle system.

**Tech Stack:** Python 3.12+, Pydantic/FormSchema contracts, Starlette web runtime, SQLAlchemy async adapter, pytest, Ruff, ty, MkDocs.

**Spec:** `docs/superpowers/specs/2026-08-21-c1-crud-lifecycle-ergonomics-design.md`

## Global Constraints

- Preserve source-first workflow: source implementation first, non-test verification second, new regression tests last.
- Read registration must never imply write capability; `write = None` remains the default.
- No automatic ORM-to-form generation.
- Writable fields remain explicitly declared.
- Existing `Admin.register_write(...)` and `Admin.register_write_resource(...)` remain supported.
- Unsupported write capability fails closed; never silently downgrade to read-only.
- No tag, release, version bump, TestPyPI, or PyPI action.
- `docs/roadmap.md` moves C1 to Complete only after final verification; C2 becomes Next.

---

### Task 1: Neutral write declaration and adapter runtime contract

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/admin_types.py`
- Modify: `packages/rakit-core/src/rakit_core/generated_runtime.py`
- Modify: `packages/rakit-core/src/rakit_core/__init__.py` if package exports require it
- Modify: `packages/rakit/src/rakit/__init__.py`
- Modify: `packages/rakit/src/rakit/core.py` if the core facade mirrors the new contract

**Produces:**
- `ResourceWriteDefinition`
- `ResourceAdmin.write: ResourceWriteDefinition | None`
- `ResourceWriteServiceContext`
- `ResourceWriteServiceProvider`
- `ResourceAdapterRuntime.write_service_provider`

- [ ] Add frozen `ResourceWriteDefinition` with `form_schema`, explicit `writable_fields`, optional `version_field`, optional `success_message`, and HTMX refresh targets.
- [ ] Add declaration validation that rejects empty/duplicate/unknown/non-writable fields and malformed version/refresh values.
- [ ] Add the write-provider context/protocol and optional provider slot on `ResourceAdapterRuntime` without changing existing adapter behavior.
- [ ] Export the new public declaration from `rakit` and relevant core facades.
- [ ] Review dependency direction: `rakit-core` must not import `rakit-web` or SQLAlchemy.
- [ ] Commit source contract changes.

### Task 2: SQLAlchemy write service provider

**Files:**
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/write_provider.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/plugin.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/__init__.py` only if a direct implementation export is useful

**Consumes:**
- `ResourceWriteServiceContext`
- `ResourceWriteDefinition`

**Produces:**
- `SQLAlchemyWriteServiceProvider`
- claimed SQLAlchemy runtimes that can materialize ordinary CRUD mutation services

- [ ] Implement provider bound to `model` and `async_sessionmaker`.
- [ ] Derive the single identity field from `inspect_model(model)` rather than requiring application duplication.
- [ ] Build `SQLAlchemyMutationService` using the declaration's form schema, explicit writable fields, version field, canonical resource id, and Admin token service.
- [ ] Derive delete and force-overwrite permission strings from `admin_id` and `resource_id`.
- [ ] Attach the provider to `ResourceAdapterRuntime` returned by `SQLAlchemyPlugin._claim(...)`.
- [ ] Ensure read-only SQLAlchemy claims remain behaviorally unchanged.
- [ ] Commit adapter source changes.

### Task 3: Declarative write composition in `Admin.register`

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Modify: `packages/rakit-web/src/rakit_web/form_routes.py` only if structural mutation-service validation should share a helper/protocol

**Consumes:**
- `ResourceAdmin.write`
- selected `ResourceAdapterRuntime.write_service_provider`

**Produces:**
- one-call resource registration for explicitly mutable model resources

- [ ] Capture the selected adapter runtime during normal `Admin.register(...)` model claim.
- [ ] After canonical read/resource registration succeeds, inspect the explicit write declaration.
- [ ] If no write declaration exists, preserve current behavior exactly.
- [ ] If write is declared, require a provider and the existing auth/secret prerequisites.
- [ ] Build the canonical token service from Admin's configured secret and admin id.
- [ ] Ask the provider to build the mutation service and validate that it satisfies the write-route service shape.
- [ ] Reuse `Admin.register_write(...)` with the declaration's form schema, success message, and refresh targets.
- [ ] Preserve duplicate-binding and post-compilation guards.
- [ ] Keep manual `register_write(...)` as the advanced path.
- [ ] Commit web composition source changes.

### Task 4: Friendly lifecycle facade

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/admin.py`

**Produces:**
- `Admin.on_startup(...)`
- `Admin.on_shutdown(...)`
- `Admin.add_health_check(...)`

- [ ] Add `on_startup` that delegates to `LifecycleManager.register_starting_callback` and returns the callback unchanged.
- [ ] Add `on_shutdown` that delegates to `LifecycleManager.register_stopping_callback` and returns the callback unchanged.
- [ ] Add `add_health_check` that mirrors the lifecycle health-check options and delegates without changing validation/caching/readiness semantics.
- [ ] Do not remove or hide `admin.lifecycle`.
- [ ] Commit lifecycle facade source changes.

### Task 5: Migrate the realistic reference application

**Files:**
- Modify: `examples/reference_app/resources.py`
- Modify: `examples/reference_app/app.py`
- Modify: `examples/reference_app/README.md`

**Produces:**
- reference app using the C1 declarative path end-to-end

- [ ] Move Product and Order write policy into `ProductAdmin.write` and `OrderAdmin.write`.
- [ ] Remove the application-level `TokenService` created only for ordinary resource mutation services.
- [ ] Remove `product_mutations(...)` / `order_mutations(...)` factory boilerplate.
- [ ] Remove separate `admin.register_write(...)` calls.
- [ ] Replace direct lifecycle-manager registration with `admin.on_startup`, `admin.add_health_check`, and `admin.on_shutdown`.
- [ ] Update README examples and ownership explanation.
- [ ] Commit reference-app migration.

### Task 6: Non-test verification and manual review

**Files:**
- No new regression-test files yet.

- [ ] Review every changed source file for dependency-direction violations and accidental adapter leakage into core.
- [ ] Confirm the reference app has exactly one resource-registration path and no second mutation-token service.
- [ ] Confirm explicit writable fields remain present in source declarations.
- [ ] Confirm read-only Customer and OrderItem resources do not acquire write declarations.
- [ ] Check import/export surfaces and `__all__` declarations.
- [ ] Run or use repository automation for Ruff formatting/lint and `ty` without adding new tests.
- [ ] Fix all source/type/lint findings before regression-test work.

### Task 7: Add focused regression coverage

**Files:**
- Modify/Create: `packages/rakit-core/tests/test_admin_types.py` or a focused new write-definition test module following current conventions
- Modify/Create: `packages/rakit-web/tests/test_public_write_composition.py`
- Modify/Create: `packages/rakit-web/tests/test_lifecycle_startup_callbacks.py` or focused lifecycle facade tests
- Modify/Create: `packages/rakit-sqlalchemy/tests/test_plugin.py` / focused write-provider tests
- Modify: `tests/test_reference_app.py`
- Modify: `packages/rakit/tests/test_facade.py` or focused C1 facade tests

- [ ] Cover valid and invalid `ResourceWriteDefinition` declarations.
- [ ] Prove read-only resources remain read-only.
- [ ] Prove an explicit write declaration is materialized through a provider and existing secure binding.
- [ ] Prove a missing provider fails closed.
- [ ] Prove SQLAlchemy derives identity and canonical delete/force-overwrite permissions.
- [ ] Prove manual `register_write(...)` remains compatible.
- [ ] Prove lifecycle facade methods preserve fail-fast startup, LIFO shutdown, and health-check semantics.
- [ ] Update the reference-app smoke test so it proves the declarative path produces write routes and readiness.
- [ ] Run focused tests and fix behavior rather than weakening assertions when a real bug is exposed.

### Task 8: C1 documentation closure and full quality gates

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`
- Modify additional user docs only where the public API needs explanation

- [ ] Document the declarative CRUD/lifecycle ergonomics under `[Unreleased]`.
- [ ] Mark C1 Complete and C2 Next in the roadmap only after focused verification is green.
- [ ] Run full Python 3.12/3.13/3.14 test matrix.
- [ ] Run lowest-direct and latest dependency matrices.
- [ ] Run Ruff format/check and `ty`.
- [ ] Run `pytest --cov`.
- [ ] Run `mkdocs build --strict`.
- [ ] Run artifact checker and artifact dry-run.
- [ ] Run generated web asset reproducibility gate.
- [ ] Open/update the C1 integration PR with exact final-head verification evidence.
- [ ] Do not merge without explicit maintainer instruction unless the maintainer has already instructed that this phase should be executed and merged after green CI.
