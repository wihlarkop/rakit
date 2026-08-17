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

The UI Lab is a baseline, not a separate theme. If it needs styling that the default Rakit UI does not provide, the framework UI should be improved in a later UI maturity PR instead of adding showcase-only CSS.
