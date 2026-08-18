# Rakit UI-05E Filter Rail & Responsive Filter Experience Design

Date: 2026-08-18
Status: Approved design direction; ready for maintainer review before implementation planning

## 1. Goal

UI-05E refines the resource filtering experience introduced in UI-05D so it scales from a small demonstration resource to arbitrary developer-defined filters without requiring page-specific layout work.

The current expandable filter card works functionally, but its horizontal grid presentation is not durable for a framework where applications may declare many filters, custom semantic filters, long choice lists, or a mix of text, numeric, boolean, date, date-range, legacy, and custom controls.

UI-05E adopts a Django-admin-inspired filtering philosophy with a modern Rakit presentation:

- a persistent right-side filter rail on desktop;
- a mobile filter drawer using the same filter-group renderer;
- vertically stacked filter groups separated by visible dividers;
- sensible automatic expand/collapse behavior;
- adaptive handling for long choice lists;
- global active-filter chips outside the rail;
- full SSR behavior with HTMX as progressive enhancement only;
- Web-specific presentation configuration kept separate from semantic filter definitions.

This slice remains part of UI-05 resource experience acceptance. It does not change query semantics, generated REST behavior, SQLAlchemy translation, pagination contracts, or UI-06 operation/auth work.

## 2. Architectural Boundary

`ResourceFilter` remains a backend-neutral semantic/query contract.

It continues to own concerns such as:

- `filter_id`;
- `label`;
- operators;
- control kind;
- choices;
- predicate fields;
- parsing and serialization;
- display values;
- custom resolution to ordinary backend-neutral predicates.

It must not gain Web layout concerns such as sidebar width, collapse thresholds, drawer behavior, spacing, or CSS classes.

Presentation concerns belong to `rakit-web`.

The conceptual flow is:

```text
ResourceFilter semantic definition
        ↓
rakit-core compiled resource/query contract
        ↓
rakit-web resource query presentation model
        ↓
Web presentation policy
        ↓
shared generic filter-group renderer
        ↓
Desktop rail / Mobile drawer
```

Generated REST and non-Web consumers never need to know how browser filters are presented.

## 3. Desktop Layout

On desktop and sufficiently wide laptop viewports, resource filtering uses a right-side rail next to the resource table.

The main resource area becomes conceptually:

```text
Orders                                             32 total

[ Search orders................................ ]

[Status: Paid ×] [Customer contains Atlas ×]  Clear all

┌────────────────────────────────────────────────┬──────────────────────────┐
│                                                │ FILTERS            Hide  │
│                                                │                          │
│                  DATA TABLE                    │ Status · 1            ▴ │
│                                                │ ○ All                    │
│                                                │ ● Paid                   │
│                                                │ ○ Pending review         │
│                                                ├──────────────────────────┤
│                                                │ Customer              ▴ │
│                                                │ [contains          ▾]   │
│                                                │ [________________]      │
│                                                │ [Apply]                 │
│                                                ├──────────────────────────┤
│                                                │ Created               ▾ │
└────────────────────────────────────────────────┴──────────────────────────┘

Showing 1–20 of 32                       Previous  1  2  Next
```

The rail is visible by default but can be hidden manually by the current browser user.

When hidden, the table expands into the freed space and a compact `Show filters` control remains visible. If filters are active, the control includes the active count, for example `Show filters (2)`.

Hiding or showing the rail is presentation state only. It never changes query state, removes active filters, changes pagination, or changes URL semantics.

## 4. Filter Group Composition and Dividers

Each filter is rendered as a distinct vertical filter group.

A group contains:

1. a header;
2. optional active-count indicator;
3. expand/collapse affordance;
4. the control renderer for the semantic filter type.

Adjacent groups are separated by a visible but restrained horizontal divider using the Rakit border token.

The rail itself is one coherent surface. Individual filter groups are not rendered as nested cards. This avoids card noise when resources expose many filters.

The boundary between the table and the rail is also visually clear through layout separation and a vertical border/divider treatment.

Dividers are a framework visual invariant. Developers do not configure them per filter.

## 5. Expand and Collapse Rules

Automatic behavior must work without configuration.

Default rules:

- when a resource has four or fewer filter groups, all groups are expanded initially;
- when a resource has more than four groups, the first four are expanded initially and the remainder are collapsed;
- any filter with active query state is expanded on initial render even if it is beyond the automatic threshold;
- users may manually collapse an active filter;
- applying or clearing a filter does not implicitly hide the entire rail;
- clearing a filter does not intentionally collapse its group during an enhanced interaction;
- `Clear all` does not hide the rail.

A filter header may present active state as:

```text
Status · 1                       ▴
```

A manually collapsed active group remains visibly active:

```text
Created · 2                      ▾
```

Expand/collapse is presentation state, not semantic query state.

## 6. Choice and Boolean Presentation

Single-value `ChoiceFilter` and `BooleanFilter` use a vertical option-list presentation suitable for a narrow rail.

Example:

```text
Status

● All
○ Paid
○ Pending review
○ Processing
○ Fulfilled
○ Refunded
○ Cancelled
```

The current horizontal pill layout is removed from the filter-selection surface because it becomes difficult to scan and wrap predictably in a narrow rail.

Choice/boolean selection applies immediately through the canonical GET query flow. These controls do not require a separate `Apply` button.

The visual selection treatment must expose equivalent semantic state to assistive technology; it must not rely on decorative radio circles alone.

Active-filter chips remain outside the rail and continue to summarize the effective query.

## 7. Text, Number, Date, and Date-Range Presentation

Controls that require user input retain explicit application.

The default interaction is:

- `TextFilter` → operator + text value + Apply;
- `NumberFilter` → operator + numeric value + Apply;
- `DateFilter` → operator + date value + Apply;
- `DateRangeFilter` → From + To + Apply;
- legacy filters → the compatible operator/value presentation already supported by the resource query layer.

Custom `ResourceFilter` subclasses are rendered according to their declared semantic `control`, not according to class names or datasource-specific information.

The rail must never expose internal predicate expansion. For example, the custom showcase filter `Stock level: Needs attention` remains a semantic selection even if it resolves internally to multiple status predicates.

## 8. Long Choice Lists

Choice lists must not make the resource page arbitrarily tall by default.

Default policy:

- up to eight choices: render all choices;
- more than eight choices: render a preview of six choices plus a `Show N more` disclosure;
- when expanded, the user can return with `Show less`;
- very long expanded lists use a bounded internal scrolling area rather than forcing an extremely tall page.

`Show more` and `Show less` change presentation only. They do not issue a filtering request or alter query state.

Remote/searchable dynamic choice loading is intentionally out of scope for UI-05E. The presentation architecture should not prevent adding such a capability later.

## 9. Active Filter Summary

Active-filter chips remain outside the filter rail and above the primary result area.

Examples:

```text
[Status: Paid ×]
[Customer contains Atlas ×]
[Created: 2026-08-01–2026-08-18 ×]

Clear all filters
```

The summary serves three purposes:

1. the current query remains obvious when the rail is hidden;
2. mobile users can inspect/remove effective filters without reopening the drawer;
3. complex semantic filters remain understandable without exposing backend predicates.

Long chip values may truncate visually, but accessible names retain the complete effective label.

## 10. Web-Specific Presentation Configuration

Zero-configuration behavior must be production-quality.

A normal resource should only need semantic filters:

```python
class OrdersAdmin(ResourceAdmin):
    filters = (
        TextFilter(...),
        ChoiceFilter(...),
        DateRangeFilter(...),
    )
```

Rakit automatically supplies the rail, dividers, collapse behavior, long-choice handling, active-state treatment, and mobile container.

Developer overrides are an escape hatch and belong to `rakit-web`, not `rakit-core` or `ResourceFilter`.

The intended public shape is conceptually:

```python
ResourceWebPresentation(
    filters=FilterPanelPresentation(
        visible_by_default=True,
        collapse_after=4,
        choice_collapse_after=8,
        choice_preview_count=6,
    )
)
```

Per-filter behavior may be overridden by `filter_id`:

```python
ResourceWebPresentation(
    filters=FilterPanelPresentation(
        groups={
            "status": FilterGroupPresentation(
                expanded_by_default=True,
            ),
            "country": FilterGroupPresentation(
                choice_preview_count=10,
            ),
        },
    )
)
```

Exact public names remain subject to implementation planning and compatibility review, but the architectural requirements are fixed:

- presentation policy lives in `rakit-web`;
- references use semantic `filter_id` values;
- configuration changes behavior, not pixel-level styling;
- invalid presentation references fail clearly during resource registration/compilation rather than being silently ignored.

The API must not expose arbitrary CSS concerns such as rail width, divider color, padding values, button classes, or raw Tailwind classes.

## 11. Responsive Strategy

The right rail is a desktop/laptop presentation, not a narrow-screen sidebar squeezed onto mobile.

At tablet/mobile sizes, the resource toolbar shows a `Filters` button with the active count when applicable:

```text
[ Search orders................ ]
[ Filters (2) ]
```

Activating the control opens a filter drawer/sheet.

The drawer and desktop rail use the same generic filter-group rendering model. They must not become separate implementations with divergent behavior.

Conceptually:

```text
Filter presentation model
        ↓
Shared FilterGroup renderer
        ├── Desktop container: right rail
        └── Mobile container: drawer
```

This ensures new built-in or custom semantic filters automatically work in both viewport modes.

## 12. Mobile Drawer Interaction

The mobile drawer:

- has an accessible `Filters` name;
- includes the same vertical group dividers as desktop;
- preserves the same group ordering and controls;
- closes through an explicit close control, Escape, or backdrop interaction where appropriate;
- moves focus into the drawer on open;
- prevents keyboard focus from escaping into obscured page content;
- restores focus to the Filters trigger when closed.

During enhanced HTMX interaction, applying or clearing a filter should not unexpectedly close the drawer. The user closes it intentionally.

Without JavaScript, a normal full-page GET remains authoritative and filtering continues to work correctly even though overlay presentation state cannot persist across the navigation.

## 13. SSR and HTMX Progressive Enhancement

All filtering remains based on canonical server-visible GET parameters.

JavaScript and HTMX are optional enhancements, never the source of truth.

Without JavaScript:

```text
select/submit filter
→ normal GET
→ server parses semantic query
→ server renders correct resource page
```

With HTMX:

```text
select/submit filter
→ same canonical GET semantics
→ targeted resource result update
→ browser URL updated consistently
→ presentation/focus state preserved where practical
```

Bookmarking, reload, copy URL, browser back/forward, and direct navigation must continue to reconstruct the effective query correctly.

UI-05E must not create client-only filter state that can disagree with the URL.

## 14. Query and Pagination Interaction

UI-05E does not change the semantic query contracts established in UI-05D.

When a substantive query dimension changes, the result set returns to the first page. This applies to:

- search;
- filter changes;
- sorting changes;
- page-size changes.

Other active query dimensions are preserved.

This prevents stale page numbers from producing confusing empty or partial result states after the dataset ordering or matching set changes.

The existing Admin Web tolerant canonicalization remains authoritative. Generated REST continues to use its existing strict/fail-closed behavior.

## 15. Accessibility Requirements

Each filter group is a semantically distinct region/section associated with its visible heading.

Disclosure controls expose appropriate state, including `aria-expanded` and a relationship to the controlled region.

Requirements include:

- keyboard-operable group expand/collapse;
- keyboard-operable rail show/hide;
- semantic single-choice state for choice/boolean filters;
- visible focus using Rakit focus tokens;
- accessible labels for operator/value/date controls;
- accessible active-filter removal labels;
- drawer focus containment and restoration;
- Escape support for the drawer;
- no reliance on color alone for selected/active state;
- normal text contrast remains at least 4.5:1 and large text at least 3:1;
- reduced-motion preferences remain respected.

## 16. Showcase Acceptance Scenarios

`examples/ui_showcase` remains the primary deterministic visual acceptance surface.

UI-05E acceptance must exercise at least:

1. Orders with choice, text, and date-range filters;
2. Inventory with the custom semantic `StockLevelFilter`;
3. a resource exposing more than four filters to prove automatic group collapse;
4. a choice filter exposing more than eight choices to prove choice overflow behavior;
5. active filters beyond the automatic collapse threshold;
6. rail hide/show while filters remain active;
7. active-filter chips while the rail is hidden;
8. mobile filter drawer;
9. Light, Dark, and System themes;
10. keyboard navigation and focus behavior;
11. no-JavaScript filtering path;
12. long labels and long choice labels without layout breakage.

The showcase must continue to use default Rakit framework UI only and must not add private CSS to make the demonstration pass.

## 17. Error and Invalid-State Behavior

Presentation changes must not weaken existing query validation or security behavior.

- Invalid Admin Web query values continue to use the tolerant/canonical behavior established in UI-05D without widening policy.
- Generated REST remains strict and fail-closed.
- Unknown filter IDs remain governed by existing policy.
- Custom filter resolvers never execute presentation-defined predicates.
- Web presentation configuration may reference only declared semantic filters.
- Invalid presentation configuration fails during configuration/registration rather than rendering partially inconsistent UI.

Raw parser, adapter, SQL, or predicate details are not exposed to end users through the rail.

## 18. Implementation Boundary

UI-05E includes:

- Web filter presentation policy;
- resource-level Web presentation registration path;
- generic filter presentation model refinements;
- shared filter-group renderer;
- desktop right rail;
- desktop rail hide/show;
- visible dividers between groups;
- automatic group expansion/collapse;
- adaptive long-choice presentation;
- mobile drawer using the same renderer;
- active-state presentation;
- SSR-first filtering behavior;
- HTMX progressive enhancement where appropriate;
- accessibility behavior;
- showcase scenarios and focused regression coverage.

UI-05E explicitly does not include:

- changes to `ResourceFilter` semantic meaning;
- OR/NOT expression DSL;
- new SQLAlchemy query semantics;
- generated REST policy changes;
- new pagination strategies;
- remote/searchable dynamic choice providers;
- UI-06 actions/bulk/relationship redesign;
- UI-06 auth/session redesign;
- release/tag/PyPI work.

## 19. Development and Verification Strategy

Implementation follows the maintainer workflow for this project:

1. implement source/runtime/template/CSS behavior first;
2. rebuild generated CSS from `packages/rakit-web/src/rakit_web/assets/rakit.css` using the repository asset workflow;
3. perform focused non-test verification and inspect the UI showcase;
4. add/update focused unit and regression tests after the feature behavior is in place;
5. run format, lint, type checking, focused tests, then the full repository/CI gate;
6. perform local/browser visual acceptance before the UI-05 integration PR is allowed to merge to `main`.

Generated CSS is never hand-edited.

## 20. Branch and PR Strategy

UI-05E is developed on:

```text
ui-05e-filter-rail-responsive-filters
```

Its pull request targets:

```text
ui-05-resource-experience
```

The UI-05 integration PR to `main` remains draft/unmerged until UI-05E and the remaining browser acceptance work are approved.

## 21. Success Criteria

UI-05E is successful when:

- developer-defined filter count no longer dictates custom page layout work;
- arbitrary semantic filters render consistently through one generic presentation pipeline;
- adjacent filters have obvious visual separation without nested-card noise;
- desktop filtering behaves like a stable product surface rather than a temporary popover form;
- mobile filtering is usable without duplicating renderer logic;
- clearing a filter never causes the entire filtering UI to disappear unexpectedly;
- active state remains understandable when groups or the entire rail are collapsed/hidden;
- long choice lists are bounded and usable;
- SSR remains fully functional without JavaScript;
- HTMX only enhances the same canonical GET behavior;
- core/query/REST/adapter contracts remain unchanged unless implementation discovers a narrowly scoped compatibility bug;
- the final result passes automated verification plus maintainer browser acceptance.