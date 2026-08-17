# Installation

Rakit requires Python 3.12 or newer.

Install the facade package first:

```bash
pip install rakit
```

Add extras only for the capabilities your application needs. The current alpha exposes extras for
SQLAlchemy, built-in SQLAlchemy auth, and the standard server/runtime bundle through the `rakit`
package metadata. Check your lockfile after selecting extras; adapters are explicit and Rakit does
not silently install an ORM or authentication backend.

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
