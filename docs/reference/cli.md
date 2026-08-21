# CLI

The `rakit` command loads application targets in `module:attribute` form. The current working
directory is added to the import path consistently so local application modules work through the
console script on Windows and Linux.

## Validate

```bash
rakit check myapp:admin
```

Compiles the target, reports route/plugin counts and capability diagnostics, and exits non-zero for
invalid configuration. Capability validation evaluates the complete requirement graph first, so one
run reports every missing capability requirement instead of stopping at the first failure.

## Inspect capabilities

```bash
rakit capabilities myapp:admin
rakit capabilities --installed
rakit capabilities myapp:admin --installed
```

`rakit capabilities` is an inspector rather than a validator. A target whose capability graph is
under-provisioned is still inspectable and is reported as `invalid`; use `rakit check` when a
non-zero validation exit is required.

Configured application state and installed environment state are intentionally separate. An
installed integration is never treated as active simply because its package is present.

Machine-readable output is available with `--json`:

```bash
rakit capabilities myapp:admin --json
```

The C4 JSON contract uses `schema_version: 1` and deterministic ordering. See
[Capability Discovery](../guides/capability-discovery.md) for the configured/installed model and
first-party integration ids.

## Inspect routes

```bash
rakit routes myapp:admin
```

Prints compiled HTTP methods, paths, and stable route names.

## Run

```bash
rakit run myapp:admin --server uvicorn --host 127.0.0.1 --port 8000 --workers 1
```

`--reload` and `--log-level` are available when supported by the selected server adapter. Missing
first-party server adapters use the same canonical `uv add` installation vocabulary as the rest of
Rakit's optional-dependency diagnostics.

## Built-in SQLAlchemy auth utilities

```bash
rakit createsuperuser myapp:admin --email admin@example.com
rakit permissions sync myapp:admin
```

These commands require the SQLAlchemy/auth capability in the target application. Password input is
prompted rather than accepted as a command-line argument.
