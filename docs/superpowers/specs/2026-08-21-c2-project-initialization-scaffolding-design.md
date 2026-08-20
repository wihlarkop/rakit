# Phase C2 — Project Initialization and Scaffolding Design

**Status:** Approved design

**Date:** 2026-08-21

## Summary

Phase C2 adds a first-party `rakit init` experience that takes a user from an installed Rakit CLI to a runnable/checkable project without requiring them to hand-copy repository examples. The initializer is intentionally conservative: it generates a small, production-shaped Rakit application, uses the existing Click CLI, is `uv`-only in C2 v1, supports both interactive and deterministic non-interactive operation, and never rewrites an existing host application's entrypoint.

The core design principle is:

> **Plan first, apply second.**

Interactive prompts and command-line flags both normalize into the same typed configuration. That configuration produces one deterministic scaffold plan containing files, dependency actions, integration guidance, and next steps. All local conflicts are validated before filesystem writes begin.

## Goals

C2 must provide:

1. A `rakit init` interactive wizard for human use.
2. Equivalent non-interactive flags for CI, scripts, and repeatable automation.
3. A `standard` starter that demonstrates the modern Rakit composition path introduced through Phase C1.
4. A smaller `minimal` starter for users who only need a lightweight/read-only starting point.
5. New-project scaffolding into a new or previously generated project directory.
6. Safe additive scaffolding inside an existing Python project.
7. `uv`-based dependency installation and exact retry instructions.
8. `--dry-run` planning with zero writes and zero subprocesses.
9. Fail-closed collision handling and rerun-safe handling of identical generated files.
10. Generated code that is checkable through the existing `rakit check` command and runnable through an installed Rakit server adapter.

## Non-goals

C2 v1 does not:

- support pip, Poetry, PDM, Hatch environment management, or arbitrary package-manager mutation;
- rewrite a user's FastAPI, Starlette, or other host application entrypoint;
- infer writable forms or CRUD semantics from arbitrary ORM models;
- infer or reuse an existing project's database configuration automatically;
- generate a full Alembic project or define a production migration strategy;
- generate Docker, deployment, CI, or infrastructure files;
- create a real `.env` file or persist a generated production secret;
- introduce a public scaffold plugin registry;
- normalize or redesign Rakit extras naming, which remains Phase C3 work;
- add a second persistence adapter, which remains later adapter-ecosystem work.

## Existing foundation

The top-level `rakit` distribution already exposes the CLI as:

```toml
[project.scripts]
rakit = "rakit.cli:cli"
```

The package already depends on Click, and existing commands such as `check`, `routes`, `run`, `createsuperuser`, and `permissions sync` live under the same command group. C2 extends this command group; it does not add a second executable or CLI framework.

Current extras are reused as they exist today. In particular, the `standard` extra already combines SQLAlchemy, SQLAlchemy auth, local storage, and Uvicorn. Granian remains selectable through its current extra. C3 may improve the public extras vocabulary later without making C2 depend on that redesign.

## User-facing command surface

The canonical command is:

```bash
rakit init
```

Representative deterministic forms are:

```bash
rakit init my-admin --template standard --server uvicorn --yes
rakit init my-admin --template minimal --server granian --yes
rakit init --existing . --template standard --yes
rakit init my-admin --template standard --dry-run
```

C2 v1 exposes the following concepts:

- project name for new-project mode;
- `--existing PATH` to select existing-project mode;
- `--template [standard|minimal]`;
- `--server [uvicorn|granian]`;
- `--package PACKAGE` for explicit existing-project package placement when detection is ambiguous;
- `--yes` to accept defaults and disable interactive prompting;
- `--install/--no-install`, with install enabled by default in the interactive flow;
- `--dry-run` to render the complete plan without writes or subprocesses.

`--yes` is explicitly automation-safe: it must not unexpectedly fall back to an interactive prompt. If a required value cannot be derived safely, the command fails with an actionable message.

## Interactive flow

The wizard and flag-based path are two front ends over the same configuration model.

For a new project, the wizard asks for:

1. project name;
2. starter template (`standard` by default);
3. server adapter (`uvicorn` by default);
4. whether dependencies should be installed now (`yes` by default).

For an existing project, it asks for:

1. target directory;
2. starter template (`standard` by default);
3. server adapter (`uvicorn` by default);
4. package location only when it cannot be resolved safely;
5. whether dependencies should be installed now (`yes` by default).

The `standard` and `minimal` templates are intentional bundles in C2 v1 rather than arbitrary combinatorial capability pickers. The standard bundle fixes SQLAlchemy persistence, SQLAlchemy-backed auth, and local storage. The minimal bundle omits persistence/auth/storage and remains read-only. Server selection is independent because both Uvicorn and Granian are already supported server adapters.

This keeps C2 small and deterministic. Future adapter growth can justify richer capability selection later.

## Architecture

The command handler remains thin. Scaffolding logic lives outside `rakit.cli` so the existing CLI does not become a monolith.

Conceptually:

```text
rakit.cli
   │
   │ prompts + Click option parsing
   ▼
rakit.scaffold
   ├── InitConfig
   ├── InitPlanner
   ├── renderers
   └── apply
```

### `InitConfig`

`InitConfig` is the normalized, typed source of truth for one initializer run. It contains only resolved choices, such as:

- mode: new or existing;
- target directory;
- project distribution name where relevant;
- import package/module location;
- template;
- server adapter;
- install-dependencies boolean;
- dry-run boolean.

Prompting never leaks into planner or renderer code.

### `InitPlanner`

`InitPlanner` converts `InitConfig` into a deterministic `ScaffoldPlan` before mutation begins.

The plan records:

- every file expected to be created or already satisfied;
- the exact rendered content for Rakit-owned files;
- dependency action(s);
- selected server command details;
- existing-project integration guidance;
- post-init commands.

The planner is pure with respect to external mutation. Filesystem inspection used for preflight/detection is allowed, but planning does not write files or invoke `uv`.

### Renderers

Rendering is based on the normalized configuration, not on ad-hoc prompt branches. Small focused renderer functions own generated file content. C2 does not create a public template/plugin protocol.

This avoids duplicating entire template directories for every server/mode combination while keeping generated output easy to inspect in source control.

### Apply step

The apply layer consumes a validated `ScaffoldPlan` and performs filesystem creation followed by optional dependency installation. It tracks files/directories created by the current run so it can clean them up if a local filesystem write fails before dependency installation begins.

External package-manager rollback is not attempted. Once `uv` is invoked, any `uv` mutation is treated as owned by `uv`; Rakit reports the failure and prints the exact retry command.

## New-project output

### Standard starter

The standard starter is a small standalone Rakit application using SQLAlchemy, SQLite/aiosqlite, SQLAlchemy-backed Rakit auth, local storage, and the selected server adapter.

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

`var/` is the development data root and is ignored except for a placeholder when necessary. The generated SQLite database and local uploads are runtime artifacts, not source-controlled data.

The generated starter contains one simple SQLAlchemy-backed example resource. That resource uses the C1 declarative write API (`ResourceWriteDefinition`) rather than manually constructing a mutation service. The composition root uses:

- `SQLAlchemyPlugin`;
- `SQLAlchemyAuthPlugin`;
- `SQLAlchemyIdempotencyStore`;
- `LocalStoragePlugin`/`LocalStorage`;
- `Admin.on_startup`, `Admin.on_shutdown`, and `Admin.add_health_check` where lifecycle hooks are needed.

The starter therefore teaches the current public ergonomic path rather than preserving old boilerplate patterns.

The storage adapter may be configured and ready even if the first sample resource does not require file upload; C2 does not need to make the sample domain artificially complex just to exercise every installed capability.

### Minimal starter

The minimal starter is intentionally smaller:

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

It uses a small in-memory read-only resource patterned after the current minimal example and depends only on Rakit plus the selected server adapter. It does not install SQLAlchemy auth/storage extras.

## Generated package metadata

New projects use a normal `src/` layout and Python 3.12 as the generated baseline because Rakit itself requires Python 3.12 or newer.

The generated `pyproject.toml` is buildable/installable rather than being only a dependency manifest. C2 may use the same lightweight build backend conventions already used by Rakit itself.

Dependency intent is:

- standard + Uvicorn: current `rakit[standard]` plus `aiosqlite`;
- standard + Granian: current SQLAlchemy/auth/local-storage/Granian extras plus `aiosqlite`;
- minimal + Uvicorn: current `rakit[uvicorn]`;
- minimal + Granian: current `rakit[granian]`.

C2 must use the repository's current extra names exactly. Renaming or consolidating them belongs to C3.

## Names and package derivation

A new project's human-facing distribution/directory name may contain a conventional hyphen, for example `my-admin`. The generated Python import package is normalized to a valid identifier, for example `my_admin`.

The initializer rejects names that cannot be normalized unambiguously or that would create an invalid/import-unsafe package. It must report the normalized import package before apply in dry-run output.

## Existing-project mode

Existing-project support is explicitly **safe additive**.

It may:

- inspect `pyproject.toml` and directory structure;
- add Rakit dependencies through `uv add` when installation is enabled;
- create Rakit-owned modules/files;
- print an exact host integration snippet.

It must not:

- rewrite an existing FastAPI/Starlette entrypoint;
- modify arbitrary application modules;
- infer writable CRUD from host ORM models;
- replace an existing database/session configuration;
- overwrite conflicting user files.

### Package placement

Preferred output is:

```text
<repo>/src/<host_package>/rakit_admin/
    __init__.py
    app.py
    ...template-specific files...
```

For a flat package layout, the equivalent is:

```text
<repo>/<host_package>/rakit_admin/
```

Resolution order is:

1. explicit `--package` if supplied;
2. an unambiguous import package detected from a conventional `src/` layout;
3. an unambiguous conventional flat package;
4. a top-level `rakit_admin/` only when the repository is clearly a flat/non-package application and the location is conflict-free;
5. otherwise prompt in interactive mode or fail under `--yes` with a request for `--package`.

Detection must prefer correctness over convenience. Ambiguous repositories are never guessed.

### Host framework integration

Existing-project mode may inspect dependencies to recognize a small known set of host frameworks. C2 v1 should provide precise mount guidance for FastAPI and Starlette when detected.

For example, generated guidance may conceptually look like:

```python
from my_app.rakit_admin.app import app as rakit_app

app.mount("/admin", rakit_app, name="rakit-admin")
```

The actual host file is not edited.

For an unrecognized host, C2 prints a framework-neutral statement plus the standalone Rakit run command. The generated Rakit ASGI app remains directly serveable.

## Existing-project dependencies

When installation is enabled, dependency mutation is delegated to `uv add`; Rakit does not implement a TOML dependency editor for host projects.

Representative commands are:

```bash
uv add "rakit[standard]" aiosqlite
```

or the equivalent current-extra combination for Granian/minimal.

When `--no-install` is selected:

- generated Rakit-owned files are still written;
- the host `pyproject.toml` is not changed;
- the exact `uv add ...` command is printed for later execution.

This cleanly separates scaffolding from dependency mutation and avoids duplicating package-manager semantics.

## Secrets and environment configuration

C2 never writes a real production secret.

The standard scaffold includes `.env.example` documenting:

```text
RAKIT_SECRET_KEY=<generate-a-real-secret>
```

`.env` is ignored. The generated application reads `RAKIT_SECRET_KEY` from the process environment and does not contain a fallback production secret.

The generated README must accurately explain how to provide the variable before commands that compile/run the authenticated standard app. `.env.example` is documentation; C2 must not imply that `.env` is automatically loaded unless the generated project explicitly includes such a loader.

## Database/bootstrap policy

The standard starter uses a development SQLite database under a local data root such as `var/app.db`.

C2 does not define production migrations. Instead it generates an explicit development bootstrap module/function that can create the starter application's SQLAlchemy tables and the built-in auth tables.

A representative next step is:

```bash
uv run python -m my_admin.bootstrap
```

After bootstrap, users can use existing Rakit commands such as permission synchronization and superuser creation.

Schema creation must be clearly described as development/bootstrap behavior, not as an implicit production migration policy.

## Dependency installation

C2 v1 is `uv`-only.

### New project

The generated `pyproject.toml` already contains the selected dependencies. If install is enabled, apply runs:

```bash
uv sync
```

inside the generated project after file creation succeeds.

### Existing project

If install is enabled, apply runs the planned `uv add ...` command after Rakit-owned files are created.

### `uv` availability

If dependency installation is requested and `uv` is not available, preflight fails before filesystem mutation and explains that the user can rerun with `--no-install`.

If a real `uv` invocation later exits unsuccessfully, generated scaffold files remain in place. Rakit reports that scaffolding succeeded but installation failed and prints the exact retry command. It does not attempt speculative rollback of host dependency-manager state.

## Dry-run behavior

`--dry-run` performs detection, normalization, rendering, and conflict analysis, then prints the plan.

It performs:

- zero filesystem writes;
- zero directory creation;
- zero `uv` subprocesses;
- zero dependency mutation.

The output should include enough information to be useful in CI/review:

- resolved mode and target;
- normalized Python package;
- template and server;
- files that would be created, skipped as identical, or conflict;
- dependency command that would run;
- post-init/integration guidance.

A conflict found during dry-run is still reported as a failed plan rather than being hidden.

## Safety and idempotence

Before any write, C2 preflights the complete planned file set.

Each planned file is classified as:

- **create** — path does not exist;
- **satisfied** — path exists and content is byte-for-byte equivalent to the rendered Rakit-owned content;
- **conflict** — path exists with different content or incompatible type.

Rules:

1. Conflicts abort before apply.
2. No `--force` overwrite exists in C2 v1.
3. Identical Rakit-owned files are rerun-safe and skipped.
4. A new-project target may be absent/empty, or may contain only the exact already-generated scaffold state. Arbitrary extra content makes new-project mode fail rather than silently treating the directory as an existing project.
5. Existing-project mode may naturally contain arbitrary host files; only planned Rakit-owned destinations are conflict checked.
6. Invalid names/options/package resolution fail before mutation.
7. If a local render/write failure occurs during apply before dependency installation, C2 removes only files/directories created by that invocation, and only removes directories when they are empty. Pre-existing user content is never deleted.
8. Once external dependency installation begins, Rakit does not attempt to roll back `uv` state.

## Error reporting

Initializer failures should be actionable Click errors rather than raw tracebacks for expected user mistakes.

Important error classes/messages include:

- invalid project/package name;
- target directory is not safe for new-project mode;
- ambiguous existing package; use `--package`;
- missing `pyproject.toml` when dependency mutation requires one;
- conflicting generated path;
- `uv` unavailable while installation requested;
- `uv` command failed, with retry command;
- unsupported option combination.

Unexpected programming/runtime errors continue to surface normally during development rather than being swallowed.

## Post-init experience

After successful standard new-project creation, C2 prints concise concrete next steps. The exact commands depend on package/server selection but should cover:

1. entering the project directory;
2. configuring `RAKIT_SECRET_KEY`;
3. running the explicit development bootstrap;
4. validating with `rakit check`;
5. synchronizing permissions / creating a superuser when auth is enabled;
6. starting with `rakit run ... --reload` and the selected server adapter.

Minimal projects omit auth/database steps.

Existing-project output additionally prints the detected host integration snippet but does not pretend it was applied automatically.

## Source layout inside Rakit

The exact internal filenames can be refined during implementation, but responsibilities must remain separated. A likely layout is:

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

`cli.py` owns user interaction only. Detection, normalization, planning, rendering, and application remain independently understandable/testable units.

## Verification workflow

The project workflow for C2 remains source-first:

1. implement source/scaffold behavior first;
2. perform non-test/manual verification;
3. add regression/unit tests only after source behavior is stable;
4. run full repository CI last.

Manual/non-test verification must exercise at least:

- interactive standard new project;
- non-interactive standard new project;
- minimal new project;
- Uvicorn and Granian planning/install command differences;
- existing-project additive mode;
- explicit `--package` placement;
- `--no-install`;
- `--dry-run` zero-mutation behavior;
- rerun of identical generated output;
- collision fail-closed behavior;
- generated standard project bootstrap/check path;
- generated minimal project `rakit check` path.

Regression coverage should use Click's `CliRunner`, temporary filesystems, and mocked subprocess boundaries where appropriate. It should test behavior rather than snapshot every byte of every template unless exact generated content is itself the contract.

Final quality gates remain the repository-wide matrix, including supported Python versions, Ruff formatting/lint, `ty`, pytest, dependency matrices, strict docs build, artifact checks, and web asset reproducibility as configured by the repository at implementation time.

## Acceptance criteria

Phase C2 is complete when all of the following are true:

1. `rakit init` exists under the current Click CLI.
2. Interactive and non-interactive flows share one normalized planning/apply path.
3. Standard and minimal starters can be generated deterministically.
4. Standard starter uses current C1 declarative CRUD/lifecycle ergonomics.
5. New projects use the `uv` workflow and selected supported server adapter.
6. Existing-project mode is additive and never rewrites the host entrypoint.
7. `--dry-run` performs zero mutation.
8. Conflicts fail before writes and identical generated files can be safely rerun.
9. Missing `uv` fails before writes when installation is requested.
10. Generated projects have accurate next-step instructions and can pass the intended `rakit check` flow after required dependencies/environment are present.
11. Source-first manual verification is completed before regression tests are added.
12. Full repository CI passes on the final implementation head.
13. No release, tag, version bump, TestPyPI/PyPI publication, or merge is performed merely as part of C2 completion; those remain explicit maintainer decisions.

## Deferred follow-up

C2 intentionally leaves future extension points evidence-driven. Likely later work includes:

- C3 extras/install vocabulary cleanup;
- C4 capability discovery surfaced through CLI UX;
- adapter-provided scaffold metadata if Phase D proves a real need;
- additional persistence/auth/storage choices;
- additional host-framework integration snippets;
- migration/bootstrap strategies beyond the development SQLite starter.

No public scaffold plugin API should be introduced until those needs exist in real adapters.