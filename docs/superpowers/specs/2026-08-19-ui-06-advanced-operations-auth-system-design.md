# Rakit UI-06 Advanced Operations, Auth, and System Surfaces Design

Date: 2026-08-19
Status: Approved design direction; written for maintainer review before implementation planning

## 1. Goal

UI-06 matures Rakit's advanced operational surfaces into one coherent production-grade experience without weakening the framework's transport-neutral core, capability boundaries, SSR-first behavior, or fail-closed security model.

The slice covers four coordinated areas:

1. actions and bulk operations;
2. relationships and uploads;
3. authentication and system surfaces;
4. custom pages and feedback consistency.

UI-06 is a presentation and interaction maturity pass over capabilities Rakit already owns. It may add narrowly-scoped Web-only presentation policy where the current core semantics are insufficient to choose a safe visual hierarchy, but it must not move presentation concerns into `rakit-core` or invent backend capability that does not exist.

## 2. Integration Strategy

UI-06 is developed on one integration branch:

```text
ui-06-advanced-operations
```

Four implementation slices merge into that integration branch in order:

```text
UI-06A  Actions & Bulk Operations
UI-06B  Relationships & Uploads
UI-06C  Auth & System Surfaces
UI-06D  Custom Pages & Feedback Consistency
```

Each slice is reviewable and verifiable independently, but `main` is not updated until the combined integration branch passes fresh CI and browser acceptance.

After UI-06 lands on `main`, `examples/reference_app` is built as a separate follow-up using only public Rakit APIs. UI-07 then performs responsive/accessibility hardening across both `examples/ui_showcase` and `examples/reference_app`, followed by UI-08 final polish.

## 3. Architectural Boundary

The ownership model is fixed:

```text
rakit-core
  owns semantics, capability, policy, authorization, transactions,
  idempotency, concurrency, action availability, relationship edit modes,
  storage policy, and typed page/action results

rakit-web
  owns layout, visual hierarchy, interaction presentation, Web-only intent,
  browser/system surfaces, and progressive enhancement

application
  may optionally configure Web presentation through public Web-only policy
```

`rakit-core` must not import `rakit-web`.

Visual semantics such as a red destructive button are not inferred from unrelated business/runtime flags unless the core contract explicitly provides that semantic. Conversely, Web presentation never overrides authorization, availability, transaction, idempotency, concurrency, relationship destructive policy, or storage rules.

## 4. UI-06A — Actions and Bulk Operations

### 4.1 Unified action mental model

PAGE, RESOURCE, RECORD, and BULK actions use the same interaction language. Context changes where the action appears and what it affects; the user should not need to relearn the action flow for each scope.

The canonical flow remains the existing server-authoritative pipeline:

```text
optional input form
  -> authoritative preview
  -> optional confirmation
  -> POST execution
  -> structured result / redirect / refresh
```

No critical action flow may become JavaScript-only.

### 4.2 Web-only action intent

`ActionDefinition` remains unchanged. It continues to own runtime semantics such as:

- scope;
- `mutating`;
- `needs_form`;
- `needs_preview`;
- `needs_confirmation`;
- availability;
- authorization;
- transaction policy;
- concurrency;
- idempotency;
- bulk policy.

Web presentation adds a separate visual-intent contract:

```python
class ActionIntent(StrEnum):
    DEFAULT = "default"
    PRIMARY = "primary"
    DANGER = "danger"


@dataclass(frozen=True, slots=True)
class ActionPresentation:
    intent: ActionIntent = ActionIntent.DEFAULT
```

`ResourceWebPresentation` is extended backward-compatibly with action presentation keyed by `action_id`:

```python
ResourceWebPresentation(
    filters=FilterPanelPresentation(),
    actions={
        "refund_order": ActionPresentation(intent=ActionIntent.DANGER),
    },
)
```

Page actions use the symmetric Web-only contract:

```python
@dataclass(frozen=True, slots=True)
class PageWebPresentation:
    actions: Mapping[str, ActionPresentation] = field(default_factory=dict)
```

and registration becomes:

```python
admin.register_page(
    PageDefinition(...),
    actions=(...),
    web=PageWebPresentation(...),
)
```

The ellipses above are illustrative call-site placeholders, not additional runtime fields. Existing registration calls without `web=` remain valid.

### 4.3 Intent validation

Presentation configuration fails closed during registration/startup:

- unknown action ids are invalid;
- non-`ActionPresentation` values are invalid;
- invalid presentation enum values are invalid;
- each owner may have at most one `PRIMARY` action **within each action scope**.

For example, one resource may independently have one primary RESOURCE action, one primary RECORD action, and one primary BULK action, but it may not have two primary RECORD actions.

Rakit does not expose arbitrary action CSS classes, colors, pixel positions, or raw class-name customization through this contract.

### 4.4 Action placement

`ActionIntent` determines hierarchy, not only color:

- `PRIMARY`: preferred visible CTA when a primary action exists;
- `DEFAULT`: ordinary visible or overflow action according to density;
- `DANGER`: separated destructive treatment, normally in a destructive section or visually separated overflow group.

Danger does not imply confirmation. Confirmation remains controlled by `ActionDefinition.needs_confirmation`.

A mutating or confirmed action is not automatically treated as danger. Actions such as Publish, Approve, Regenerate, or Archive may mutate state without being semantically destructive.

When action density is high, Rakit uses a deterministic overflow strategy rather than placing every action side-by-side.

### 4.5 Availability

Core availability remains authoritative:

- `AVAILABLE` renders normally;
- `DISABLED` may remain visible and must expose the safe human-facing reason when supplied;
- `HIDDEN` is not rendered.

POST execution still re-evaluates availability and authorization against fresh state. The Web layer never treats a disabled visual state as the security boundary.

### 4.6 Action forms, preview, and confirmation

Action forms use the same mature form primitives as resource forms.

Preview pages are review surfaces rather than generic warning dialogs. They should clearly present:

- action label;
- target/context;
- submitted values that are safe to render;
- authoritative preview title and description;
- impact text when supplied;
- back/cancel affordance;
- confirm CTA whose visual intent follows `ActionPresentation`.

Signed CSRF, submission, concurrency, and confirmation tokens remain unchanged and must survive full-page and HTMX paths.

### 4.7 Action result presentation

Existing structured results map to consistent Web feedback:

- success: success feedback plus existing redirect/refresh semantics;
- validation: field-local errors plus summary where needed;
- rejected: expected business-policy rejection, not generic server error;
- rendered: normal Rakit result surface;
- redirect: existing 303/HX redirect semantics;
- refresh: existing HX/full-page refresh semantics;
- advanced response: existing opt-in adapter behavior.

Presentation must not collapse validation, business rejection, authorization failure, and unexpected failure into one generic red error box.

### 4.8 Bulk operations

Bulk UI appears only when selection exists and prominently states selected-record count.

Safe/default actions and danger actions are separated. Confirmation must describe scope and impact instead of only asking "Are you sure?".

When existing bulk policy exposes useful execution semantics such as atomic vs best-effort behavior, thresholds, or partial-result policy, the UI may surface that information. It must not invent policy absent from the core contract.

Bulk selection, submission tokens, concurrency snapshots, CSRF, authorization, and transaction behavior remain server-authoritative.

## 5. UI-06B — Relationships and Uploads

### 5.1 Adaptive relationship presentation

Relationship presentation derives from the existing relationship contract. Rakit does not add a second relationship semantics layer in Web presentation.

Baseline rendering rules:

```text
TO_ONE + LINK
  -> compact current-selection surface with change/clear affordances

TO_MANY + LINK, complete linked set already available in the current result
  -> compact linked-record list

TO_MANY + LINK, result is paginated or indicates records outside the loaded window
  -> searchable/paginated compact list or table using existing editor/query capability

INLINE / NESTED
  -> editable row/nested presentation only because the developer explicitly chose that edit mode

READ_ONLY
  -> calm information-only list/table

HIDDEN
  -> not rendered
```

Rakit does **not** introduce a magic numeric "high-cardinality" threshold in UI-06. The compact-vs-paginated choice is result/capability-driven:

- if the current relationship result proves the complete linked set is loaded, a compact list is allowed;
- if pagination metadata, `has_next`, a total beyond the loaded window, or equivalent existing relationship-editor state proves additional records exist, use the paginated surface;
- if the runtime cannot safely establish that the loaded set is complete, prefer the existing paginated/editor surface rather than silently presenting an incomplete compact list.

This rule avoids domain-specific assumptions and keeps the renderer aligned with server-authoritative relationship querying.

### 5.2 Empty states

Every editable/readable relationship mode has a clear empty state such as "No products linked yet" plus only the affordances the compiled capability permits.

### 5.3 Candidate selection

Candidate selection may be progressively enhanced with HTMX/dialog/drawer presentation, but the critical flow must remain usable with ordinary navigation/form submission.

Search, pagination, and candidate visibility use existing server-side relationship helper behavior and exact compiled permissions.

### 5.4 Unlink is not delete

The UI must visually and verbally distinguish:

```text
unlink/remove relationship
```

from:

```text
delete related record permanently
```

Persistent child deletion is shown only when the compiled `RelationshipDestructivePolicy` and permissions permit it. Mapper cascade facts or visual intent never enable destructive deletion on their own.

### 5.5 Ordering

Reorder controls appear only when the relationship is actually reorderable.

Any drag-and-drop treatment is progressive enhancement. The baseline must provide accessible non-pointer controls such as move up/down or an equivalent SSR-compatible mechanism where reordering is supported.

No fake reorder affordance appears when the backend/compiled relationship does not support reordering.

### 5.6 Upload presentation

`FileField` becomes a first-class mature form field while remaining field-centric rather than expanding into a media-library subsystem.

The UI derives safe policy hints from the existing field definition, including where applicable:

- allowed extensions;
- allowed MIME types;
- maximum size;
- required/nullable state;
- filename constraints;
- current file state;
- replace capability;
- removal affordance when the existing mutation/delete behavior permits it.

The server remains authoritative for all validation and storage policy. Client hints are explanatory only.

Rakit does not show fake progress UI unless the active transport/storage path actually exposes a real progress capability.

## 6. UI-06C — Authentication and System Surfaces

### 6.1 Shell model

Rakit formalizes three presentation contexts:

```text
app shell
  authenticated normal product surface with navigation

auth shell
  login/session-related surface with brand + theme, no admin sidebar

system shell
  403 / 404 / production 500 with brand + theme, no admin sidebar
```

These contexts reuse the same shared document head, semantic tokens, theme initialization, assets, accessibility primitives, and brand language. They are not three separate styling systems.

Existing template context compatibility such as `rakit_shell_enabled` is preserved. Internal implementation may add a more explicit shell-mode value, but custom templates that depend on existing context must not be forced to rewrite during UI-06.

### 6.2 Login

The login page uses a dedicated minimal auth shell:

- admin/product title;
- concise heading and supporting copy;
- labeled identifier/email field;
- labeled password field;
- primary sign-in CTA;
- theme control;
- accessible inline/global error feedback.

The page does not include a sidebar, marketing hero, illustration, fake remember-me option, fake forgot-password feature, or social-auth control when those capabilities do not exist.

The existing pre-session login CSRF defense, field limits, origin handling, rate limiting, credential normalization, session issuance, cookie attributes, and security headers remain authoritative.

Invalid credentials remain deliberately non-enumerating: the UI must not distinguish "unknown identifier" from "wrong password".

HTTP semantics remain:

- successful GET: 200;
- invalid credentials: 401;
- rate limited: 429;
- malformed/invalid security form states retain their existing failure semantics unless separately specified by the runtime.

### 6.3 Session-expired feedback

A stale/invalid session remains resolved as anonymous, revoked/cleared as currently required, and gated by the existing authorization flow.

When the runtime already knows that a browser arrived with a stale/unusable session cookie, that fact may be carried through request-local state to the existing unauthenticated redirect. The redirect may then add a whitelisted reason:

```text
/auth/login?reason=session_expired
```

Only fixed internal reason identifiers are accepted. Unknown values are ignored. Query values are never rendered directly as arbitrary message text.

A user who simply visits a protected page without any session continues to receive the ordinary login redirect without a false "session expired" message.

### 6.4 Logout feedback

Logout remains POST-only and retains CSRF validation for active authenticated sessions, session revocation, and cookie deletion.

After successful logout, the existing 303 redirect may become:

```text
/auth/login?reason=signed_out
```

The login page maps the whitelisted reason to a fixed success message. Logout must never become a GET action for presentation convenience.

### 6.5 403 Access Denied

Authenticated browser authorization failure renders a minimal system shell with HTTP 403.

The surface may explain that access is denied and may offer a safe return/dashboard CTA only when that destination is actually appropriate for the authenticated principal.

It must not disclose:

- missing permission identifiers;
- internal route names;
- hidden resource names;
- permission catalogue details;
- authorization matching internals.

Generated API authorization failure remains JSON and keeps its existing machine-readable contract.

Security-form failures such as invalid CSRF are not reclassified as authorization failures merely to reuse this presentation. Their existing security semantics remain authoritative.

### 6.6 404 Page Not Found

Browser not-found states render a minimal system shell with HTTP 404.

The page must not:

- fuzzy-suggest registered routes;
- enumerate resources;
- reveal hidden routes;
- show route matcher/debug information;
- disclose whether an unauthorized hidden resource exists.

The existing authorization boundary remains ahead of informative routing presentation. UI-06 does not rearrange security to reveal 404 information to principals who would otherwise be redirected or denied.

Mounted admins must generate safe return/dashboard URLs using the active mount/root path rather than assuming `/`.

Generated API 404 remains JSON, not HTML.

### 6.7 Production 500

Unexpected production browser failures render a safe system shell with HTTP 500.

The surface may display the existing request id when available so users can correlate a failure with logs/support.

Production HTML must not expose:

- exception text;
- traceback;
- SQL statements;
- database connection information;
- filesystem paths;
- secret/token values;
- internal stack/module details.

A retry CTA is only appropriate for requests whose HTTP method is semantically safe to retry, limited to GET/HEAD in UI-06. Blind retry is not offered for failed POST/PUT/PATCH/DELETE requests.

Debug mode retains developer diagnostics rather than being replaced by the production 500 surface.

### 6.8 HTML/API error boundary

Browser/admin HTML and generated API errors must remain distinct:

```text
Browser/admin HTML
403 -> system HTML for authenticated authorization failure
404 -> system HTML after the applicable security boundary
500 -> system HTML in production

Generated API
401 -> JSON
403 -> JSON
404 -> JSON
500 -> JSON
```

Generated API route ownership is authoritative for response format; Rakit does not rely only on the `Accept` header to decide whether an API error should become HTML.

`RakitError`, `HTTPException`, and unexpected-error translation must preserve the underlying status/error meaning while selecting the correct browser/API presentation.

## 7. UI-06D — Custom Pages and Feedback Consistency

### 7.1 No page-builder DSL in UI-06

UI-06 deliberately does not add `PageCard`, `PageGrid`, `PageMetric`, or another component/page-builder DSL.

The existing boundary remains:

```text
PageDefinition + PageResult
  -> conservative default Rakit page rendering

PageDefinition(template="...")
  -> explicit custom-template escape hatch
```

This keeps the core page contract backend-neutral and prevents UI-06 from becoming a new page-builder subsystem.

### 7.2 Default page shell

Default custom pages receive mature Rakit page rhythm:

- permission-aware navigation when using the app shell;
- breadcrumbs/current-location hierarchy where applicable;
- consistent heading spacing;
- message/error/empty feedback primitives;
- form styling consistent with resource/action forms;
- normal Rakit responsive width/rhythm;
- theme consistency.

### 7.3 Conservative payload renderer

The current debugging-style default payload dump is replaced by a conservative safe renderer.

Supported default shapes are intentionally narrow:

```text
scalar values
  -> readable scalar presentation

flat mapping of renderable scalar values
  -> definition-list presentation

sequence of flat scalar mappings with consistent keys
  -> compact table presentation

empty payload
  -> neutral empty state

unsupported/deep/arbitrary object
  -> safe neutral message directing the developer to a custom template
```

Rakit must not use arbitrary raw object `repr()` as a production fallback because user/library repr output can expose internal or sensitive data.

Rakit never interprets arbitrary payload strings or mappings as trusted HTML or as an implicit page-component DSL.

### 7.4 Mutating pages

Mutating custom pages retain the existing POST/Redirect/Get and transaction semantics. Their forms use the same Rakit form primitives and feedback hierarchy as resource/action forms.

### 7.5 PAGE actions

PAGE actions participate in the same Web-only `ActionPresentation` hierarchy as resource actions through `PageWebPresentation`. Their core execution semantics remain unchanged.

## 8. Feedback Language and Hierarchy

UI-06 establishes consistent meaning across surfaces:

```text
validation
  user-correctable field/form input problem

business rejection
  expected domain/policy rejection

unavailable
  action/capability currently unavailable for state

forbidden
  authorization failure

not found
  route/resource absence after applicable security boundary

unexpected
  server/runtime failure
```

These states should use appropriate semantic styling and useful copy rather than all appearing as the same generic red error block.

Error copy should help the user understand the next safe step without exposing sensitive internal policy or implementation detail.

## 9. Backward Compatibility

UI-06 is additive and presentation-focused.

The following existing calls remain valid:

```python
admin.register(MyAdmin)

admin.register(
    MyAdmin,
    web=ResourceWebPresentation(filters=FilterPanelPresentation()),
)

admin.register_page(PageDefinition(...))

admin.register_page(
    PageDefinition(...),
    actions=(...),
)

ActionDefinition(...)

PageDefinition(template="my_page.html", ...)
```

The ellipses in these examples represent existing constructor arguments and do not imply unspecified UI-06 behavior.

Additional compatibility requirements:

- existing `ActionDefinition` instances require no new fields;
- existing resource/page templates are not forced to opt into action presentation;
- absence of Web action presentation yields the default intent;
- existing filter presentation behavior remains unchanged;
- existing custom page templates remain the explicit escape hatch;
- existing auth, CSRF, session, rate-limit, permission, transaction, idempotency, and concurrency semantics remain authoritative;
- `rakit-core` does not depend on `rakit-web`.

## 10. Explicit Non-Goals

UI-06 does not implement:

- a custom page-component/page-builder DSL;
- a media library or reusable asset manager;
- arbitrary relationship presentation configuration;
- arbitrary login/system-page visual customization APIs;
- arbitrary CSS class/color/position injection for actions;
- new authentication providers or password-reset flows;
- new storage backends;
- new relationship semantics;
- new bulk transaction semantics;
- fake backend capabilities in JavaScript;
- JavaScript-only critical paths.

These may be considered later only after public-API usage in `examples/reference_app` or real consumers demonstrates a repeated need.

## 11. Implementation Workflow

The repository workflow for UI-06 is feature-first and tests-last within each approved slice:

```text
1. implement source/templates/runtime behavior
2. rebuild generated CSS when source CSS changes
3. run non-test structural/manual verification
4. exercise the new states in examples/ui_showcase
5. add/update regression tests
6. run focused tests
7. run the relevant rakit-web/full suite
8. obtain fresh PR CI
9. perform browser acceptance
10. merge the slice into ui-06-advanced-operations
```

Tests are still mandatory before a slice is considered complete; they are written after the feature behavior is established rather than before implementation.

No UI-06 slice merges directly to `main`.

## 12. Acceptance Criteria by Slice

### 12.1 UI-06A — Actions & Bulk Operations

Visual/behavior acceptance must cover:

- normal record action;
- danger record action;
- disabled action with reason;
- action input form;
- authoritative preview;
- confirmation;
- validation failure;
- business rejection;
- success/redirect/refresh feedback;
- bulk selection with one record;
- bulk selection with many records;
- safe/default bulk action;
- danger bulk action;
- existing atomic/best-effort policy presentation where applicable;
- no-JS execution path.

Contract/regression acceptance must cover:

- unknown Web action presentation fails closed;
- only one primary action per owner/scope;
- existing actions without Web presentation retain valid default behavior;
- CSRF behavior unchanged;
- submission-token/idempotency behavior unchanged;
- concurrency behavior unchanged;
- authorization/availability re-check unchanged.

### 12.2 UI-06B — Relationships & Uploads

Visual/behavior acceptance must cover:

- TO_ONE selected;
- TO_ONE empty;
- TO_ONE change/clear;
- TO_MANY complete/compact linked set;
- TO_MANY paginated linked set;
- empty TO_MANY;
- read-only relationship;
- inline relationship;
- nested relationship;
- reorderable relationship;
- non-reorderable relationship;
- unlink flow;
- permitted destructive child delete flow;
- file empty state;
- current file state;
- replace file;
- permitted file removal state;
- file validation error;
- size/type policy help;
- no-JS relationship flow.

Regression acceptance must confirm relationship permission boundaries, destructive policy, ordering capability, upload validation, storage behavior, and mutation semantics are unchanged.

### 12.3 UI-06C — Auth & System Surfaces

Visual/behavior acceptance must cover:

- login;
- invalid credentials (401);
- rate-limited login (429);
- signed-out message;
- session-expired message;
- unauthenticated redirect without a false session-expired message;
- authenticated 403;
- browser 404;
- production 500;
- debug exception behavior;
- mounted admin path correctness;
- Light theme;
- Dark theme;
- basic mobile layout.

Generated API acceptance matrix:

```text
unauthenticated API -> JSON 401
forbidden API       -> JSON 403
missing API path    -> JSON 404
API server failure  -> JSON 500
```

Security regression acceptance must prove:

- invalid credentials remain non-enumerating;
- login/logout CSRF behavior is unchanged;
- unknown auth reason values are ignored;
- stale-session reason is emitted only when the runtime actually detected a stale/unusable session;
- 403 does not disclose internal permission identifiers;
- 404 does not disclose route/resource registry information;
- production 500 does not leak exception/internal data;
- security gating still precedes informative 404 presentation where required.

### 12.4 UI-06D — Custom Pages & Feedback Consistency

Visual/behavior acceptance must cover:

- scalar payload;
- flat mapping payload;
- sequence-of-flat-mappings payload;
- empty payload;
- unsupported/deep payload;
- custom template;
- mutating page;
- validation feedback;
- business rejection;
- successful redirect;
- PAGE action;
- danger PAGE action.

Regression acceptance must confirm page permission, PRG, transaction, idempotency, input parsing, and custom-template behavior remain unchanged.

## 13. Integration Acceptance

After UI-06A/B/C/D merge into `ui-06-advanced-operations`, fresh integrated verification is required.

The integration branch is not eligible for merge to `main` until all of the following are true:

```text
all slice CI is green
+ fresh integration CI is green
+ combined browser acceptance is complete
+ no known security regression remains
+ no unexpected public API break remains
```

The maintainer performs final browser acceptance on the combined experience. Only after explicit approval does the integration branch merge to `main`.

UI-06 does not create a tag, GitHub Release, TestPyPI release, or PyPI release.

## 14. Post-UI-06 Reference Application

After UI-06 is merged, create `examples/reference_app` as a separate consumer-facing example.

The initial reference app is a realistic but simple backoffice with resources such as Customers, Products, Orders, and Inventory. It should exercise real public Rakit APIs for:

- authentication/session;
- CRUD;
- filters/search/pagination;
- relationships;
- at least one record action such as Refund order;
- at least one bulk action;
- upload when the public capability is appropriate;
- dashboard/custom-page usage where useful.

The reference app must not rely on private framework hooks or private CSS workarounds. Its purpose is to demonstrate what a real user can build with Rakit's public default experience.

## 15. Completion Definition

UI-06 is complete when Rakit's advanced operations, relationship/upload editing, auth/system states, and custom pages share one mature product language while all critical semantics remain server-authoritative and backward-compatible.

The completed slice should make these statements true:

- action hierarchy is explicit without polluting core semantics;
- destructive presentation never substitutes for confirmation/security policy;
- bulk operations communicate selection and impact clearly;
- relationships scale from complete compact sets to paginated sets without changing declared edit semantics;
- unlink and persistent delete are unmistakably different;
- upload UI explains real `FileField` policy instead of inventing client rules;
- login/session/403/404/500 surfaces look intentional and safe;
- generated APIs never receive accidental HTML error pages;
- production 500 surfaces do not leak internals;
- custom pages have a useful default without introducing a premature page-builder DSL;
- existing applications continue to work without opting into new Web presentation settings;
- all critical flows remain usable without JavaScript.
