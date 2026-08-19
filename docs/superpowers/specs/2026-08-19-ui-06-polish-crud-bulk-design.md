# UI-06 Polish, Built-in CRUD, and Bulk Delete Design

## Goal

Polish the combined UI-06 browser experience without changing the security/transaction semantics established by UI-06A-D, while making the framework's built-in resource operations line up with the familiar Django Admin mental model.

## Decisions

### Built-in versus custom operations

- `ResourceAdmin` CRUD remains framework-generated behavior, not user `ActionDefinition` entries.
- Create, detail/view, update, and delete appear only when the resource's compiled capability and permission permit the operation.
- The only framework-provided bulk operation is **Delete selected** when delete is supported and authorized.
- Other BULK actions are user-defined and appear only when registered by the application.
- Custom PAGE definitions do not receive CRUD automatically.
- Existing `MutationHooks` remain the lower-level customization seam. A Django-like ergonomic `ResourceAdmin` lifecycle API is explicitly deferred to a later improvement.

### Theme control

The theme menu gets an explicit placement contract. Sidebar placement opens upward; auth/system header placement opens downward. Choosing a theme updates preference without navigation, scroll jumps, or stealing focus beyond returning focus to the invoking trigger. Click-away and Escape close the menu.

### Popovers

All native `<details>` action overflow menus use the shared `rakit-popover` marker so existing progressive-enhancement click-away and Escape handling applies consistently. No-JavaScript behavior remains functional through native `<details>`.

### Select controls

Native selects receive a framework-owned chevron instead of relying on browser-specific native arrow placement. The select retains native semantics and keyboard behavior; the presentation wrapper only provides spacing and a stable icon location.

### Bulk selection

Resource tables with bulk operations expose a header checkbox that selects/deselects all selectable rows on the current rendered page. JavaScript maintains checked/indeterminate state and selected-count text. Individual row checkboxes remain normal form controls and continue to work without JavaScript.

This is page-local selection only. It does not silently select records across pagination, filters, or cursor pages.

### Bulk review and errors

The canonical server route remains authoritative. With JavaScript enabled, bulk review/confirmation and safe validation/rejection states may be presented in a Rakit dialog rather than navigating to a visually detached full page. Without JavaScript, the same GET/POST endpoints render a fully styled Rakit page and preserve CSRF, idempotency, confirmation, availability, concurrency, and authorization checks.

Empty selection must render a normal Rakit feedback/review surface, never plain unstyled HTML.

## Compatibility

- No change to core action registration semantics.
- No change to mutation authorization, transaction, concurrency, or idempotency contracts.
- No implicit registration of showcase actions such as `Mark reviewed`.
- Existing custom bulk actions remain supported alongside built-in Delete selected.
- Main remains untouched; work integrates only through `ui-06-advanced-operations`.
