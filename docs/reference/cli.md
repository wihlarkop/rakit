# CLI

The `rakit` command loads application targets in `module:attribute` form. The current working
directory is added to the import path consistently so local application modules work through the
console script on Windows and Linux.

## Validate

```bash
rakit check myapp:admin
```

Compiles the target, reports route/plugin counts and capability diagnostics, and exits non-zero for
invalid configuration.

## Inspect routes

```bash
rakit routes myapp:admin
```

Prints compiled HTTP methods, paths, and stable route names.

## Run

```bash
rakit run myapp:admin --server uvicorn --host 127.0.0.1 --port 8000 --workers 1
```

`--reload` and `--log-level` are available when supported by the selected server adapter.

## Built-in SQLAlchemy auth utilities

```bash
rakit createsuperuser myapp:admin --email admin@example.com
rakit permissions sync myapp:admin
```

These commands require the SQLAlchemy/auth capability in the target application. Password input is
prompted rather than accepted as a command-line argument.
