# UI-05A Dashboard Experience Design

## Status

Approved design for the first UI-05 slice.

This document supersedes the dashboard portion of the original single-PR `UI-05 — Dashboard and Resource Experience` scope. The approved UI-05 sequence is now:

1. `UI-05A — Dashboard Experience`
2. `UI-05B — Resource List Experience`
3. `UI-05C — Resource Detail, Forms & Delete`

The slices are implemented and merged sequentially. UI-05A starts from the merged UI-04 `main`; UI-05B starts after UI-05A merges; UI-05C starts after UI-05B merges.

## Goal

Mature the default Rakit dashboard into a calm, generic operational home page that helps users understand what is available, what needs attention, and where to go next without assuming that every Rakit application is an analytics product.

The dashboard must remain driven by registered Rakit launchers and dashboard widgets. The framework presentation must not invent application-specific KPIs, recent-activity semantics, inventory concepts, or business status rules.

## Design Direction

Use an **operational dashboard** rather than a KPI-first analytics dashboard or a navigation-only portal.

The page hierarchy is:

1. contextual page heading;
2. quick access to registered resources/pages;
3. registered operational widgets in their declared layout sizes;
4. explicit loading, partial-error, empty, and no-content states.

The page should feel useful for an internal/admin product while remaining generic enough for arbitrary Rakit applications.

## Architecture

The existing dashboard runtime remains authoritative:

- launcher definitions determine available shortcuts;
- widget definitions determine labels, layout sizes, lazy behavior, and content;
- capability/permission filtering remains upstream of presentation;
- HTMX remains a progressive enhancement for widget loading/refresh;
- the server-rendered page remains usable without JavaScript.

UI-05A is primarily a template/style/showcase change. Python runtime changes are out of scope unless a concrete semantic presentation requirement cannot be satisfied from data already provided by the existing dashboard context. Any such runtime addition must be presentation-only and preserve permission, routing, error, and HTTP behavior.

## Page Heading

The dashboard has exactly one clear `<h1>`.

Recommended hierarchy:

- eyebrow/context: `Dashboard`;
- page title: the registered dashboard/admin title, for example `Rakit Commerce`;
- short operational supporting copy.

The heading must not become a hero banner or consume excessive vertical space.

## Quick Access

Quick access renders registered launchers only. It must not hard-code resource names or application concepts.

Each launcher may show:

- primary label;
- optional short description supplied by the definition;
- a restrained directional affordance;
- an icon only where a meaningful existing Rakit/Lucide mapping is available and improves scanning.

The launcher treatment should be compact and neutral. Avoid large marketing cards, heavy shadows, oversized radii, or excessive brand backgrounds.

Responsive behavior:

- one column on narrow screens;
- multiple columns when space permits;
- long descriptions wrap without making neighboring controls unusable.

## Widget Presentation

The existing widget size contract remains unchanged:

- small;
- medium;
- large;
- full.

UI-05A must not introduce new layout enum values or reinterpret widget sizing behavior.

All widget containers should use the shared semantic Rakit visual language:

- semantic surface/border/text tokens;
- restrained elevation;
- consistent header/body rhythm;
- readable table/list/value typography;
- no remaining direct blue/slate role styling in modified dashboard templates when an equivalent Rakit semantic role exists.

Cards are acceptable because a dashboard widget is itself a meaningful bounded unit. The design should still avoid nested-card noise inside widgets.

## Widget Content Types

Existing widget result shapes remain authoritative. UI-05A should mature the presentation of the result types already supported by Rakit rather than create new dashboard domain models.

Representative presentation includes:

- scalar/value widgets;
- text widgets;
- table widgets;
- item/list widgets;
- custom widget templates;
- empty widget results;
- widget error states.

A table widget should use compact readable table styling and intentional horizontal overflow. A list widget should use clear row separation without becoming a stack of cards.

## Lazy Loading

Lazy widget behavior remains server + HTMX based.

The initial state must communicate both visually and semantically that content is loading. A compact skeleton may remain decorative, but readable context such as `Loading <widget label>…` must remain available to assistive technology.

Requirements:

- `aria-busy` stays meaningful;
- loading is not represented by animation alone;
- reduced-motion handling from the shared Rakit UI remains authoritative;
- no widget content is gated behind a JavaScript-only client renderer.

## Refresh Behavior

Refresh remains an HTMX enhancement against the existing widget endpoint.

The control may become a compact refresh icon button or restrained secondary control, but it must retain an accessible name such as `Refresh Recent orders`.

During a refresh:

- duplicate activation should be suppressed through existing HTMX control behavior;
- a readable refreshing state is exposed;
- the widget content region remains the update target;
- no new client-side widget state store is introduced.

## Error and Partial-Failure States

A widget failure must not make the entire dashboard unusable.

Use the semantic UI-04 alert/feedback language for widget-local failures:

- clear short failure label;
- server-provided safe message/context where already available;
- retry remains the normal widget refresh path when appropriate.

Do not expose stack traces, exception representations, or debug-only internal details in production presentation.

A page containing healthy and failed widgets must clearly communicate a partial failure without visually turning the whole page into an error state.

## Empty States

Two empty conditions are distinct:

### No launchers and no widgets

Render a calm page-level empty state explaining that registered resources, pages, or widgets will appear when available to the current user.

### A widget has no result rows/items

Keep the empty state inside that widget and use the widget-provided empty message where available.

The framework must not invent a create action or remediation that the registered application did not expose.

## UI Showcase Acceptance Surface

`examples/ui_showcase` remains the deterministic visual QA application and must use only default Rakit UI.

The showcase dashboard should exercise realistic registered definitions such as:

- recent orders;
- low inventory;
- recent activity;
- a compact summary/value widget;
- at least one lazy widget;
- at least one empty widget state;
- at least one deterministic widget error/partial failure scenario if the existing public widget API can express it safely.

These are showcase application concepts, not new framework assumptions.

## Accessibility

UI-05A must preserve or improve:

- exactly one page `<h1>`;
- logical section headings;
- accessible launcher link text;
- keyboard-operable refresh controls;
- visible focus;
- useful `aria-live`/`aria-busy` widget semantics without excessive announcements;
- no color-only failure/status communication;
- reduced-motion behavior.

Icon-only refresh controls require explicit accessible names. Decorative icons remain `aria-hidden` through the existing Rakit icon helper.

## Responsive Baseline

Full systematic responsive hardening remains UI-07, but UI-05A must not intentionally ship broken narrow layouts.

Minimum acceptance:

- quick-access grid collapses cleanly;
- widgets become full-width when their configured grid cannot fit;
- table widget content can scroll horizontally rather than overflow the application shell;
- headings and widget controls wrap without overlapping.

## Files Expected to Change

Primary surface:

- `packages/rakit-web/src/rakit_web/templates/dashboard/index.html`
- `packages/rakit-web/src/rakit_web/templates/dashboard/_widget.html`
- `packages/rakit-web/src/rakit_web/templates/components/dashboard_navigation.html` only where dashboard-local presentation requires it
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- generated `packages/rakit-web/src/rakit_web/static/rakit.css`
- `examples/ui_showcase` dashboard definitions/templates where needed

Runtime Python files are not expected to change by default.

## Testing Strategy

Per the approved execution workflow, implement the complete UI-05A feature surface first, perform visual/manual review, and add/finish focused tests at the end of the slice.

Create or mature dashboard UI contracts that verify stable semantics rather than full HTML snapshots, including:

- one page heading;
- launcher semantics;
- meaningful widget headings;
- lazy loading/busy semantics;
- refresh accessible name/state;
- widget error and empty presentation;
- semantic Rakit token usage in modified built-in dashboard templates;
- preservation of existing dashboard runtime behavior.

Existing `test_dashboard_runtime.py`, accessibility tests, asset tests, and showcase tests remain authoritative regressions.

## Out of Scope

UI-05A does not implement:

- resource search/filter/table redesign;
- resource pagination;
- detail/create/edit/delete redesign;
- domain actions;
- bulk-operation workflow redesign;
- relationship/upload UX;
- auth/session presentation;
- custom-page redesign;
- new widget domain/result types;
- new permission or capability behavior;
- releases, tags, PyPI, or TestPyPI publication.

## Definition of Done

UI-05A is complete when:

- the dashboard is visually coherent with UI-03/UI-04;
- launchers and widgets remain definition-driven;
- lazy/refresh/error/empty states are understandable;
- no application-specific analytics assumptions have leaked into framework code;
- desktop and basic narrow layouts are usable;
- showcase visual acceptance is approved;
- focused and existing regression tests are green;
- Ruff, ty, diff check, full pytest/coverage, strict MkDocs, and artifact checks are green;
- the PR is reviewed and merged before UI-05B begins.
