# Phase C2 — Project Initialization and Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-party, deterministic `rakit init` workflow that can create a new Rakit project or safely add an isolated Rakit admin module to an existing Python project.

**Architecture:** Extend the existing Click executable with a thin `init` command that normalizes interactive prompts and non-interactive flags into a typed `InitConfig`. A dedicated `rakit.scaffold` package plans every generated file and dependency action before mutation, renders standard/minimal starters deterministically, preflights conflicts, applies only Rakit-owned writes, and delegates dependency mutation to `uv`.

**Tech Stack:** Python 3.12+, Click, pathlib, dataclasses/enums, stdlib subprocess/shutil, existing Rakit public facades, SQLAlchemy/aiosqlite for the standard generated starter, `uv` for dependency installation.

**Spec:** `docs/superpowers/specs/2026-08-21-c2-project-initialization-scaffolding-design.md`

## Global Constraints

- C2 v1 is `uv`-only; do not add pip, Poetry, PDM, or package-manager abstraction.
- Interactive and non-interactive paths must normalize into the same typed configuration/planner/apply pipeline.
- `standard` is the default template: SQLAlchemy + isolated SQLite/aiosqlite + SQLAlchemy auth + local storage + one C1 declarative CRUD resource.
- `minimal` is read-only and omits persistence/auth/storage.
- Existing-project mode is safe additive and never rewrites the host entrypoint or silently adopts host persistence.
- `--dry-run` performs zero writes, zero directory creation, zero subprocesses, and must work when `uv` is not installed.
- Real apply with dependency installation enabled must verify `uv` before filesystem mutation.
- No `--force`; conflicting generated paths fail before writes. Byte-identical generated files are rerun-safe.
- A failed local write cleans up only paths created by that invocation. Failed `uv` execution leaves scaffold files in place and prints the retry command.
- New-project generated baseline is Python 3.12 with a `src/` package layout.
- Do not normalize/rename Rakit extras in C2; use the current extras exactly.
- Follow the project workflow for this phase: source implementation first, then non-test/manual verification, then regression/unit tests, then full CI.
- Do not merge, release, tag, version-bump, publish to TestPyPI/PyPI, or otherwise publish merely because C2 becomes implementation-complete.

---

## File Structure

Create a focused internal scaffolding package under the existing `rakit` distribution:

```text
packages/rakit/src/rakit/scaffold/
├── __init__.py       # internal exports used by command/tests
├── model.py          # typed normalized config, plan, file/dependency state
├── detection.py      # name/package/framework detection and validation
├── render.py         # deterministic generated file contents
├── planner.py        # InitConfig -> ScaffoldPlan and conflict classification
├── apply.py          # filesystem application + uv availability/execution
└── command.py        # Click-facing prompts/options/output only
```

Modify:

```text
packages/rakit/src/rakit/cli.py
```

only to register/import the new command and keep current commands unchanged.

Add regression coverage after source verification:

```text
packages/rakit/tests/test_init_detection.py
packages/rakit/tests/test_init_planner.py
packages/rakit/tests/test_init_apply.py
packages/rakit/tests/test_init_cli.py
packages/rakit/tests/test_init_generated_projects.py
```

Close documentation only after implementation verification:

```text
CHANGELOG.md
docs/roadmap.md
```

---

### Task 1: Typed scaffold contract and validation primitives

**Files:**
- Create: `packages/rakit/src/rakit/scaffold/__init__.py`
- Create: `packages/rakit/src/rakit/scaffold/model.py`
- Create: `packages/rakit/src/rakit/scaffold/detection.py`

**Interfaces:**
- Produces `InitMode`, `StarterTemplate`, `ServerAdapter`, `FileDisposition`, `InitConfig`, `PlannedFile`, `DependencyAction`, `ScaffoldPlan`, and `ApplyResult`.
- Produces `normalize_distribution_name(name: str) -> tuple[str, str]`, returning `(distribution_name, import_package)`.
- Produces `resolve_existing_package(root: Path, explicit_package: str | None, *, interactive: bool) -> PackageResolution` without mutation.
- Produces `detect_host_framework(pyproject_text: str | None) -> str | None` for only `fastapi` and `starlette`.

- [ ] **Step 1: Add the typed model layer**

Implement frozen/slots dataclasses and enums so later layers pass explicit values rather than loose dicts. The core shapes should be equivalent to:

```python
class InitMode(StrEnum):
    NEW = "new"
    EXISTING = "existing"

class StarterTemplate(StrEnum):
    STANDARD = "standard"
    MINIMAL = "minimal"

class ServerAdapter(StrEnum):
    UVICORN = "uvicorn"
    GRANIAN = "granian"

class FileDisposition(StrEnum):
    CREATE = "create"
    SATISFIED = "satisfied"
    CONFLICT = "conflict"

@dataclass(frozen=True, slots=True)
class InitConfig:
    mode: InitMode
    target: Path
    distribution_name: str | None
    import_package: str
    template: StarterTemplate
    server: ServerAdapter
    install_dependencies: bool
    dry_run: bool
    host_framework: str | None = None

@dataclass(frozen=True, slots=True)
class PlannedFile:
    path: Path
    content: str
    disposition: FileDisposition = FileDisposition.CREATE

@dataclass(frozen=True, slots=True)
class DependencyAction:
    argv: tuple[str, ...]
    cwd: Path

@dataclass(frozen=True, slots=True)
class ScaffoldPlan:
    config: InitConfig
    files: tuple[PlannedFile, ...]
    dependency_action: DependencyAction | None
    guidance: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ApplyResult:
    created: tuple[Path, ...]
    satisfied: tuple[Path, ...]
    dependency_command: tuple[str, ...] | None
```

Keep these internal to the scaffold package; do not export them from the root `rakit` facade.

- [ ] **Step 2: Implement new-project name normalization**

Accept conventional distribution names such as `my-admin` and normalize the import package to `my_admin`. Reject empty names, path separators, dotted traversal-like names, Python keywords, leading digits after normalization, and values that cannot become a valid identifier without ambiguous destructive rewriting.

- [ ] **Step 3: Implement conservative existing-package detection**

Detection order must match the spec: explicit package, exactly one conventional `src/<package>`, exactly one conventional flat package, clearly flat/non-package fallback to top-level `rakit_admin`, otherwise unresolved. Ignore hidden directories, build artifacts, virtual environments, and known tooling directories when identifying candidate packages.

- [ ] **Step 4: Implement host-framework detection**

Read dependency text only; recognize FastAPI first and Starlette second. Do not import or execute the host project. Unknown/absent dependency metadata returns `None`.

- [ ] **Step 5: Run source-only checks**

Run formatting/type/syntax checks limited to the new source files without adding tests yet:

```bash
uv run ruff format --check packages/rakit/src/rakit/scaffold
uv run ruff check packages/rakit/src/rakit/scaffold
uv run python -m compileall -q packages/rakit/src/rakit/scaffold
```

- [ ] **Step 6: Commit**

```bash
git add packages/rakit/src/rakit/scaffold
git commit -m "feat(cli): add C2 scaffold contracts and detection"
```

---

### Task 2: Deterministic standard/minimal renderers

**Files:**
- Create: `packages/rakit/src/rakit/scaffold/render.py`
- Modify: `packages/rakit/src/rakit/scaffold/__init__.py`

**Interfaces:**
- Consumes `InitConfig`.
- Produces `render_scaffold_files(config: InitConfig) -> tuple[PlannedFile, ...]`.
- Produces `dependency_action_for(config: InitConfig) -> DependencyAction | None`.
- Produces `guidance_for(config: InitConfig) -> tuple[str, ...]`.

- [ ] **Step 1: Render new-project package metadata**

Generate a buildable `pyproject.toml`, `.python-version`, `.gitignore`, and README. Use Python `>=3.12`. The selected current extras must be exact:

```text
standard + uvicorn -> rakit[standard] + aiosqlite
standard + granian -> rakit[sqlalchemy,auth-sqlalchemy,storage-local,granian] + aiosqlite
minimal + uvicorn  -> rakit[uvicorn]
minimal + granian  -> rakit[granian]
```

Do not redesign extras here.

- [ ] **Step 2: Render minimal new-project application**

Generate `src/<package>/__init__.py` and `app.py` with a tiny in-memory, read-only resource patterned after `examples/minimal`, exporting both `admin` and `app`. Keep the sample intentionally small and avoid importing SQLAlchemy/auth/storage.

- [ ] **Step 3: Render standard new-project application**

Generate:

```text
.env.example
var/.gitkeep
src/<package>/__init__.py
src/<package>/app.py
src/<package>/bootstrap.py
src/<package>/db.py
src/<package>/models.py
src/<package>/resources.py
```

The generated code must:

```python
# app.py conceptual composition
secret = os.environ["RAKIT_SECRET_KEY"]
auth = SQLAlchemyAuthPlugin(session_factory)
idempotency = SQLAlchemyIdempotencyStore(session_factory)
admin = Admin(
    ...,
    secret_key=SecretValue(secret),
    auth_backend=auth.auth_backend,
    session_store=auth.session_store,
    operation_idempotency_store=idempotency,
)
admin.install(SQLAlchemyPlugin(session_factory=session_factory))
admin.install(LocalStoragePlugin(storages=(LocalStorage(...),)))
admin.register(ItemAdmin)
admin.add_health_check(...)
admin.on_shutdown(dispose_database)
app = admin.asgi()
```

`resources.py` must use `ResourceWriteDefinition` with an explicit `FormSchema` and writable-field allowlist, not manual mutation-service wiring.

`bootstrap.py` must explicitly create both starter `Base.metadata` and built-in `AuthBase.metadata`; it must be documented as development bootstrap, not production migration.

- [ ] **Step 4: Render existing-project modules additively**

Generate only beneath the resolved Rakit-owned namespace. Minimal existing mode gets the minimal module surface; standard existing mode gets its own isolated `.rakit/` SQLite/runtime paths and the same C1 declarative CRUD shape. Do not generate/replace host root `.env`, `.env.example`, `.gitignore`, README, or entrypoint files.

- [ ] **Step 5: Render integration and post-init guidance**

For FastAPI/Starlette, print an exact mount snippet using the resolved import path. For unknown hosts, print standalone Rakit serve guidance. Standard guidance includes secret export, bootstrap, `rakit check`, permission sync, createsuperuser, and `rakit run`; minimal omits auth/bootstrap steps.

- [ ] **Step 6: Render dependency actions**

New project with install enabled plans `uv sync` in the target root. Existing project with install enabled plans the exact `uv add ...` command in the host root. `--no-install` plans no dependency subprocess but still emits the exact future command in guidance.

- [ ] **Step 7: Run source-only renderer inspection**

Use a temporary Python script or REPL invocation to instantiate representative `InitConfig` values and print rendered paths/content headers. Confirm no filesystem writes occur from rendering itself. Then run:

```bash
uv run ruff format --check packages/rakit/src/rakit/scaffold
uv run ruff check packages/rakit/src/rakit/scaffold
uv run python -m compileall -q packages/rakit/src/rakit/scaffold
```

- [ ] **Step 8: Commit**

```bash
git add packages/rakit/src/rakit/scaffold
git commit -m "feat(cli): render C2 project starters"
```

---

### Task 3: Planner, conflict preflight, and safe apply

**Files:**
- Create: `packages/rakit/src/rakit/scaffold/planner.py`
- Create: `packages/rakit/src/rakit/scaffold/apply.py`
- Modify: `packages/rakit/src/rakit/scaffold/__init__.py`

**Interfaces:**
- Consumes detection/rendering interfaces from Tasks 1–2.
- Produces `build_scaffold_plan(config: InitConfig) -> ScaffoldPlan`.
- Produces `classify_plan(plan: ScaffoldPlan) -> ScaffoldPlan`.
- Produces `apply_scaffold_plan(plan: ScaffoldPlan) -> ApplyResult`.
- Produces scaffold-specific expected-user exceptions that `command.py` can translate to `click.ClickException` without catching unexpected programming errors.

- [ ] **Step 1: Build plans before mutation**

`build_scaffold_plan` combines rendered files, dependency action, and guidance. It does not write or spawn subprocesses.

- [ ] **Step 2: Classify all planned paths**

For each planned file:

```python
if not path.exists():
    CREATE
elif path.is_file() and path.read_text(encoding="utf-8") == content:
    SATISFIED
else:
    CONFLICT
```

Also preflight the new-project root: arbitrary extra content outside the full generated file set makes new-project mode unsafe and must fail before apply. Existing mode only checks planned Rakit-owned destinations.

- [ ] **Step 3: Enforce `uv` availability only for real install apply**

Use `shutil.which("uv")` only when `plan.config.install_dependencies` is true and `plan.config.dry_run` is false. Missing `uv` becomes an actionable expected-user error before any write. Dry-run never performs this lookup as a requirement.

- [ ] **Step 4: Implement filesystem apply with local cleanup**

Create parent directories and only `CREATE` files. Skip `SATISFIED`. Track files and directories created during this invocation. If a local filesystem operation fails before dependency execution, remove only created files and empty created directories in reverse order; never remove pre-existing content.

- [ ] **Step 5: Execute dependency action without speculative rollback**

Call `subprocess.run(argv, cwd=cwd, check=False)` only after local file writes succeed. On nonzero exit, raise an expected-user install error that includes the exact retry command. Keep scaffold files in place.

- [ ] **Step 6: Run manual failure-path probes**

Without tests, use temporary directories to verify:

- conflict classification happens before writes;
- identical content becomes `SATISFIED`;
- dry-run planning works with `PATH` arranged so `uv` is absent;
- real install preflight rejects missing `uv` before writes;
- a deliberately failing filesystem write only removes run-owned paths.

- [ ] **Step 7: Run source-only quality checks and commit**

```bash
uv run ruff format --check packages/rakit/src/rakit/scaffold
uv run ruff check packages/rakit/src/rakit/scaffold
uv run python -m compileall -q packages/rakit/src/rakit/scaffold
git add packages/rakit/src/rakit/scaffold
git commit -m "feat(cli): plan and safely apply C2 scaffolds"
```

---

### Task 4: Click `rakit init` command and interactive/non-interactive normalization

**Files:**
- Create: `packages/rakit/src/rakit/scaffold/command.py`
- Modify: `packages/rakit/src/rakit/cli.py`

**Interfaces:**
- Consumes `InitConfig`, detection, planner, classifier, and apply functions.
- Produces a Click command object `init_command` registered beneath the existing `cli` group.

- [ ] **Step 1: Define the public command surface**

Implement equivalent Click options:

```text
rakit init [PROJECT_NAME]
  --existing PATH
  --template [standard|minimal]
  --server [uvicorn|granian]
  --package PACKAGE
  --yes
  --install / --no-install
  --dry-run
```

Reject mutually exclusive/unsupported combinations with actionable errors, including `PROJECT_NAME` together with `--existing` and `--package` in new-project mode.

- [ ] **Step 2: Normalize interactive new-project choices**

When values are missing and `--yes` is false, prompt in this order: project name, template (default standard), server (default uvicorn), install now (default yes). Use Click prompts only here; lower layers remain prompt-free.

- [ ] **Step 3: Normalize interactive existing-project choices**

Resolve target, template/server/install defaults, then package placement. If detection is ambiguous, prompt for package only in interactive mode. Under `--yes`, fail instead of prompting and explicitly request `--package`.

- [ ] **Step 4: Keep `--yes` fully non-interactive**

Defaults under `--yes` are standard + uvicorn + install. Any unresolved required value becomes an error rather than a prompt.

- [ ] **Step 5: Implement dry-run and success output**

Dry-run prints resolved config, each planned file disposition, dependency command, and guidance without calling apply. Real success prints created/satisfied counts plus the same next-step guidance. Make it explicit in existing mode that no host entrypoint was edited.

- [ ] **Step 6: Register without destabilizing existing CLI**

Keep `packages/rakit/src/rakit/cli.py` changes minimal, for example importing `init_command` and calling:

```python
cli.add_command(init_command)
```

Do not move or refactor unrelated existing commands.

- [ ] **Step 7: Manual CLI smoke before tests**

Run at least:

```bash
uv run rakit init demo-standard --template standard --server uvicorn --no-install
uv run rakit init demo-minimal --template minimal --server granian --no-install
uv run rakit init dry-demo --template standard --dry-run
```

and one interactive invocation in an isolated temp directory. Inspect generated paths and output manually, then delete only the temporary verification directories.

- [ ] **Step 8: Commit**

```bash
git add packages/rakit/src/rakit/cli.py packages/rakit/src/rakit/scaffold
git commit -m "feat(cli): add interactive rakit init"
```

---

### Task 5: Complete source-first manual/non-test verification matrix

**Files:**
- Source under verification only; do not add tests in this task.

**Interfaces:**
- Verifies the complete user-facing source behavior before regression tests are introduced.

- [ ] **Step 1: Verify new standard project non-interactively**

Generate with `--no-install`, inspect the full tree, confirm `pyproject.toml` dependencies, confirm no real secret is written, set `RAKIT_SECRET_KEY` in the process environment, and validate generated Python syntax with `compileall`.

- [ ] **Step 2: Verify new minimal project and server variation**

Generate minimal/Uvicorn and minimal/Granian plans, confirm only server dependency selection differs and no SQLAlchemy/auth/storage files leak into minimal.

- [ ] **Step 3: Verify existing-project additive placement**

Create temp host examples for conventional `src/` layout, flat package layout, and ambiguous multi-package layout. Confirm automatic placement only when unambiguous, `--package` resolves ambiguity, and no host source file is changed.

- [ ] **Step 4: Verify FastAPI/Starlette guidance**

Use host `pyproject.toml` fixtures in temporary directories and manually confirm framework recognition changes only the printed integration snippet.

- [ ] **Step 5: Verify dry-run zero mutation**

Run dry-run against absent and existing targets, snapshot directory listings before/after, arrange `PATH` so `uv` cannot be found, and confirm the command still returns a plan with zero created paths.

- [ ] **Step 6: Verify collision and rerun semantics**

Generate once, rerun unchanged and confirm files are satisfied/skipped. Then alter one generated Rakit-owned file and confirm the next run fails before touching any other planned file.

- [ ] **Step 7: Verify intended `rakit check` path using the workspace environment**

For generated projects created with `--no-install`, expose their `src/` directories to the current workspace Python environment (where Rakit packages are already installed), set `RAKIT_SECRET_KEY` for standard, run explicit standard bootstrap, then execute:

```bash
uv run rakit check <generated_package>.app:admin
```

Run the equivalent minimal `rakit check` without auth/bootstrap. This verifies generated composition without depending on public package publication.

- [ ] **Step 8: Fix source issues found by manual review, rerun affected probes, and commit fixes**

Use focused source commits with descriptive messages. Do not introduce regression tests until the source behavior is stable.

---

### Task 6: Regression coverage after source stabilization

**Files:**
- Create: `packages/rakit/tests/test_init_detection.py`
- Create: `packages/rakit/tests/test_init_planner.py`
- Create: `packages/rakit/tests/test_init_apply.py`
- Create: `packages/rakit/tests/test_init_cli.py`
- Create: `packages/rakit/tests/test_init_generated_projects.py`

**Interfaces:**
- Tests the contracts already stabilized by Tasks 1–5; no new product behavior should be invented here.

- [ ] **Step 1: Add detection/name tests**

Cover hyphen-to-underscore normalization, invalid names, unambiguous `src/` package, flat package, ambiguous package requiring explicit selection, and FastAPI/Starlette/unknown detection.

- [ ] **Step 2: Add planner/render tests**

Assert standard/minimal file sets, Uvicorn/Granian dependency commands, existing isolation paths, no host-root environment files, and deterministic repeated planning.

- [ ] **Step 3: Add apply safety tests**

Using `tmp_path`, assert `CREATE`/`SATISFIED`/`CONFLICT`, arbitrary-extra-content rejection in new mode, zero writes on conflict, identical rerun, missing-uv preflight before write, and subprocess failure retaining scaffold files. Mock only the `shutil.which`/subprocess boundary; keep filesystem behavior real.

- [ ] **Step 4: Add Click command tests with `CliRunner`**

Cover interactive standard defaults, fully non-interactive `--yes`, `--dry-run`, `--no-install`, existing ambiguous package failure under `--yes`, explicit `--package`, and mutual-exclusion errors. Assert `--yes` never emits a prompt.

- [ ] **Step 5: Add generated-project composition tests**

Generate standard/minimal projects with `--no-install` into temporary directories, prepend generated `src/` to `sys.path`, set the standard secret environment, import/compile `admin`, and invoke existing `rakit check` through `CliRunner`. For standard, run the generated bootstrap entrypoint or its async function against temp runtime paths before commands that require schema.

- [ ] **Step 6: Run focused regression suite**

```bash
uv run pytest \
  packages/rakit/tests/test_init_detection.py \
  packages/rakit/tests/test_init_planner.py \
  packages/rakit/tests/test_init_apply.py \
  packages/rakit/tests/test_init_cli.py \
  packages/rakit/tests/test_init_generated_projects.py -q
```

- [ ] **Step 7: Run existing CLI regression suite**

```bash
uv run pytest \
  packages/rakit/tests/test_cli.py \
  packages/rakit/tests/test_run_cli.py \
  packages/rakit/tests/test_auth_cli.py \
  packages/rakit/tests/test_capability_cli.py -q
```

- [ ] **Step 8: Commit tests only after behavior is stable**

```bash
git add packages/rakit/tests/test_init_*.py
git commit -m "test(cli): cover C2 project initialization"
```

---

### Task 7: Documentation closure and roadmap transition

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

**Interfaces:**
- Records C2 behavior already implemented and verified.
- Advances the canonical roadmap from C2 to C3 only after focused regression checks pass.

- [ ] **Step 1: Update changelog**

Under Unreleased, document `rakit init`, standard/minimal starters, interactive + automation-safe flags, additive existing-project mode, uv-only install behavior, dry-run, and fail-closed collision/rerun semantics.

- [ ] **Step 2: Close C2 in roadmap**

Mark C2 Complete, summarize the concrete shipped behavior, and mark C3 Installation & Extras UX as Next. Preserve the separate no-release/publication decision.

- [ ] **Step 3: Verify docs locally**

```bash
uv run mkdocs build --strict
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/roadmap.md
git commit -m "docs: close C2 and advance roadmap to C3"
```

---

### Task 8: Final repository-wide verification

**Files:**
- No intentional source changes unless a quality gate reveals a real defect.

**Interfaces:**
- Proves the final C2 head against all repository quality gates before completion is claimed.

- [ ] **Step 1: Run formatting/lint/type checks**

Use the repository's current canonical commands/CI equivalents for Ruff formatting, Ruff lint, and `ty` across supported packages.

- [ ] **Step 2: Run full pytest on supported Python matrix**

Verify Python 3.12, 3.13, and 3.14 using the same CI workflow/matrix already required by the repository.

- [ ] **Step 3: Run dependency compatibility gates**

Verify lowest-direct and latest-allowed dependency jobs.

- [ ] **Step 4: Run release-quality non-publication gates**

Verify coverage, `mkdocs build --strict`, `scripts/check_artifacts.py`, official artifact dry-run, and generated web/CSS reproducibility exactly as the repository CI defines them.

- [ ] **Step 5: Inspect final diff and branch scope**

Confirm the branch contains only C2 design/plan/source/tests/docs, with no temporary verification workflow/files, release metadata changes, tags, or publication actions.

- [ ] **Step 6: Record final exact-head evidence**

Capture final commit SHA and all successful CI run/job results. Do not merge until the maintainer explicitly requests merge.
