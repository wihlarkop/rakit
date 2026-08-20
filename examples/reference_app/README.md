# Rakit reference application

This is the realistic Phase B backoffice application used to validate Rakit as a coherent product through its public APIs.

It intentionally goes beyond the isolated examples elsewhere in `examples/`: one application composes SQLAlchemy persistence, built-in authentication, RBAC, CRUD forms, optimistic concurrency, relationships, private file storage, filters and search, record and bulk actions, custom pages, dashboard widgets, generated REST reads, lifecycle initialization, and readiness checks.

## Run from the repository

The repository development environment already provides the SQLite async driver used by this example.

```bash
uv run python -m examples.reference_app
```

Then open `http://127.0.0.1:8000`.

The development database and uploaded files are created under `.rakit-reference/` by default. Set `RAKIT_REFERENCE_ROOT` to use another location.

For an application outside this repository, install Rakit plus an async SQLite driver, for example:

```bash
uv add "rakit[standard]" aiosqlite
```

`RAKIT_REFERENCE_SECRET` may override the deterministic development signing secret. The built-in default exists only so this checked-in example is immediately runnable; a real deployment must supply its own persistent secret and should not copy the example's `debug=True` setting.

## Demo accounts

Both seeded users use the password `rakit-demo-password`.

| User | Purpose |
| --- | --- |
| `admin@example.com` | Superuser for the complete application surface. |
| `operator@example.com` | Limited operations role for realistic permission boundaries. |

The operator can read the commerce resources, update products and orders, view the operations page, and execute the two order actions. Create/delete capabilities remain unavailable to that role.

## What to exercise

- `/` — dashboard with eager and lazy widgets.
- `/customers` — searchable/filterable read-only customer resource.
- `/products` — product CRUD, optimistic concurrency, private image upload, search, and filters.
- `/orders` — order CRUD, customer relationship metadata, record action, and bulk action.
- `/order-items` — related transactional records.
- `/operations` — application-owned custom page rendered through Rakit.
- `/api/customers`, `/api/products`, `/api/orders` — generated authenticated REST read endpoints.
- `/_system/health` and `/_system/ready` — lifecycle and database readiness surfaces.

The product upload field accepts PNG, JPEG, and WebP files up to 2 MiB. Files are private and stored by `rakit.storage.local`; only the portable `StoredFile` descriptor is persisted in the application table.

## Why the example owns some code

Rakit is not a universal ORM or domain layer. The application therefore owns:

- its SQLAlchemy models and migrations/bootstrap metadata;
- the JSON SQLAlchemy type used to persist a portable `StoredFile` descriptor;
- order-transition domain logic;
- dashboard queries and page content;
- its choice of SQLite and its driver.

Rakit owns the admin compiler/runtime, authentication/session contracts, authorization, form transport, CSRF/submission protection, optimistic-concurrency token handling, resource/query UI, action transport, generated REST transport, storage contract, and lifecycle orchestration.

The record and bulk order actions deliberately use `TransactionPolicy.DISABLED`: `DomainActionExecutor` cannot claim participation in Rakit's root persistence unit of work, so those handlers explicitly own their short SQLAlchemy transactions. CRUD forms, by contrast, use `SQLAlchemyMutationService` and Rakit's existing mutation pipeline.

## Data safety

Bootstrap is additive and idempotent for development. It creates missing tables and seed records but does not reset existing data. Delete `.rakit-reference/` when you intentionally want a fresh local dataset.

This example is a development/reference artifact, not a production deployment template.
