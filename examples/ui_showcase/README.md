# UI Showcase

`examples/ui_showcase` is the visual QA application for Rakit's default admin UI. It intentionally uses the framework's shipped templates, assets, and `.rakit-*` primitives without a private stylesheet.

The example is both a realistic commerce/operations application and a deterministic visual baseline for the UI/UX Maturity program.

## Run locally

```powershell
uv sync --extra examples
uv run python -m examples.ui_showcase.main
```

Open `http://127.0.0.1:8000`.

Demo credentials:

```text
Email: operator@example.com
Password: demo-password
```

## What to inspect

The showcase exposes six read-only resources with deterministic data:

- `/customers` — long labels, optional values, segments, owners, and statuses
- `/products` — catalog names, categories, SKUs, lifecycle statuses, and prices
- `/orders` — 32 records for pagination, search/filter/sort, mixed statuses, and totals
- `/categories` — compact master-data presentation
- `/inventory` — numeric stock levels plus healthy/low/out-of-stock states
- `/teams` — people-oriented operational data

Additional surfaces:

- `/` — commerce operations dashboard with summary and recent-order widgets
- `/ui-lab` — deterministic component/state inspection surface for typography, buttons, fields, statuses, feedback, tables, relationships, empty/loading/error states, and theme behavior
- Orders declare `customer` and `products` relationship contracts for later relationship-UX work
- Orders expose a `refund_order` record action using Rakit's real preview + confirmation pipeline as a baseline for later action-UX work
- `/auth/login` — successful and invalid-credential states using the development-only demo backend

## UI-05E filter rail acceptance

Use `/orders`, `/products`, and `/inventory` together when reviewing resource filtering:

- `/orders` exercises text, choice, and date-range controls in the default rail;
- `/products` intentionally exposes five filter groups so automatic group collapse is visible, and its Category filter has ten choices so `Show more`/`Show less` behavior can be inspected;
- `/products` also uses the public Web presentation override to show five Category choices before disclosure;
- `/inventory` exercises a custom semantic `ResourceFilter` whose friendly selection resolves to backend-neutral predicates;
- on desktop, verify the right rail, group dividers, Hide/Show filters, active chips, and table expansion;
- on tablet/mobile, verify the no-JavaScript fallback and the enhanced filter drawer;
- clearing one filter or all filters must not unexpectedly hide the filtering surface.

The UI Lab is a baseline, not a separate theme. If it needs styling that the default Rakit UI does not provide, the framework UI should be improved in a later UI maturity PR instead of adding showcase-only CSS.
