# C3 Installation & Extras UX Design

Date: 2026-08-21
Status: Approved design, pending implementation plan
Branch: `phase-c3-installation-extras-ux`
Base: `main` at `7bf5cd45eebf1b3e58cf9a69d854dd82d6c4531d`

## Context

Phase C2 added `rakit init` and exposed a concrete installation inconsistency: `rakit[standard]` currently includes Uvicorn, so a standard starter with Uvicorn can depend on `rakit[standard]`, while the equivalent Granian starter must expand the bundle manually as `rakit[sqlalchemy,auth-sqlalchemy,storage-local,granian]`.

Rakit has not been publicly released yet. C3 therefore optimizes for a clean first-release installation contract rather than preserving pre-release compatibility aliases.

## Goals

C3 makes optional capability installation predictable and consistent across package metadata, runtime missing-dependency errors, generated C2 projects, and first-party documentation.

The acceptance criteria are:

1. every current optional capability has exactly one canonical extra name;
2. `standard` is server-neutral and does not include a database driver;
3. server selection is always explicit;
4. database drivers remain application-owned;
5. runtime install hints and C2 scaffold dependency strings use one canonical internal vocabulary;
6. no unpublished legacy extra aliases remain;
7. Rakit does not add an installer CLI or hide package-manager behavior;
8. malformed optional installations continue to fail honestly rather than being misreported as a missing Rakit extra.

## Canonical extras

The public optional-dependency surface is:

- `rakit[uvicorn]`
- `rakit[granian]`
- `rakit[sqlalchemy]`
- `rakit[auth-sqlalchemy]`
- `rakit[storage-local]`
- `rakit[standard]`

The unpublished `server-uvicorn` alias is removed completely.

Names remain implementation-specific rather than generic capability aliases. This keeps backend choice explicit and scales to future adapter work without redefining ambiguous names such as `auth`, `storage`, or `persistence`.

## `standard` contract

`rakit[standard]` is a convenience bundle for the current common application capabilities only. It contains these Rakit distributions explicitly:

- `rakit-sqlalchemy`
- `rakit-auth-sqlalchemy`
- `rakit-storage-local`

Even though `rakit-auth-sqlalchemy` currently depends transitively on `rakit-sqlalchemy`, `standard` lists both intentionally. The bundle contract describes the capabilities it promises rather than relying on incidental transitive dependency structure.

`standard` does not include Uvicorn or Granian. Server selection is explicit:

```bash
uv add "rakit[standard,uvicorn]"
uv add "rakit[standard,granian]"
```

`standard` also does not include `aiosqlite`, `asyncpg`, `asyncmy`, or any other database driver. Driver choice belongs to the application:

```bash
uv add "rakit[standard,uvicorn]" aiosqlite
uv add "rakit[standard,uvicorn]" asyncpg
uv add "rakit[standard,granian]" asyncmy
```

SQLite remains the C2 standard starter's development database, so that generated starter adds `aiosqlite` explicitly rather than inheriting it from `rakit[standard]`.

## Package-manager policy

Python extras remain ordinary package metadata and are not intentionally restricted to uv. Users may technically install Rakit with any standards-compliant Python package manager.

First-party DX uses uv as the canonical documented workflow:

```bash
uv add "rakit[sqlalchemy]"
```

C3 does not add commands such as `rakit install`, does not wrap dependency resolution, and does not introduce automatic capability activation. Capability inspection and richer diagnostics remain C4 work.

## Canonical install vocabulary

Add a small internal module, `rakit._install`, as the single runtime/source-code vocabulary for current user-facing extras and install command formatting.

The module is internal and is not exported as a public API in C3. It owns typed identifiers equivalent to:

```text
SQLALCHEMY      -> sqlalchemy
AUTH_SQLALCHEMY -> auth-sqlalchemy
STORAGE_LOCAL   -> storage-local
UVICORN         -> uvicorn
GRANIAN         -> granian
STANDARD        -> standard
```

It also owns deterministic helpers for:

- formatting one or more extras into a canonical requirement string, for example `rakit[standard,uvicorn]`;
- formatting the canonical `uv add` command;
- optionally appending application-owned packages such as `aiosqlite` without treating them as Rakit extras.

Extra ordering is deterministic. Bundle plus server examples must render as `standard,uvicorn` and `standard,granian`, not whichever order individual callers happen to supply. Repeated canonical extras are deduplicated. Known overlapping combinations are not rejected merely because one bundle currently contains another capability; for example, `standard` plus `sqlalchemy` normalizes deterministically rather than creating a special compatibility rule. Non-canonical or unknown identifiers are rejected rather than silently rendered into a requirement string.

The packaging declaration in `packages/rakit/pyproject.toml` remains normal static TOML. C3 does not generate packaging metadata from Python. Regression coverage instead verifies that every canonical user-facing extra represented by `_install` exists in package metadata and that removed unpublished aliases do not.

## Runtime missing-dependency diagnostics

`rakit._optional` continues to provide the guard used by optional facade modules, but callers stop passing free-form raw extra strings.

Each guarded optional facade provides canonical install metadata plus a human-readable capability label. Expected error shape:

```text
SQLAlchemy support is not installed.

Install it with:
    uv add "rakit[sqlalchemy]"
```

Equivalent diagnostics apply to SQLAlchemy auth, local storage, Uvicorn, and Granian.

The existing safety behavior is preserved: the friendly Rakit error is emitted only when the optional top-level package itself is absent. If that package is installed but one of its own transitive dependencies is missing or broken, the original import exception propagates unchanged. Rakit must not misdiagnose a broken installed adapter as merely an uninstalled extra.

## C2 scaffold integration

C2 no longer hand-builds public extra combinations independently of the runtime install vocabulary.

Generated dependency requirements become:

| Starter | Server | Rakit requirement | Application dependency |
| --- | --- | --- | --- |
| minimal | Uvicorn | `rakit[uvicorn]` | none |
| minimal | Granian | `rakit[granian]` | none |
| standard | Uvicorn | `rakit[standard,uvicorn]` | `aiosqlite` |
| standard | Granian | `rakit[standard,granian]` | `aiosqlite` |

For new projects these values are written to generated `pyproject.toml`, followed by the existing optional `uv sync` behavior.

For existing projects the same dependency set is used to produce `uv add ...` commands. C3 does not change C2's file-safety, dry-run, conflict, or host-integration semantics.

## Documentation

First-party installation documentation is normalized around uv and the canonical extras. It must explain:

- base installation versus optional capabilities;
- server-neutral `standard` semantics;
- explicit server choice;
- explicit database-driver ownership;
- implementation-specific extra naming;
- no implicit adapter activation.

Examples using the removed `server-uvicorn` alias must disappear from source, tests, and docs.

C2 generated README/install guidance must use the same canonical combinations.

## Scope boundaries

C3 does not:

- add new persistence, auth, storage, or server adapters;
- add generic aliases such as `auth`, `storage`, or `persistence`;
- add a package installer command;
- inspect the environment to recommend capabilities dynamically;
- change SQLAlchemy database support semantics;
- bundle a database driver into `standard`;
- preserve compatibility for unpublished extra names;
- create a public capability registry.

Those concerns either belong to C4 or later adapter phases.

## Failure behavior

Expected user-facing failures stay actionable and fail closed:

- missing optional implementation package -> `RakitOptionalDependencyError` with one canonical `uv add` command;
- installed optional implementation whose dependency graph is broken -> original import exception;
- non-canonical install vocabulary input -> rejected by the typed/install-formatting helper rather than silently producing an unknown extra;
- repeated canonical extras -> deduplicated with deterministic ordering;
- generated C2 dependency output -> deterministic and derived from the canonical install vocabulary.

No runtime auto-installation is attempted.

## Verification strategy

The implementation follows the project's source-first workflow:

1. implement package metadata, install vocabulary, diagnostics, facades, scaffold integration, and docs source;
2. perform non-test/manual verification before adding C3 regression tests;
3. add focused regression tests only after source/manual review passes;
4. run full repository CI last.

Manual/non-test verification should cover at minimum:

- inspection of package metadata for the exact six canonical extras;
- absence of `server-uvicorn` from first-party source/docs;
- deterministic requirement formatting for single extras and `standard` plus either server;
- generated C2 standard/minimal dependency output for Uvicorn and Granian;
- missing optional facade diagnostics for all current optional implementations;
- preservation of transitive import failures;
- generated standard starter retaining explicit `aiosqlite` ownership.

Regression coverage should lock:

- package metadata and internal vocabulary consistency;
- standard server-neutral membership;
- removal of the unpublished alias;
- canonical formatting, deduplication, and ordering;
- friendly optional dependency messages;
- transitive failure passthrough;
- C2 new/existing dependency combinations.

Full CI must include the existing Python 3.12/3.13/3.14 matrices, Ruff format/lint, `ty`, pytest/coverage, lowest-direct/latest dependency matrices, strict MkDocs, artifact validation/dry-run, and web asset reproducibility.

## Roadmap closure

Once implementation and exact-head verification pass, update CHANGELOG and the canonical roadmap so:

- C3 is Complete;
- C4 Capability discovery becomes Next.

No merge, release, tag, version bump, TestPyPI upload, or PyPI publication is implied by C3 completion.