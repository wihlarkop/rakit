# Plan 02 final whole-branch review fixes report

## Status and boundary

All findings in `plan-02-final-review-fixes.md` are implemented on
`worktree-plan-02-read-only-resources-ui`, starting from `7de96c0`. The public resource URL
contract remains unchanged. Core stays ORM/web-neutral, SQLAlchemy owns mapped-type conversion,
and web owns HTTP parsing/translation.

No authentication, write path, form mutation, relationship, upload, dashboard, or Plan 03 system
was added. Nothing was pushed, merged, tagged, or published.

## Preflight

- Starting HEAD: `7de96c0` (`fix(web): keep mounted controls and workspace boundary`).
- Starting branch/worktree: clean named branch in the existing linked worktree.
- Baseline: `uv run pytest` -> **257 passed in 13.87s**.
- The final-review plan, roadmap boundary, prior task reports, implementation, and existing tests
  were read before changes.

## Findings, root causes, and resolutions

### 1. UUID identities and safe identity errors

Root causes:

- core identity extraction accepted only integer/string values, so UUID model identities could not
  produce detail links;
- detail predicates used decoded URL text directly instead of the mapped column's Python type;
- malformed codec payloads could surface raw decoding/validation exceptions.

Resolution:

- canonical UUID values are lowercase hyphenated strings at `RecordIdentity` construction;
- the codec validates/copies the payload and exposes one controlled decode failure;
- SQLAlchemy validates exact identity shape and coerces integer, string, and UUID values before
  session creation;
- strict PostgreSQL compilation verifies correctly typed binds;
- malformed/wrong-shaped HTTP tokens return stable 400 responses with `Cache-Control: no-store`,
  while a valid absent identity remains a no-store 404.

### 2. Runtime-equivalent routes

Root cause: route registration compared only exact literal strings. A static segment could overlap
a dynamic segment, two differently named parameters could match the same request, and the built-in
home route was not represented in the compiled collision set.

Resolution: compilation compares path segments per HTTP method and includes a real `rakit.home`
`RouteDefinition`. Static-before-dynamic routes owned by the same resource remain valid to preserve
the existing `/_count` priority; dynamic-first, cross-owner, and dynamic/dynamic overlaps fail in
either registration order. Root resources now conflict with home during compilation.

### 3. Deep immutability

Root cause: a frozen Pydantic model protected attribute assignment but still aliased caller-owned
dict/list objects and exposed mutable nested values.

Resolution: identities and filters recursively copy/freeze mappings, sequences, and sets; `IN`
values are canonical immutable tuples. Caller mutation and direct nested mutation cannot alter the
model, while serialization and equality stay stable.

### 4. Stable pagination ordering

Root cause: the whitelist parser appended identity sorts, but a directly constructed
`ResourceQuery` could bypass it and reach SQLAlchemy without a deterministic tie-breaker.

Resolution: the adapter appends all missing identity columns to a local SQL ordering without
mutating the query and never duplicates an explicit identity sort. Duplicate-primary-sort paging
is stable under EXACT, DEFERRED, and DISABLED policies.

### 5. Query controls preserve validated state

Root cause: templates rebuilt controls from only a subset of values, losing repeated filters,
sorting, `per_page`, or count policy. Raw query reuse would also have retained unvalidated pairs.

Resolution: route helpers serialize only the parsed `ResourceQuery`, preserving repeated filters,
relevant explicit sorting, search, `per_page`, and count policy while deliberately removing only
`page`. Sort links and search forms work when followed in standalone and `/admin`-mounted apps;
unsafe reconstruction returns a controlled error.

### 6. Full-page table override parity

Root cause: the fragment route resolved template overrides, but the full page hard-coded the
generic `_table.html` include.

Resolution: the route resolves one selected table template and passes it to both full and fragment
rendering. Resource-specific and generic overrides now have the same precedence in both paths.

### 7. Accessible sort state

Root cause: raw internal `asc`/`desc` values were not valid `aria-sort` vocabulary, and default
adapter ordering was presented as if the user had selected it.

Resolution: explicit primary sort renders `ascending` or `descending`, an unsorted column renders
`none`, and a secondary explicitly sorted column renders `other`. Adapter/default identity ordering
does not appear selected.

### 8. Executable README contract

Root cause: the primary snippet omitted the production-safe secret placeholder and required
`ModelAdmin` resource metadata, so it did not compile against the public API.

Resolution: the snippet supplies `SecretValue` plus `resource_id`, `path`, `label`, and
`singular_label`. A smoke test extracts and executes that exact block with an in-memory mapped model
and engine, then compiles without starting a lifespan or opening a network/database connection.

### Related minor hardening

- SQLAlchemy `Enum` columns are excluded from generic search and covered by strict PostgreSQL
  compilation.
- duplicate same-direction explicit sorts are deterministic and deduplicated; contradictory
  directions are a controlled validation error at core and HTTP boundaries.
- `is_null` accepts only case-insensitive `true`/`false`; `1`, `yes`, empty, and arbitrary values
  fail before the service/data source runs.
- resource error pages consistently use `no-store` and stable messages without decoder, Pydantic,
  driver, or SQLAlchemy detail leakage.

## TDD evidence

| Wave | RED evidence | Focused GREEN |
| --- | --- | --- |
| Core identities/query values | 9 intended failures, 8 existing passes | 17 passed; full core 111 passed |
| SQLAlchemy identity/order/search | 10 intended failures, 35 passes | 45 passed; full SQLAlchemy 52 passed |
| Route collisions/home | 6 intended failures, 44 passes | 50 passed |
| Web controls/templates/errors | 14 intended failures, 20 passes | 34 passed; full web 102 passed |
| README contract smoke | 1 intended failure | 1 passed |

The first route-collision GREEN attempt also identified the intentional same-resource static
`/_count` route preceding the dynamic detail route. The collision rule was narrowed to that
router-priority case and the focused 50-test set then passed. The SQLAlchemy RED run included one
old assertion that expected mutable `IN` lists; its expected value was updated to the newly tested
immutable tuple contract before GREEN.

## Focused commits

- `134535c` `fix(core): freeze identities and query values`
- `371b2d4` `fix(sqlalchemy): coerce identities and stabilize paging`
- `0b83409` `fix(core): reject overlapping runtime routes`
- `652117d` `fix(web): preserve safe resource query state`
- `21a499c` `docs: make read-only example executable`
- final evidence/decision commit: this report, progress ledger, and decision record

## Final verification

All commands ran from the Plan 02 worktree after the implementation commits.

| Check | Result |
| --- | --- |
| `uv run pytest -p no:cacheprovider` | **302 passed in 14.29s** |
| `ruff format --check .` | **69 files already formatted** |
| `ruff check .` | **All checks passed** |
| `ty check` | **All checks passed** |
| `uv build --all-packages --out-dir C:\\tmp\\rakit-plan02-final-review-7de96c0-21a499c` | success |
| wheel/sdist enumeration | exactly **8 wheels + 8 sdists** |
| artifact version inspection | all **`0.1.0a1`** |
| typed-package inspection | `py.typed` present in every wheel and sdist |
| web-resource inspection | all 9 required resources present in wheel and sdist |
| minimal example `rakit check` / `rakit routes` | both exit 0; 4 compiled routes |
| FastAPI example `rakit check` / `rakit routes` | both exit 0; 4 routes and 1 plugin |
| `git diff --check 7de96c0..HEAD` | clean |

The nine web resources inspected in both artifact formats are the CSS asset, HTMX asset, HTMX
license, HTMX provenance, and the base/list/detail/`_table`/`_count` templates. The build output
directory was verified absent before the build and is outside the repository under `C:\\tmp`.

## Whole-diff self-review

- Reviewed the complete `7de96c0..HEAD` production/test/documentation diff, not only the last
  commit.
- No public resource path changed; list, count, and identity detail paths keep their prior forms.
- Core contains no SQLAlchemy or web dependency; mapped coercion remains in the adapter and HTTP
  handling remains in web.
- All SQL remains SQLAlchemy expression/bind based; no write session behavior was introduced.
- The virtual workspace still builds exactly the eight official distributions.
- The final diff contains no Plan 03 feature system and no generated build artifact.
- No unresolved correctness, security, architecture, test, or documentation concern remains in
  the requested scope.

## Final Important re-review follow-up: multi-column sort links

### Finding and root cause

For a request such as `sort=-name,email`, `_sort_headers()` derived accessibility state from the
normalized explicit sequence but serialized each link from only the clicked field. Clicking
`name`, `email`, or a new field therefore produced `sort=name`, `sort=email`, or `sort=id` and
discarded the rest of the user's ordering.

### Resolution

Commit `be4fec3` (`fix(web): preserve multi-column sort links`) toggles an already explicit field
at its existing sequence index and appends a newly clicked field. Every header serializes the
complete normalized explicit sequence plus validated repeated filters, search, `per_page`, and
count policy, while omitting only `page`.

The sequence is still derived from the raw request sort through `_explicit_sorting(...,
identity_fields=())`, not from the adapter-ready `ResourceQuery.sorting`. Consequently the
automatically appended identity tie-breaker is not presented as explicit URL state. Clicking the
identity header makes it explicit and appends it exactly once. No public URL shape or package
boundary changed.

### TDD evidence

- RED: the standalone and mounted tests both failed with `sort=name` where `sort=name,email` was
  required (**2 failed, 22 deselected**).
- Focused GREEN after implementation and formatting: **2 passed, 22 deselected**.
- Full query UI regression file: **24 passed in 0.94s**.
- Both tests start from `sort=-name,email`, inspect and follow links for the existing primary
  `name`, existing secondary `email`, and new/implicit-identity `id` cases. They also verify the
  mount prefix, repeated filter/search/per-page/count-policy preservation, and page omission.

### Final follow-up verification

- `uv run pytest packages/rakit-web/tests/test_query_ui.py -v`: **24 passed in 0.91s**.
- `uv run pytest -p no:cacheprovider`: **304 passed in 15.93s**.
- `ruff format --check .`: **69 files already formatted**.
- `ruff check .`: **All checks passed**.
- `ty check`: **All checks passed**.
- `git diff --check 7de96c0..HEAD`: clean after the evidence commit.
- final tracked worktree status: clean on `worktree-plan-02-read-only-resources-ui`.

## Exact locked-development gate follow-up: FastAPI type-check dependency

### Finding and root cause

`examples/fastapi_sqlalchemy/main.py` is part of repository-wide `ty check`, but FastAPI was
declared only in the root `examples` extra. After the exact clean-development command
`uv sync --all-packages --dev --locked`, `uv run ty check` could not resolve `fastapi` unless an
earlier environment happened to retain the optional extra.

### Resolution and boundary

The root workspace `[dependency-groups].dev` now also declares `fastapi>=0.116`. The existing
user-facing `project.optional-dependencies.examples` declaration remains intact because users who
run the FastAPI example still need that explicit install contract. `uv lock --offline` updated only
the two corresponding `rakit-workspace` dev metadata entries; it did not change the already locked
FastAPI version or any resolved package artifact.

No official package runtime dependencies changed. A regression test reads every
`packages/*/pyproject.toml` and rejects FastAPI in an official package's `project.dependencies`.
This is development tooling only, not a public wheel or Plan 03 dependency.

### TDD evidence

- RED:
  `uv run pytest tests/examples/test_read_examples.py -k "locked_development_environment or official_package_runtime_dependency" -v`
  -> **1 failed, 1 passed, 8 deselected**. The missing root dev declaration failed while the
  official-runtime-dependency boundary already passed.
- GREEN after the root declaration and intentional lock refresh: **2 passed, 8 deselected**.

### Exact clean-development sequence

- `uv sync --all-packages --dev --locked`: success; **40 packages resolved, 39 checked**.
- `uv run ruff format --check .`: **69 files already formatted**.
- `uv run ruff check .`: **All checks passed**.
- `uv run ty check`: **All checks passed**, without `--extra`.
- `uv run pytest -p no:cacheprovider`: **306 passed in 16.67s**, without `--extra`.

### Ordinary-wheel isolation proof

- Built all packages into a newly verified-absent temporary output directory: exactly the eight
  official wheels and eight sdists succeeded.
- Created a fresh isolated Python 3.12 environment and performed a normal dependency-resolving,
  offline install of `rakit-0.1.0a1-py3-none-any.whl` using the local official wheels. The install
  resolved **16 packages**; `rakit==0.1.0a1` imported and `fastapi` was absent.
- Inspected `METADATA` in all eight wheels: none contains FastAPI in `Requires-Dist`.
- `git diff 35814df -- packages/*/pyproject.toml` was empty, independently confirming that official
  package dependency declarations did not change.
