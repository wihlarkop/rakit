# Phase C2 — Project Initialization and Scaffolding Design

**Status:** Approved design

**Date:** 2026-08-21

## Summary

Phase C2 adds a first-party `rakit init` experience that takes a user from an installed Rakit CLI to a runnable/checkable project without requiring hand-copied repository examples. The initializer is intentionally conservative: it extends the existing Click CLI, is `uv`-only in C2 v1, supports interactive and deterministic non-interactive use, generates modern C1-style Rakit code, and never rewrites an existing host application's entrypoint.

The governing principle is:

> **Plan first, apply second.**

Prompts and flags normalize into one typed configuration. That configuration produces one deterministic scaffold plan containing rendered files, dependency actions, integration guidance, and next steps. Local conflicts are validated before mutation.

## Goals

C2 must provide:

1. `rakit init` as an interactive wizard.
2. Equivalent non-interactive flags for CI and automation.
3. A production-shaped `standard` starter using current Rakit ergonomics.
4. A lightweight `minimal` read-only starter.
5. New-project scaffolding.
6. Safe additive existing-project scaffolding.
7. `uv` dependency installation with exact retry guidance.
8. `--dry-run` with zero writes and zero subprocesses.
9. Fail-closed collisions and rerun-safe identical output.
10. Generated projects that can follow the existing `rakit check` and `rakit run` workflows.

## Non-goals

C2 v1 does not:

- support pip, Poetry, PDM, or another package-manager mutation path;
- rewrite FastAPI, Starlette, or another host entrypoint;
- infer writable CRUD/forms from arbitrary ORM models;
- infer or silently reuse an existing project's database/session configuration;
- define production migrations or generate a full Alembic project;
- generate Docker, deployment, CI, or infrastructure files;
- create a real `.env` or persist a generated production secret;
- introduce a public scaffold plugin registry;
- redesign Rakit extras naming (C3);
- introduce a second persistence adapter (later adapter work).

## Existing foundation

The top-level distribution already exposes:

```toml
[project.scripts]
rakit = "rakit.cli:cli"
```

Click is already a direct dependency, and `check`, `routes`, `run`, `createsuperuser`, and `permissions sync` already live under the same command group. C2 extends this CLI; it does not add a second executable/framework.

Current extras are reused exactly as they exist. In particular, `standard` currently combines SQLAlchemy, SQLAlchemy auth, local storage, and Uvicorn. Granian remains selectable through its current extra. C2 must not pre-empt C3's extras cleanup.

## Command surface

Canonical interactive use:

```bash
rakit init
```

Representative deterministic forms:

```bash
rakit init my-admin --template standard --server uvicorn --yes
rakit init my-admin --template minimal --server granian --yes
rakit init --existing . --template standard --yes
rakit init my-admin --template standard --dry-run
```

C2 v1 exposes:

- a project name for new-project mode;
- `--existing PATH` for existing-project mode;
- `--template [standard|minimal]`;
- `--server [uvicorn|granian]`;
- `--package PACKAGE` for explicit existing-project placement when detection is ambiguous;
- `--yes` to accept defaults and disable prompting;
- `--install/--no-install`;
- `--dry-run`.

`--yes` is automation-safe: if a required value cannot be derived safely, the command fails instead of prompting.

## Interactive flow

New project:

1. project name;
2. template (`standard` default);
3. server (`uvicorn` default);
4. install dependencies now (`yes` default).

Existing project:

1. target directory;
2. template (`standard` default);
3. server (`uvicorn` default);
4. package location only if it cannot be resolved safely;
5. install dependencies now (`yes` default).

`standard` and `minimal` are intentional bundles rather than arbitrary capability pickers in C2 v1:

- **standard**: SQLAlchemy persistence + SQLAlchemy auth + local storage + selected server;
- **minimal**: no persistence/auth/storage, read-only in-memory starter + selected server.

This avoids an unnecessary combination matrix before Rakit has multiple persistence/auth/storage adapters.

## Architecture

The CLI handler remains thin:

```text
rakit.cli
   │ prompts + Click parsing
   ▼
rakit.scaffold
   ├── InitConfig
   ├── detection
   ├── InitPlanner / ScaffoldPlan
   ├── renderers
   └── apply
```

A likely source layout is:

```text
packages/rakit/src/rakit/
├── cli.py
└── scaffold/
    ├── __init__.py
    ├── config.py
    ├── detect.py
    ├── plan.py
    ├── render.py
    └── apply.py
```

Exact filenames may move during implementation, but these responsibilities must stay separated.

### `InitConfig`

The normalized typed source of truth for one run. It contains resolved mode, target, distribution/import package names, template, server, install behavior, and dry-run behavior. No prompting occurs below the CLI layer.

### `InitPlanner` / `ScaffoldPlan`

The planner turns `InitConfig` into a deterministic plan before mutation. The plan records:

- every Rakit-owned file and rendered content;
- file status (`create`, `satisfied`, `conflict`);
- dependency command(s);
- server-specific command details;
- existing-project integration guidance;
- post-init instructions.

Planning may inspect the filesystem but performs no writes and invokes no external command.

### Renderers

Small focused renderers produce deterministic content from the normalized config. C2 does not create a public scaffold/template plugin API.

### Apply

Apply consumes a validated plan, creates local files, then optionally invokes `uv`. It tracks paths created by the current invocation so local write failures can clean up only those new paths.

Once external dependency installation starts, Rakit does not attempt speculative rollback of `uv` state.

## New-project output

### Standard starter

Expected shape:

```text
my-admin/
├── .env.example
├── .gitignore
├── .python-version
├── README.md
├── pyproject.toml
├── var/
│   └── .gitkeep
└── src/
    └── my_admin/
        ├── __init__.py
        ├── app.py
        ├── bootstrap.py
        ├── db.py
        ├── models.py
        └── resources.py
```

The starter uses SQLite/aiosqlite, SQLAlchemy-backed auth, local storage, and the selected server adapter. Runtime database/upload contents under `var/` are ignored.

It contains one simple SQLAlchemy-backed example resource using C1's declarative `ResourceWriteDefinition`, not a manually constructed mutation service. Its composition root uses the current public APIs:

- `SQLAlchemyPlugin`;
- `SQLAlchemyAuthPlugin`;
- `SQLAlchemyIdempotencyStore`;
- `LocalStoragePlugin` / `LocalStorage`;
- `Admin.on_startup`, `Admin.on_shutdown`, and `Admin.add_health_check` where appropriate.

No startup hook performs an implicit production migration. Startup may prepare Rakit-owned runtime directories; schema creation remains an explicit bootstrap action.

Local storage may be configured and ready even if the first sample domain does not need file upload. The sample should stay small rather than adding domain complexity only to exercise every capability.

### Minimal starter

Expected shape:

```text
my-admin/
├── .gitignore
├── .python-version
├── README.md
├── pyproject.toml
└── src/
    └── my_admin/
        ├── __init__.py
        └── app.py
```

It uses a small in-memory read-only resource patterned after the existing minimal example and installs only Rakit plus the selected server adapter.

## Generated package metadata

New projects use a conventional `src/` layout and Python 3.12 as the generated baseline because Rakit requires Python 3.12+.

The generated `pyproject.toml` is buildable/installable, not merely a dependency manifest. It may mirror the lightweight build-backend conventions already used by Rakit.

Dependency intent:

- standard + Uvicorn: current `rakit[standard]` + `aiosqlite`;
- standard + Granian: current SQLAlchemy/auth/local-storage/Granian extras + `aiosqlite`;
- minimal + Uvicorn: current `rakit[uvicorn]`;
- minimal + Granian: current `rakit[granian]`.

C2 uses current extra names exactly; C3 owns normalization.

## Naming

A project distribution/directory name may use a conventional hyphen such as `my-admin`. The import package is normalized to a valid identifier such as `my_admin`.

Names that cannot be normalized unambiguously or safely are rejected before mutation. Dry-run output includes the resolved import package.

## Existing-project mode

Existing-project support is **safe additive**.

It may:

- inspect `pyproject.toml` and conventional package layouts;
- add dependencies through `uv add` when installation is enabled;
- create only Rakit-owned module paths;
- print a precise host integration snippet.

It must not:

- rewrite a host entrypoint;
- modify arbitrary application modules;
- infer CRUD from host models;
- silently bind to/replace the host database or session factory;
- overwrite conflicting files.

### Standard existing-project isolation

`--template standard` inside an existing project remains self-contained by default. Because C2 explicitly refuses to infer the host database, the generated `rakit_admin` starter uses its own development SQLite database and Rakit-owned runtime data directory (for example `.rakit/`) until the developer deliberately replaces the generated DB/session composition with application-owned infrastructure.

The initializer does not create runtime `.rakit/` data during scaffolding; bootstrap/runtime code creates it when needed. Generated guidance tells the user that this directory is runtime data and should be ignored by their VCS. C2 does not silently edit an existing host `.gitignore`.

This makes existing-project mode runnable without pretending that Rakit understands the application's domain persistence.

### Package placement

Preferred:

```text
<repo>/src/<host_package>/rakit_admin/
```

Flat-package equivalent:

```text
<repo>/<host_package>/rakit_admin/
```

Resolution order:

1. explicit `--package`;
2. one unambiguous conventional `src/` package;
3. one unambiguous conventional flat package;
4. top-level `rakit_admin/` only for a clearly flat/non-package application and only if conflict-free;
5. otherwise prompt interactively or fail under `--yes` and require `--package`.

Detection prefers correctness over convenience. Ambiguous repositories are never guessed.

For standard existing-project mode, template-specific files (`db.py`, `models.py`, `resources.py`, `bootstrap.py`) live beneath the Rakit-owned `rakit_admin` namespace rather than being spread through host modules.

### Host integration

C2 v1 may recognize FastAPI and Starlette from project dependencies and print a precise mount snippet, conceptually:

```python
from my_app.rakit_admin.app import app as rakit_app

app.mount("/admin", rakit_app, name="rakit-admin")
```

The host file is never edited.

For an unrecognized framework, output stays framework-neutral and also provides the standalone `rakit run` command for the generated admin.

## Existing-project dependency mutation

When installation is enabled, host dependency editing is delegated to `uv add`; Rakit does not implement its own TOML dependency editor.

Example:

```bash
uv add "rakit[standard]" aiosqlite
```

or the current equivalent for the chosen template/server.

With `--no-install`:

- Rakit-owned files are generated;
- host `pyproject.toml` is not changed;
- the exact `uv add ...` command is printed.

If installation is enabled, an existing project must have a usable `pyproject.toml`. With `--no-install`, scaffolding may still proceed when package placement is otherwise resolvable.

## Secrets

C2 never writes a real production secret.

The standard new-project scaffold includes `.env.example` documenting:

```text
RAKIT_SECRET_KEY=<generate-a-real-secret>
```

`.env` is ignored. Generated code reads `RAKIT_SECRET_KEY` from the process environment and has no production-secret fallback.

`.env.example` is documentation only unless an explicit loader exists. Generated instructions must not imply that copying it to `.env` automatically loads it.

Existing-project mode keeps secret guidance under the Rakit-owned scaffold/readme surface and does not create or replace a host root `.env`/`.env.example` file.

## Database/bootstrap policy

The standard starter has an explicit development bootstrap module that creates the starter model tables and built-in auth tables. It does not define a production migration strategy.

Representative new-project flow:

```bash
uv run python -m my_admin.bootstrap
```

After bootstrap, the user can run the existing permission-sync and superuser commands.

Existing-project standard mode exposes the equivalent module path under its `rakit_admin` namespace.

Schema creation is always documented as starter/development bootstrap behavior, never as an implicit production migration policy.

## Dependency installation

C2 v1 is `uv`-only.

### New project

Dependencies are rendered into the new `pyproject.toml`. If installation is enabled, apply runs:

```bash
uv sync
```

in the generated project after successful local file creation.

### Existing project

If enabled, apply runs the planned `uv add ...` after successful local file creation.

### `uv` availability

For a **real apply** with dependency installation enabled, preflight checks that `uv` is available before any filesystem mutation. If it is missing, C2 fails with an actionable message and recommends `--no-install`.

`--dry-run` is different: it never requires `uv` to be installed. It reports the command that would run but does not resolve or execute the binary.

If a real `uv` invocation exits unsuccessfully, scaffold files remain in place. Rakit reports that scaffolding succeeded but installation failed and prints the exact retry command. Rakit does not attempt to roll back package-manager state.

## Dry-run

`--dry-run` performs detection, normalization, rendering, and local conflict analysis, then prints the plan.

It performs:

- zero file writes;
- zero directory creation;
- zero subprocesses;
- zero dependency mutation;
- no requirement that `uv` be installed.

Output includes:

- resolved mode/target;
- normalized package;
- template/server;
- files classified as create/satisfied/conflict;
- dependency command that would run;
- post-init/integration guidance.

A local conflict found during dry-run is reported as a failed plan rather than hidden.

## Safety and idempotence

Before any write, the complete planned file set is classified:

- **create** — absent;
- **satisfied** — present with byte-equivalent rendered content;
- **conflict** — present with different content or incompatible type.

Rules:

1. Any conflict aborts before apply.
2. C2 v1 has no `--force` overwrite.
3. Identical generated files are skipped and rerun-safe.
4. New-project target may be absent/empty or contain only the exact already-generated scaffold state. Arbitrary extra content makes new-project mode fail; users must choose existing-project mode deliberately.
5. Existing-project mode may contain arbitrary host files; only planned Rakit-owned destinations are collision checked.
6. Invalid names/options/package resolution fail before mutation.
7. A local render/write failure removes only files/directories created by that invocation, and directories only when empty. Pre-existing content is never deleted.
8. External package-manager state is never speculatively rolled back.

## Error reporting

Expected user/configuration mistakes become actionable Click errors, including:

- invalid project/package name;
- unsafe non-empty new-project target;
- ambiguous package (`--package` required);
- missing `pyproject.toml` when `uv add` is requested;
- generated-path collision;
- missing `uv` during real install apply;
- failed `uv` command with retry command;
- unsupported option combination.

Unexpected programming errors are not silently swallowed.

## Post-init experience

Standard new-project success output gives concrete next steps for:

1. entering the directory;
2. setting `RAKIT_SECRET_KEY`;
3. explicit development bootstrap;
4. `rakit check`;
5. permission synchronization;
6. superuser creation;
7. `rakit run ... --reload` using the selected server adapter.

Minimal projects omit auth/database steps.

Existing-project output additionally prints package placement and the host mount/integration snippet while making clear that no host source file was edited.

## Verification workflow

C2 follows the project's explicit **source-first** workflow:

1. implement source/scaffold behavior;
2. perform non-test/manual verification;
3. add regression/unit tests only after source behavior is stable;
4. run full repository CI last.

Manual/non-test verification must cover at least:

- interactive standard new project;
- non-interactive standard new project;
- minimal new project;
- Uvicorn vs Granian plan differences;
- existing-project additive mode;
- explicit `--package` placement;
- `--no-install`;
- `--dry-run` with no `uv` installed and zero mutation;
- identical rerun;
- collision fail-closed behavior;
- standard bootstrap + intended `rakit check` path;
- minimal `rakit check` path.

Regression tests should use Click `CliRunner`, temporary filesystems, and mocked subprocess boundaries where appropriate. Tests should assert behavior/contracts rather than snapshot every rendered byte unless exact content is the behavior under test.

Final verification uses the repository's complete quality gates at implementation time: supported Python matrix, Ruff formatting/lint, `ty`, pytest, dependency matrices, strict documentation build, artifact checks, and web asset reproducibility.

## Acceptance criteria

C2 is complete only when:

1. `rakit init` exists under the current Click CLI.
2. Interactive/non-interactive flows share one normalization/planning/apply path.
3. Standard/minimal starters generate deterministically.
4. Standard starter uses current C1 declarative CRUD/lifecycle ergonomics.
5. New projects use `uv` and the selected supported server.
6. Existing-project mode is additive, isolated by default, and never rewrites the host entrypoint or silently adopts host persistence.
7. `--dry-run` has zero mutation, zero subprocesses, and works without `uv` installed.
8. Conflicts fail before writes and identical output is rerun-safe.
9. Real install apply fails before writes when `uv` is unavailable.
10. Generated output has accurate next-step instructions and can follow the intended `rakit check` path once dependencies/environment are present.
11. Source-first manual verification precedes regression tests.
12. Full repository CI passes on the final implementation head.
13. No merge, release, tag, version bump, TestPyPI, or PyPI publication occurs merely because C2 is implementation-complete.

## Deferred follow-up

Evidence-driven later work may add:

- C3 extras/install vocabulary improvements;
- C4 capability discovery in CLI UX;
- adapter-provided scaffold metadata if Phase D demonstrates a real need;
- more persistence/auth/storage choices;
- more host-framework integration snippets;
- migration/bootstrap strategies beyond the development SQLite starter.

No public scaffold plugin API should be introduced until real adapters require it.