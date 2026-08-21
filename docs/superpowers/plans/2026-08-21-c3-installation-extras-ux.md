# C3 Installation & Extras UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize Rakit installation ergonomics so every optional capability has one canonical extra, `standard` is server-neutral, database drivers remain application-owned, runtime hints are actionable, and C2 scaffolding uses the same install vocabulary.

**Architecture:** Add a small internal `rakit._install` vocabulary that owns canonical extra identifiers plus deterministic requirement/`uv add` formatting. Package metadata remains static TOML; optional facades and C2 scaffolding consume the vocabulary, while regression tests later lock metadata/source consistency. `rakit._optional` continues to guard only genuinely missing top-level optional packages and preserves transitive import failures.

**Tech Stack:** Python 3.12+, Click facade package, PEP 621 optional dependencies, uv, TOML metadata, pytest, Ruff, ty, MkDocs.

**Spec:** `docs/superpowers/specs/2026-08-21-c3-installation-extras-ux-design.md`

## Global Constraints

- Rakit has not been publicly released; remove the unpublished `server-uvicorn` alias completely with no compatibility path.
- Canonical extras are exactly: `uvicorn`, `granian`, `sqlalchemy`, `auth-sqlalchemy`, `storage-local`, `standard`.
- `standard` explicitly contains `rakit-sqlalchemy`, `rakit-auth-sqlalchemy`, and `rakit-storage-local`; it contains no server and no database driver.
- Server choice is always explicit: `rakit[standard,uvicorn]` or `rakit[standard,granian]`.
- Database drivers such as `aiosqlite`, `asyncpg`, and `asyncmy` remain application-owned dependencies.
- First-party install UX uses `uv add`; Python package metadata remains standards-compliant and does not prohibit other package managers.
- Do not add `rakit install`, auto-install behavior, generic extras such as `auth`/`storage`/`persistence`, or a public capability registry.
- `_install` is internal in C3 and must not be re-exported from the public `rakit` facade.
- Canonical extras are deterministically ordered and deduplicated; known overlap is not an error, unknown/non-canonical identifiers are rejected.
- Missing top-level optional packages become `RakitOptionalDependencyError`; transitive import failures propagate unchanged.
- C2 scaffold file-safety, dry-run, collision, package-detection, and host-integration behavior must not change.
- Project workflow override: implement source first, perform manual/non-test verification next, add regression tests only after manual verification passes, then run full CI.
- No merge, release, tag, version bump, TestPyPI upload, PyPI publication, or workflow relaxation during implementation.

---

## File Structure

### Create

- `packages/rakit/src/rakit/_install.py` — canonical internal extra identifiers and deterministic formatting helpers.
- `packages/rakit/tests/test_install_ux.py` — focused C3 regression tests, added only after source/manual verification.

### Modify

- `packages/rakit/pyproject.toml` — remove `server-uvicorn`; make `standard` server-neutral.
- `packages/rakit/src/rakit/_optional.py` — consume typed install metadata and render capability-specific diagnostics.
- `packages/rakit/src/rakit/sqlalchemy.py` — use canonical SQLAlchemy install metadata.
- `packages/rakit/src/rakit/auth/sqlalchemy.py` — use canonical SQLAlchemy-auth install metadata.
- `packages/rakit/src/rakit/storage/local.py` — use canonical local-storage install metadata.
- `packages/rakit/src/rakit/server/uvicorn.py` — use canonical Uvicorn install metadata.
- `packages/rakit/src/rakit/server/granian.py` — use canonical Granian install metadata.
- `packages/rakit/src/rakit/scaffold/render.py` — use the canonical formatter for all four starter/server dependency combinations.
- `docs/getting-started/installation.md` — document canonical uv-first installation surface.
- `packages/rakit/tests/test_facade.py` — update existing optional-import regression expectations after source/manual verification.
- `packages/rakit/tests/test_b2_facades.py` — strengthen capability-specific diagnostic expectations after source/manual verification.
- `packages/rakit/tests/test_init_planner.py` — lock C2 generated requirement combinations after source/manual verification.
- `packages/rakit/tests/test_init_generated_projects.py` — keep generated-project composition aligned after source/manual verification.
- `CHANGELOG.md` — C3 closure after exact-head verification.
- `docs/roadmap.md` — mark C3 Complete and C4 Next only after exact-head verification.

---

### Task 1: Canonical packaging contract and install vocabulary

**Files:**
- Create: `packages/rakit/src/rakit/_install.py`
- Modify: `packages/rakit/pyproject.toml`

**Interfaces:**
- Produces: `InstallExtra` enum with values `STANDARD`, `UVICORN`, `GRANIAN`, `SQLALCHEMY`, `AUTH_SQLALCHEMY`, `STORAGE_LOCAL`.
- Produces: `rakit_requirement(*extras: InstallExtra) -> str`.
- Produces: `uv_add_command(*extras: InstallExtra, packages: tuple[str, ...] = ()) -> tuple[str, ...]`.
- Later tasks consume these helpers from `_optional.py` and `scaffold/render.py`.

- [ ] **Step 1: Update package metadata source-first**

Change `[project.optional-dependencies]` so it contains only the six canonical extras:

```toml
uvicorn = ["rakit-server-uvicorn==0.1.0a1"]
granian = ["rakit-server-granian==0.1.0a1"]
sqlalchemy = ["rakit-sqlalchemy==0.1.0a1"]
auth-sqlalchemy = ["rakit-auth-sqlalchemy==0.1.0a1"]
storage-local = ["rakit-storage-local==0.1.0a1"]
standard = [
    "rakit-sqlalchemy==0.1.0a1",
    "rakit-auth-sqlalchemy==0.1.0a1",
    "rakit-storage-local==0.1.0a1",
]
```

Remove `server-uvicorn` entirely and remove `rakit-server-uvicorn` from `standard`.

- [ ] **Step 2: Create the internal install vocabulary**

Implement `_install.py` with an enum and stable rank rather than accepting raw strings:

```python
from __future__ import annotations

from enum import Enum


class InstallExtra(str, Enum):
    STANDARD = "standard"
    UVICORN = "uvicorn"
    GRANIAN = "granian"
    SQLALCHEMY = "sqlalchemy"
    AUTH_SQLALCHEMY = "auth-sqlalchemy"
    STORAGE_LOCAL = "storage-local"


_EXTRA_ORDER = {
    InstallExtra.STANDARD: 0,
    InstallExtra.SQLALCHEMY: 1,
    InstallExtra.AUTH_SQLALCHEMY: 2,
    InstallExtra.STORAGE_LOCAL: 3,
    InstallExtra.UVICORN: 4,
    InstallExtra.GRANIAN: 5,
}


def _normalize_extras(extras: tuple[InstallExtra, ...]) -> tuple[InstallExtra, ...]:
    if any(not isinstance(extra, InstallExtra) for extra in extras):
        raise TypeError("Rakit install extras must use InstallExtra values")
    return tuple(sorted(set(extras), key=_EXTRA_ORDER.__getitem__))


def rakit_requirement(*extras: InstallExtra) -> str:
    normalized = _normalize_extras(extras)
    if not normalized:
        return "rakit"
    joined = ",".join(extra.value for extra in normalized)
    return f"rakit[{joined}]"


def uv_add_command(
    *extras: InstallExtra,
    packages: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return ("uv", "add", rakit_requirement(*extras), *packages)
```

Do not export these symbols from `rakit/__init__.py`.

- [ ] **Step 3: Source review**

Confirm by inspection that:

```text
rakit_requirement(STANDARD, UVICORN) -> rakit[standard,uvicorn]
rakit_requirement(UVICORN, STANDARD, STANDARD) -> rakit[standard,uvicorn]
rakit_requirement(STANDARD, GRANIAN) -> rakit[standard,granian]
uv_add_command(STANDARD, UVICORN, packages=("aiosqlite",))
    -> ("uv", "add", "rakit[standard,uvicorn]", "aiosqlite")
```

Do not add regression tests yet.

- [ ] **Step 4: Commit Task 1 source**

Commit only the metadata and `_install.py` changes with a focused message such as:

```text
feat: normalize Rakit installation extras
```

---

### Task 2: Capability-specific optional dependency diagnostics

**Files:**
- Modify: `packages/rakit/src/rakit/_optional.py`
- Modify: `packages/rakit/src/rakit/sqlalchemy.py`
- Modify: `packages/rakit/src/rakit/auth/sqlalchemy.py`
- Modify: `packages/rakit/src/rakit/storage/local.py`
- Modify: `packages/rakit/src/rakit/server/uvicorn.py`
- Modify: `packages/rakit/src/rakit/server/granian.py`

**Interfaces:**
- Consumes: `InstallExtra`, `uv_add_command` from `rakit._install`.
- Produces: `OptionalDependency` immutable metadata with `extra: InstallExtra` and `label: str`.
- Produces revised `require_module(module_name: str, *, dependency: OptionalDependency) -> ModuleType`.
- Produces revised `optional_import(module_name: str, *, dependency: OptionalDependency) -> Iterator[None]`.

- [ ] **Step 1: Replace raw extra strings with typed metadata**

Implement in `_optional.py`:

```python
from dataclasses import dataclass

from ._install import InstallExtra, uv_add_command


@dataclass(frozen=True, slots=True)
class OptionalDependency:
    extra: InstallExtra
    label: str


def _missing_message(dependency: OptionalDependency) -> str:
    command = " ".join(uv_add_command(dependency.extra))
    return (
        f"{dependency.label} support is not installed.\n\n"
        "Install it with:\n"
        f"    {command}\n"
    )
```

Update `require_module` and `optional_import` to use `_missing_message(dependency)` only when `exc.name == module_name`. Preserve the exact transitive-failure guard already present.

- [ ] **Step 2: Update all optional facade call sites**

Use these labels and extras:

```text
rakit_sqlalchemy        -> InstallExtra.SQLALCHEMY      / "SQLAlchemy"
rakit_auth_sqlalchemy   -> InstallExtra.AUTH_SQLALCHEMY / "SQLAlchemy authentication"
rakit_storage_local     -> InstallExtra.STORAGE_LOCAL   / "Local storage"
rakit_server_uvicorn    -> InstallExtra.UVICORN         / "Uvicorn"
rakit_server_granian    -> InstallExtra.GRANIAN         / "Granian"
```

Each facade should create one module-level `OptionalDependency` constant and pass it to `optional_import`.

- [ ] **Step 3: Preserve static typing and top-level guard behavior**

Keep the existing pattern where the optional top-level implementation package is guarded first, followed by unconditional statically typed imports. In particular, do not replace the facade imports with dynamic `import_module` lookups.

- [ ] **Step 4: Source review**

By inspection, verify expected message examples include:

```text
SQLAlchemy support is not installed.

Install it with:
    uv add rakit[sqlalchemy]
```

and equivalent canonical commands for auth/local-storage/Uvicorn/Granian. Confirm the command formatter is the only place constructing `rakit[...]` for runtime diagnostics.

- [ ] **Step 5: Commit Task 2 source**

Commit with a focused message such as:

```text
feat: standardize optional dependency diagnostics
```

---

### Task 3: Reuse install vocabulary from C2 scaffolding

**Files:**
- Modify: `packages/rakit/src/rakit/scaffold/render.py`

**Interfaces:**
- Consumes: `InstallExtra`, `rakit_requirement`, `uv_add_command` from `rakit._install`.
- Preserves existing public/internal scaffold functions: `_dependency_specs`, `dependency_command_for`, `dependency_action_for`.

- [ ] **Step 1: Replace handwritten Rakit requirement strings**

Refactor `_dependency_specs(config)` so it returns exactly:

```text
minimal + Uvicorn -> ("rakit[uvicorn]",)
minimal + Granian -> ("rakit[granian]",)
standard + Uvicorn -> ("rakit[standard,uvicorn]", "aiosqlite")
standard + Granian -> ("rakit[standard,granian]", "aiosqlite")
```

Build each Rakit requirement through `rakit_requirement(...)`.

- [ ] **Step 2: Reuse canonical uv command for existing-project mutation**

For existing projects, construct the dependency action from the same canonical extras and application packages rather than rebuilding `("uv", "add", ...)` independently. New projects continue to use `("uv", "sync")` because dependencies are already written into generated `pyproject.toml`.

A small internal helper in `render.py` may return `(extras, packages)` for a config so both `_dependency_specs` and existing-project command rendering share the same selection logic.

- [ ] **Step 3: Preserve C2 safety semantics**

Do not change planner/apply/command behavior, target-path rules, dry-run semantics, collision behavior, or dependency installation timing.

- [ ] **Step 4: Source review**

Inspect generated `pyproject.toml` rendering and existing-project `uv add` command construction for all four starter/server combinations. Confirm `aiosqlite` is present only for standard starters and outside the Rakit extra brackets.

- [ ] **Step 5: Commit Task 3 source**

Commit with a focused message such as:

```text
refactor: share install vocabulary with scaffolding
```

---

### Task 4: Normalize first-party installation documentation and perform source-first manual verification

**Files:**
- Modify: `docs/getting-started/installation.md`
- Inspect: generated README/help text in `packages/rakit/src/rakit/scaffold/render.py`
- No regression test additions in this task.

**Interfaces:**
- Documentation must match the six canonical extras and source behavior from Tasks 1-3.

- [ ] **Step 1: Rewrite canonical installation guidance**

The installation page must lead with uv:

```bash
uv add rakit
uv add "rakit[uvicorn]"
uv add "rakit[granian]"
uv add "rakit[sqlalchemy]"
uv add "rakit[auth-sqlalchemy]"
uv add "rakit[storage-local]"
uv add "rakit[standard,uvicorn]" aiosqlite
uv add "rakit[standard,granian]" asyncpg
```

Explain that extras are standard Python metadata, uv is the first-party canonical UX, `standard` is server-neutral, servers/drivers are explicit, and adapters are never activated implicitly.

- [ ] **Step 2: Remove unpublished legacy wording**

Search first-party source/docs for `server-uvicorn`. There must be no user-facing install example or metadata entry remaining. Any historical design/plan document that records past state may remain only if it is clearly historical; active source, active docs, tests, generated guidance, and packaging metadata must not use the alias.

- [ ] **Step 3: Perform manual metadata verification**

Read `packages/rakit/pyproject.toml` as TOML and verify the optional-dependency key set is exactly:

```python
{
    "uvicorn",
    "granian",
    "sqlalchemy",
    "auth-sqlalchemy",
    "storage-local",
    "standard",
}
```

Verify `standard` contains exactly the three Rakit capability distributions and no server/database driver.

- [ ] **Step 4: Perform manual install-vocabulary smoke**

Using the branch source without adding regression files yet, execute/import the helper and verify:

```python
assert rakit_requirement(InstallExtra.STANDARD, InstallExtra.UVICORN) == "rakit[standard,uvicorn]"
assert rakit_requirement(InstallExtra.UVICORN, InstallExtra.STANDARD, InstallExtra.STANDARD) == "rakit[standard,uvicorn]"
assert rakit_requirement(InstallExtra.STANDARD, InstallExtra.GRANIAN) == "rakit[standard,granian]"
assert uv_add_command(
    InstallExtra.STANDARD,
    InstallExtra.UVICORN,
    packages=("aiosqlite",),
) == ("uv", "add", "rakit[standard,uvicorn]", "aiosqlite")
```

Also deliberately pass a non-`InstallExtra` value and confirm it fails rather than rendering an arbitrary extra.

- [ ] **Step 5: Perform manual optional-facade diagnostics smoke**

For SQLAlchemy, SQLAlchemy auth, local storage, Uvicorn, and Granian, simulate the top-level implementation package being unavailable and confirm each facade emits its capability-specific `RakitOptionalDependencyError` with the canonical `uv add` command.

Separately simulate an installed fake optional module whose body imports a nonexistent transitive dependency; confirm the original `ModuleNotFoundError` propagates unchanged.

- [ ] **Step 6: Perform manual C2 dependency smoke**

Build dry-run/scaffold plans for:

```text
minimal/Uvicorn
minimal/Granian
standard/Uvicorn
standard/Granian
```

Confirm both new-project generated metadata and existing-project dependency commands match the table in the spec, with `aiosqlite` explicit for standard starters only.

- [ ] **Step 7: Review diff before tests**

Confirm source changes are limited to installation metadata/vocabulary, optional diagnostics/facades, scaffold dependency selection, and installation docs. Do not proceed to regression tests if manual verification exposes any mismatch.

- [ ] **Step 8: Commit docs/source-review state**

Commit with a focused message such as:

```text
docs: normalize installation guidance
```

---

### Task 5: Add C3 regression coverage after manual verification passes

**Files:**
- Create: `packages/rakit/tests/test_install_ux.py`
- Modify: `packages/rakit/tests/test_facade.py`
- Modify: `packages/rakit/tests/test_b2_facades.py`
- Modify: `packages/rakit/tests/test_init_planner.py`
- Modify: `packages/rakit/tests/test_init_generated_projects.py` only if existing assertions encode old standard/Uvicorn semantics.

**Interfaces:**
- Consumes final source behavior from Tasks 1-4.
- Tests must not introduce a second source of truth for ordering beyond expected public strings.

- [ ] **Step 1: Add install-vocabulary and metadata consistency tests**

In `test_install_ux.py`, parse `packages/rakit/pyproject.toml` with `tomllib` and assert:

```python
expected = {
    "uvicorn",
    "granian",
    "sqlalchemy",
    "auth-sqlalchemy",
    "storage-local",
    "standard",
}
assert set(optional_dependencies) == expected
assert "server-uvicorn" not in optional_dependencies
assert optional_dependencies["standard"] == [
    "rakit-sqlalchemy==0.1.0a1",
    "rakit-auth-sqlalchemy==0.1.0a1",
    "rakit-storage-local==0.1.0a1",
]
```

Import `InstallExtra`, `rakit_requirement`, and `uv_add_command` internally and assert deterministic order, deduplication, empty/base requirement behavior, application-package appending, and rejection of a raw string through a narrow type-ignore where necessary for the runtime guard test.

- [ ] **Step 2: Update optional dependency regression tests**

Replace old `extra="..."` calls in `test_facade.py` with `OptionalDependency(...)`. Assert both the capability-specific first line and exact canonical `uv add` requirement for SQLAlchemy, auth, local storage, Uvicorn, and Granian.

Keep the transitive-failure tests and confirm they still assert the original missing transitive module name and that the error is not `RakitOptionalDependencyError`.

Remove the regression that expects `server-uvicorn` because the alias no longer exists.

- [ ] **Step 3: Lock C2 dependency combinations**

Update `test_init_planner.py` so the four combinations assert exact dependency specs/commands:

```text
minimal/Uvicorn -> rakit[uvicorn]
minimal/Granian -> rakit[granian]
standard/Uvicorn -> rakit[standard,uvicorn] + aiosqlite
standard/Granian -> rakit[standard,granian] + aiosqlite
```

For existing-project mode, assert exact `uv add` argv order.

- [ ] **Step 4: Keep generated-project composition coverage valid**

Review `test_init_generated_projects.py`. Update only dependency-string assertions or generated metadata expectations that changed; preserve bootstrap, `rakit check`, permissions sync, and minimal starter behavioral coverage.

- [ ] **Step 5: Run focused C3 regressions**

Run the focused suite equivalent to:

```bash
uv run pytest \
  packages/rakit/tests/test_install_ux.py \
  packages/rakit/tests/test_facade.py \
  packages/rakit/tests/test_b2_facades.py \
  packages/rakit/tests/test_init_planner.py \
  packages/rakit/tests/test_init_generated_projects.py -v
```

Expected: all selected tests pass with no warnings/errors attributable to C3.

- [ ] **Step 6: Run repository formatting/lint/type checks before closure docs**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Expected: all commands exit successfully.

- [ ] **Step 7: Commit regression coverage**

Commit source-aligned tests with a focused message such as:

```text
test: cover C3 installation extras UX
```

---

### Task 6: Close C3 documentation and run exact-head full CI

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

**Interfaces:**
- Roadmap closure occurs only after source/manual/regression verification has passed.

- [ ] **Step 1: Update CHANGELOG Unreleased**

Record:

- six canonical implementation-specific extras;
- server-neutral `standard` bundle;
- explicit server/database-driver ownership;
- capability-specific missing-dependency hints;
- shared C2/runtime install vocabulary;
- removal of unpublished `server-uvicorn` alias.

Do not imply a release.

- [ ] **Step 2: Update canonical roadmap**

Change current position to:

```text
Phase C3 installation and extras UX | Complete
Phase C4 capability discovery       | Next
Phase C developer experience ...    | Next
```

Replace C3 planned language with the implemented contract and verification summary. Update near-term execution order so C4 is first.

- [ ] **Step 3: Run exact-head full repository CI**

Push the closure head and require the repository's canonical CI to pass all existing jobs:

```text
Python 3.12 test matrix: Ruff format, Ruff lint, ty, pytest
Python 3.13 test matrix: Ruff format, Ruff lint, ty, pytest
Python 3.14 test matrix: Ruff format, Ruff lint, ty, pytest
Dependencies (lowest-direct)
Dependencies (latest)
Plan 07 release gate: pytest --cov, mkdocs --strict, artifact checks
Artifact dry run
Web asset reproducibility
```

Do not claim C3 complete while any exact-head job is pending or failed.

- [ ] **Step 4: Audit final branch diff**

Compare `main...phase-c3-installation-extras-ux` and confirm:

- no workflow instrumentation remains;
- no release/version/tag change exists;
- no unrelated refactor is present;
- `server-uvicorn` is absent from active metadata/source/docs/tests;
- C3 source/tests/docs are the only intentional changes.

- [ ] **Step 5: Update draft PR status/body if one exists or create a draft PR**

The PR summary should record source-first manual verification and exact-head CI evidence. Keep it unmerged until explicit maintainer instruction.

---

## Plan self-review

### Spec coverage

- Canonical extras: Tasks 1 and 5.
- Server-neutral `standard`: Tasks 1, 3, 4, 5.
- Application-owned DB driver: Tasks 1, 3, 4, 5.
- uv-first but standards-compliant package metadata: Tasks 1 and 4.
- Shared internal install vocabulary: Tasks 1-3.
- Capability-specific diagnostics: Task 2 and Task 5.
- Transitive import failure passthrough: Tasks 2, 4, 5.
- C2 scaffold integration: Tasks 3-5.
- No installer CLI/capability registry: global constraints and audit.
- Source-first workflow: Tasks 1-4 before Task 5.
- C3 closure/C4 Next/full CI: Task 6.

### Placeholder scan

The plan contains no TBD/TODO/implementation-later placeholders. Every code-producing task names exact files, interfaces, expected strings, and verification behavior.

### Type consistency

The plan consistently uses:

```python
InstallExtra
OptionalDependency
rakit_requirement(*extras: InstallExtra) -> str
uv_add_command(*extras: InstallExtra, packages: tuple[str, ...] = ()) -> tuple[str, ...]
require_module(module_name: str, *, dependency: OptionalDependency) -> ModuleType
optional_import(module_name: str, *, dependency: OptionalDependency) -> Iterator[None]
```

These signatures are the implementation contract for C3 unless source inspection reveals a concrete type-checking conflict; any necessary adjustment must preserve the spec semantics and be documented in the execution state.