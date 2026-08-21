# Installation

Rakit requires Python 3.12 or newer.

Rakit uses ordinary Python package metadata, so standards-compliant package managers can install
it. First-party documentation and generated project guidance use [uv](https://docs.astral.sh/uv/)
as the canonical workflow.

Install the facade package without optional adapters:

```bash
uv add rakit
```

Add only the concrete implementations your application needs:

```bash
uv add "rakit[uvicorn]"
uv add "rakit[granian]"
uv add "rakit[sqlalchemy]"
uv add "rakit[auth-sqlalchemy]"
uv add "rakit[storage-local]"
```

The extra names are implementation-specific on purpose. Rakit does not silently choose a server,
persistence implementation, authentication backend, or storage provider for the application.

## Standard bundle

`rakit[standard]` is a server-neutral convenience bundle containing the current common Rakit
capabilities:

- SQLAlchemy persistence;
- SQLAlchemy authentication and durable idempotency;
- local private storage.

Choose the server explicitly:

```bash
uv add "rakit[standard,uvicorn]"
uv add "rakit[standard,granian]"
```

The standard bundle does not choose a database driver. Database engines and drivers remain
application-owned. For example, the generated SQLite starter uses `aiosqlite` explicitly:

```bash
uv add "rakit[standard,uvicorn]" aiosqlite
```

A PostgreSQL application may instead choose its own async driver:

```bash
uv add "rakit[standard,uvicorn]" asyncpg
```

The same rule applies to other SQLAlchemy-supported databases and drivers: Rakit owns the adapter
capability, while the application owns its database choice and connection configuration.

## Adapter imports

The facade keeps implementation-specific imports namespaced:

```python
from rakit.server.granian import GranianServer
from rakit.server.uvicorn import UvicornServer
from rakit.storage import FileStorage
from rakit.storage.local import LocalStorage
```

If an optional facade is imported without its implementation installed, Rakit reports the exact
canonical `uv add` command for that capability. It does not auto-install dependencies. A broken
transitive dependency inside an already-installed adapter is surfaced unchanged rather than being
misreported as a missing Rakit extra.

## Repository development

For repository development:

```bash
uv sync --all-packages --dev --locked
uv run rakit --help
```

Before serving an application, validate its compiled graph:

```bash
uv run rakit check myapp:admin
uv run rakit routes myapp:admin
```

`rakit check` fails closed when required adapter capabilities or configuration contracts are
missing.
