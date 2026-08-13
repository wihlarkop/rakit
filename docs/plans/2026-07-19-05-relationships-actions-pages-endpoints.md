# Rakit Relationships, Actions, Pages, and Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement complete relationship editing, unified record/resource/bulk actions, custom internal pages, and secure typed JSON endpoints.

**Architecture:** Relationship and action changes compile into typed plans that reuse the write pipeline. Pages and endpoints are framework-neutral definitions translated by `rakit-web` into HTML, HTMX, or JSON.

**Tech Stack:** SQLAlchemy 2.x, Pydantic v2, Starlette, Jinja2, HTMX.

## Global Constraints

- All relationship mutations are atomic with the parent resource operation.
- Relationship queries use the same scoped base query as list/detail/update/delete.
- Nested edit depth defaults to one; cycles are validated.
- Action availability is rechecked on POST and is never authorization.
- Bulk actions default to atomic behavior and enforce synchronous safety limits.
- Custom endpoints are not generated REST APIs.
- Session-authenticated POST endpoints require CSRF and idempotency.

---

## Approved implementation decisions

The following decisions were approved before implementation and refine this
plan without expanding its scope.

1. **Generalized operation execution.** `rakit-core` owns a small,
   backend-neutral operation-plan/execution seam for non-CRUD operations. It
   reuses `OperationContext`, exact authorization capabilities, unit-of-work
   policy, deadlines, operation-scoped services/events, concurrency, and
   idempotency where applicable. It does not introduce action-, page-,
   endpoint-, or bulk-specific contexts, transaction engines, or an untyped
   universal result. `MutationResult` remains CRUD-specific.
2. **Relationship permissions.** Relationship mutations use the parent
   resource update permission unless a relationship explicitly provides a
   `PermissionRequirement`. Target visibility remains scoped independently.
   Unlinking is distinct from deleting a child. Child deletion, delete-orphan,
   or destructive cascades require explicit relationship metadata, strong
   confirmation, and the target resource's scoped delete authorization when
   the target is a registered resource; unresolved destructive authorization
   fails during compilation.
3. **Bulk concurrency snapshot.** Preview/confirmation binds a deterministic
   digest of the canonical ordered target resource identities, record
   identities, and concurrency versions. The signed identity also binds the
   admin, principal/session, action, selection mode and fingerprint, digest,
   count, issued time, expiry, and nonce. Execution re-resolves scoped targets
   and requires an exact digest match before it runs. Bulk is atomic by
   default; best effort is explicit, savepoint-backed, and subject to the
   same limits: confirmation above 25 targets and rejection above 1,000
   synchronous targets.
4. **Route conventions.** Framework-owned resource routes reserve static
   `_relationships` and `_actions` segments beneath the existing collection
   and record routes. Explicit page and endpoint paths are compiled before
   serving. All route ownership and collisions, including `/auth` and
   `/_system`, fail during compilation.
5. **Association objects.** Plan 05 supports normal to-one/to-many
   relationships, unambiguous SQLAlchemy secondary many-to-many mappings, and
   mapped association objects only when the association mapper has a supported
   canonical identity, unambiguous parent and target sides, explicitly
   declared editable scalar association fields, and deterministic persistence
   semantics. Ambiguous joins, unsupported polymorphism, nested association
   relationships, dynamic/write-only/view-only unsupported forms, and unsafe
   identities fail during compilation.

---

### Task 1: Define relationship metadata and SQLAlchemy introspection

**Files:**
- Create: `packages/rakit-core/src/rakit_core/relationships.py`
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/relationships.py`
- Test: `packages/rakit-sqlalchemy/tests/test_relationship_introspection.py`

**Interfaces:**
- Produces: `RelationshipDefinition`, `RelationshipKind`, `RelationshipEditMode`.
- Consumes: SQLAlchemy mapper relationships.

- [ ] **Step 1: Write classification tests**

```python
def test_mapper_relationships_are_classified(model_graph) -> None:
    definitions = inspect_relationships(model_graph.Order)
    assert definitions["customer"].kind == RelationshipKind.MANY_TO_ONE
    assert definitions["profile"].kind == RelationshipKind.ONE_TO_ONE
    assert definitions["items"].kind == RelationshipKind.ONE_TO_MANY
    assert definitions["tags"].kind == RelationshipKind.MANY_TO_MANY
    assert definitions["parent"].self_referential is True
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest packages/rakit-sqlalchemy/tests/test_relationship_introspection.py -v
```

Expected: missing relationship system.

- [ ] **Step 3: Implement relationship contracts**

```python
class RelationshipKind(StrEnum):
    MANY_TO_ONE = "many_to_one"
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_MANY = "many_to_many"
    ASSOCIATION_OBJECT = "association_object"


class RelationshipEditMode(StrEnum):
    LINK = "link"
    INLINE = "inline"
    NESTED = "nested"
    READ_ONLY = "read_only"
    HIDDEN = "hidden"
```

`RelationshipDefinition` includes stable ID, source/target resource, kind, nullable, ordered, association fields, self-reference, edit mode, permissions, loading strategy, record label resolver, and `max_nested_depth=1`. Compilation rejects ambiguous or unsupported identity mappings.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/rakit-sqlalchemy/tests/test_relationship_introspection.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/rakit-core packages/rakit-sqlalchemy
git commit -m "feat: introspect resource relationships"
```

### Task 2: Add atomic relationship mutation plans

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/relationships.py`
- Modify: `packages/rakit-core/src/rakit_core/mutations.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/relationships.py`
- Test: `packages/rakit-sqlalchemy/tests/test_relationship_mutations.py`

**Interfaces:**
- Produces: `RelationshipMutationPlan`, link/unlink/create/update/delete/reorder operations.
- Consumes: parent mutation plan and UoW.

- [ ] **Step 1: Write atomic graph tests**

```python
@pytest.mark.anyio
async def test_parent_and_children_commit_atomically(service, order) -> None:
    await service.update(
        order.id,
        scalar_changes={"status": "confirmed"},
        relationship_changes={
            "items": [
                {"operation": "create", "values": {"sku": "A", "quantity": 2}},
                {"operation": "create", "values": {"sku": "B", "quantity": 1}},
            ]
        },
    )
    loaded = await service.load(order.id)
    assert loaded.status == "confirmed"
    assert [(item.sku, item.quantity) for item in loaded.items] == [("A", 2), ("B", 1)]


@pytest.mark.anyio
async def test_invalid_child_rolls_back_parent(service, order) -> None:
    with pytest.raises(RakitError):
        await service.update(
            order.id,
            scalar_changes={"status": "confirmed"},
            relationship_changes={
                "items": [{"operation": "create", "values": {"quantity": -1}}]
            },
        )
    assert (await service.load(order.id)).status != "confirmed"
```

- [ ] **Step 2: Verify failure**

Expected: child mutations are unsupported or non-atomic.

- [ ] **Step 3: Implement plan execution**

Support set/clear to-one, link/unlink many-to-many, create/update/unlink/delete one-to-many, association-object fields, and reordering. Validate nested depth, cycles, per-operation permissions, target visibility, related-record concurrency, and cascade impacts. Execute all changes inside the parent UoW and never commit in hooks.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/rakit-sqlalchemy/tests/test_relationship_mutations.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/rakit-core packages/rakit-sqlalchemy
git commit -m "feat: add atomic relationship mutations"
```

### Task 3: Render relationship editors and autocomplete

**Files:**
- Create: `packages/rakit-web/src/rakit_web/relationship_routes.py`
- Create: `packages/rakit-web/src/rakit_web/templates/relationships/to_one.html`
- Create: `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- Create: `packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html`
- Test: `packages/rakit-web/tests/test_relationship_ui.py`

**Interfaces:**
- Produces: scoped autocomplete, chips, inline rows, relationship pagination.
- Consumes: relationship definitions, form state, mutation plans.

- [ ] **Step 1: Write scoping and state-preservation tests**

```python
@pytest.mark.anyio
async def test_autocomplete_uses_scoped_target_query(client) -> None:
    response = await client.get(
        "/orders/relationships/customer/options?q=ada",
        headers={"HX-Request": "true"},
    )
    assert "Ada" in response.text
    assert "Forbidden Customer" not in response.text


@pytest.mark.anyio
async def test_relationship_pagination_preserves_unsaved_values(client) -> None:
    response = await client.post(
        "/orders/1/relationships/items/page/2",
        data={"status": "draft-changed", "items-NEW-sku": "X"},
        headers={"HX-Request": "true"},
    )
    assert 'value="draft-changed"' in response.text
    assert 'value="X"' in response.text
```

- [ ] **Step 2: Verify failure**

Expected: routes/templates missing.

- [ ] **Step 3: Implement relationship UI**

Use select or HTMX autocomplete for to-one, searchable chips for many-to-many, inline rows for one-to-many, and association scalar fields for association objects. Preserve complete `FormState` across fragments. Give every unlink/delete/reorder control an accessible label. Final persistence remains one parent POST transaction.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/rakit-web/tests/test_relationship_ui.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/rakit-web
git commit -m "feat(web): add relationship editing UI"
```

### Task 4: Add unified action definitions and execution

**Files:**
- Create: `packages/rakit-core/src/rakit_core/actions.py`
- Create: `packages/rakit-web/src/rakit_web/action_routes.py`
- Create: `packages/rakit-web/src/rakit_web/templates/actions/form.html`
- Create: `packages/rakit-web/src/rakit_web/templates/actions/confirm.html`
- Test: `packages/rakit-web/tests/test_actions.py`

**Interfaces:**
- Produces: `ActionDefinition`, `ActionAvailability`, `ActionResult`, action decorators/classes.
- Consumes: operation pipeline and forms.

- [ ] **Step 1: Write availability recheck test**

```python
@pytest.mark.anyio
async def test_action_availability_is_rechecked_on_post(client, order) -> None:
    page = await client.get(f"/orders/{order.id}/actions/approve")
    token = extract_hidden(page.text, "_rakit_submission_token")
    await mark_order_cancelled(order.id)
    response = await client.post(
        f"/orders/{order.id}/actions/approve",
        data={"_rakit_submission_token": token},
    )
    assert response.status_code == 409
    assert "no longer available" in response.text
```

- [ ] **Step 2: Verify failure**

Expected: action routes missing.

- [ ] **Step 3: Implement action system**

Scopes: PAGE, RESOURCE, RECORD, BULK. Availability: AVAILABLE, DISABLED, HIDDEN. GET renders typed input/preview/confirmation. POST reloads records through the scoped query, rechecks permission and availability, validates concurrency/idempotency, executes a mutation plan or domain service, and returns structured render/redirect/refresh/success/rejected/validation results.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/rakit-web/tests/test_actions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/rakit-core packages/rakit-web
git commit -m "feat: add unified actions"
```

### Task 5: Add explicit- and query-selection bulk actions

**Files:**
- Create: `packages/rakit-core/src/rakit_core/bulk.py`
- Modify: `packages/rakit-core/src/rakit_core/actions.py`
- Modify: `packages/rakit-web/src/rakit_web/action_routes.py`
- Test: `packages/rakit-web/tests/test_bulk_actions.py`

**Interfaces:**
- Produces: `ExplicitSelection`, `QuerySelection`, `BulkPolicy`, `BulkMutationPlan`.
- Consumes: canonical resource query and signed confirmation.

- [ ] **Step 1: Write safety and rollback tests**

```python
@pytest.mark.anyio
async def test_bulk_over_limit_is_rejected(client) -> None:
    response = await client.post(
        "/orders/actions/archive/preview",
        data={"selection": "current_query"},
    )
    assert response.status_code == 409
    assert "maximum synchronous bulk size" in response.text.lower()


@pytest.mark.anyio
async def test_atomic_bulk_rolls_back_on_conflict(service) -> None:
    with pytest.raises(RakitError):
        await service.execute_atomic(
            identities=["1", "2"], action_id="mark_paid", stale_identity="2"
        )
    assert await service.states(["1", "2"]) == ["pending", "pending"]
```

- [ ] **Step 2: Verify failure**

Expected: bulk system missing.

- [ ] **Step 3: Implement bulk plans**

Defaults: confirmation above 25 records, maximum 1,000 synchronous records, ATOMIC policy, BEST_EFFORT only when explicitly selected and savepoints are supported. Query selections store canonical query plus exclusions. Signed fingerprint binds query, exclusions, action input, principal, expected count, and expiry. Recheck count and permissions during execution.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/rakit-web/tests/test_bulk_actions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/rakit-core packages/rakit-web
git commit -m "feat: add safe bulk actions"
```

### Task 6: Add custom AdminPage GET/POST flows

**Files:**
- Create: `packages/rakit-core/src/rakit_core/pages.py`
- Create: `packages/rakit-web/src/rakit_web/page_routes.py`
- Test: `packages/rakit-web/tests/test_custom_pages.py`

**Interfaces:**
- Produces: `AdminPage`, `PageDefinition`, `@admin.page`, page actions.
- Consumes: typed schemas, services, action results.

- [ ] **Step 1: Write full/fragment test**

```python
@pytest.mark.anyio
async def test_custom_page_uses_same_context_for_full_and_fragment(client) -> None:
    full = await client.get("/scraping/competitors?q=shoes")
    fragment = await client.get(
        "/scraping/competitors?q=shoes",
        headers={"HX-Request": "true"},
    )
    assert "shoes" in full.text
    assert "shoes" in fragment.text
    assert "<html" in full.text
    assert "<html" not in fragment.text
```

- [ ] **Step 2: Verify failure**

Expected: route missing.

- [ ] **Step 3: Implement page declarations**

Pages have stable ID, path, label, permission, optional input schema, full/fragment templates, timeout, and GET/POST handlers. POST always uses CSRF, idempotency, normalized errors, and operation context. Developer configures external URLs; users control only schema-validated parameters.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/rakit-web/tests/test_custom_pages.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/rakit-core packages/rakit-web
git commit -m "feat: add custom admin pages"
```

### Task 7: Add typed custom JSON endpoints

**Files:**
- Create: `packages/rakit-core/src/rakit_core/endpoints.py`
- Create: `packages/rakit-web/src/rakit_web/endpoint_routes.py`
- Test: `packages/rakit-web/tests/test_endpoints.py`

**Interfaces:**
- Produces: `AdminEndpoint`, `@admin.api.get`, `@admin.api.post`, structured endpoint results.
- Consumes: Pydantic schemas and operation pipeline.

- [ ] **Step 1: Write schema and error-envelope tests**

```python
@pytest.mark.anyio
async def test_endpoint_validates_and_serializes(client) -> None:
    response = await client.get("/api/system-status?verbose=true")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "services": []}


@pytest.mark.anyio
async def test_endpoint_validation_error_is_stable(client) -> None:
    response = await client.get("/api/system-status?verbose=not-a-bool")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.failed"
```

- [ ] **Step 2: Verify failure**

Expected: endpoint runtime missing.

- [ ] **Step 3: Implement endpoint runtime**

Support GET and POST only. Input source is exactly one of query, JSON, or form; unknown fields are rejected. Default access is authenticated/private. Public access is explicit. GET defaults READ_ONLY. POST defaults AUTO transaction plus CSRF, Origin validation, and idempotency. JSON is default output. File/stream results must complete database transactions before sending bytes. Do not generate REST resources or OpenAPI.

- [ ] **Step 4: Run tests**

```bash
uv run pytest packages/rakit-web/tests/test_endpoints.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/rakit-core packages/rakit-web
git commit -m "feat: add typed custom endpoints"
```

## Plan completion gate

All relationship kinds, action scopes, bulk selection modes, custom pages, and custom endpoints reuse authorization, transactions, events, concurrency, idempotency, deadlines, and normalized errors.
