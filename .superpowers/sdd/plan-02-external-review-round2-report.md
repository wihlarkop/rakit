# Plan 02 external review round 2 report

## Scope and provenance

- Starting clean HEAD: `25304bc`
- Implementation commits:
  - `7cdf81c feat(core): compile fail-closed resource policies`
  - `7d9c04f fix(sqlalchemy): map attributes and validate identities`
  - `c53764d feat(rakit): export Plan 02 core contracts`
  - `cc07343 feat(web): add accessible resource pagination`
- No Plan 03 authentication, permission, write, or public URL-contract work was introduced.
- `uv.lock` was intentionally unchanged.

## 1. Fail-closed policy and datasource compilation

RED established five policy/datasource compilation failures, one sensitive-field HTML exposure,
and three direct SQLAlchemy policy bypasses. GREEN added frozen `ResourceFieldPolicy` declarations,
explicit field groups on `ResourceAdmin`, immutable compilation, datasource association and
validation, policy-driven web rendering/query controls, and independent adapter enforcement.

Focused evidence:

- policy/datasource validation matrix: 26 passed
- sensitive UI non-exposure: 1 passed
- direct SQLAlchemy bypass protection: 3 passed
- affected core/SQLAlchemy/web/example regression: 301 passed
- Ruff and ty: passed

## 2. SQLAlchemy mapped attributes and identity types

RED established five intended failures: renamed PK/regular attributes leaked database names,
unsupported identity types were claimed, and composite identity rejection was not explicit.
GREEN metadata records mapped attribute name, database column name, and column type separately and
uses mapper attributes for every ORM lookup. Integer/BigInteger, String-compatible, UUID, and safe
`TypeDecorator` wrappers are accepted; unsupported and composite identities use the stable
`config.unsupported_identity` boundary.

Focused evidence:

- metadata/plugin identity matrix: 15 passed
- renamed PK/column end-to-end list/detail/filter/sort/search/identity link: 1 passed
- PostgreSQL compilation used database `id`/`name` while API policy used
  `user_id`/`display_name`
- direct database-column-name bypass returned safe `RakitError`, never `AttributeError`
- broad SQLAlchemy/web regression: 190 passed
- Ruff and ty: passed

## 3. `rakit.core` facade

RED was exactly two import failures. GREEN exports identity-preserving Plan 02 identity, query,
datasource, policy, pagination, and resource-service contracts without importing optional
SQLAlchemy support. Runtime identity and fresh-import tests passed 12/12. The all-package build test
verified `rakit/py.typed`, performed a normal offline install into an isolated virtual environment,
and imported the complete facade from the installed wheel with SQLAlchemy absent/not loaded.

## 4. Accessible pagination

RED was exactly six failures for missing controls: standalone and `/admin` mounted applications
across exact, deferred, and disabled count policies. GREEN was 6/6 and the full query UI file was
30/30. Each mode verifies first page (Previous absent), middle page (Previous and Next present),
and last page (Next absent), labelled navigation, `aria-current`, repeated filters, search,
complete `-name,email` explicit multi-sort, `per_page`, count policy, ASGI root path, and that links
change only `page`. Every generated ordinary anchor was followed successfully without JavaScript.

Pagination and deferred-count URLs now share a canonical serializer whose inputs are the validated
`ResourceQuery` and validated explicit sort metadata; rejected raw query pairs are not reflected.

## 5. Final verification

The complete required sequence was run from committed documentation HEAD
`091cd9beb791f62e4471b0d1695dea85b9029288`:

| Gate | Result |
| --- | --- |
| `uv sync --all-packages --dev --locked` | success; 40 resolved, 39 checked |
| `uv run ruff format --check .` | success; 69 files formatted |
| `uv run ruff check .` | success |
| `uv run ty check` | success |
| `uv run pytest -p no:cacheprovider` | **348 passed in 19.96s** |
| fresh `uv build --all-packages` | success |
| artifact enumeration | exactly 8 wheels + 8 sdists, all `0.1.0a1` |
| facade typing marker | `rakit/py.typed` present in the `rakit` wheel |
| web runtime resources | all 10 required files present in the `rakit-web` wheel |
| minimal example `rakit check` / `rakit routes` | both exit 0; 4 routes, 0 plugins |
| FastAPI example `rakit check` / `rakit routes` | both exit 0; 4 routes, 1 plugin |
| isolated ordinary-wheel install | 16 packages installed offline; full facade imports passed |
| optional adapter isolation | `rakit_sqlalchemy` absent from `sys.modules` after facade import |
| `git diff 25304bc..HEAD -- uv.lock` | empty |
| worktree diff check/status before this report update | clean |

The fresh artifacts were written to `C:\tmp\rakit-plan02-round2-091cd9b`; the isolated install
used a separately verified-new `C:\tmp\rakit-plan02-round2-install-091cd9b` environment with
CPython 3.12.12. No push, merge, tag, or publish action was performed.

## 6. Fresh-review Important follow-up

Two later Important findings were fixed in focused commits:

- `de5dec5 fix(sqlalchemy): enforce declared identity sort policy`
- `55140d1 fix(web): normalize resource field declarations`
- `f0e51f5 fix(web): defer identity sort tie breakers`

SQLAlchemy now validates every caller-supplied sort strictly against declared `sort_fields`.
Identity fields are appended only afterward as internal stable-pagination tie-breakers. RED showed
the undeclared direct identity sort did not raise while the explicit opt-in and exactly-once
tie-breaker cases already passed. GREEN was 3/3: undeclared identity sorting returns the same safe,
non-echoing `validation.failed` response; declaring the identity field permits it; internal
identity ordering remains present exactly once.

Registration now accepts only list/tuple declaration containers containing strings, copies them
to immutable tuples, and converts malformed shapes into `config.invalid_resource_policy` with only
`resource_id`, `policy`, and `reason=fields_invalid` details. The RED matrix reproduced six cases
as leaked `TypeError`, leaked Pydantic `ValidationError`, or silently accepted scalar string/dict
coercion. GREEN was 6/6, secret declaration values were absent from public details, and compiling
after failed registration contained no partially registered resource.

Combined focused RED: 7 failed and 2 already passed. Combined focused GREEN: 9 passed. Broader
SQLAlchemy datasource/query and web registration regression: 55 passed; CLI regression: 2 passed;
Ruff and ty: passed.

The first whole-suite run after strict adapter validation exposed the web integration edge: the
web parser still passed `identity_fields` to `ResourceQuery.from_params`, which made core append an
identity sort before the adapter could distinguish user input from its internal tie-breaker. Two
existing end-to-end resource-page tests failed with 400 responses. The web parser now carries only
validated explicit user sorting; SQLAlchemy remains the sole identity append point after policy
validation. A list/count regression was added for a resource whose identity is excluded from
`sort_fields`; restoring the old injection reproduced the 400 RED, and the final focused web suite
passed 32/32 (list, count, renamed attributes, and all query UI cases). Ruff and ty passed afterward.

The sandbox approval service exhausted its usage allowance during the final rerun. Direct execution
from the already locked/synced `.venv` collected 357 tests and passed 352 before the web integration
fix; the other three failures were artifact/CLI subprocesses unable to use uv's sandbox-denied cache.
After the integration fix, the affected 32-test web set passed. The controller's concurrent full
run reported 354 product tests passing with only those same three uv-cache subprocess failures.
No dependency or lockfile change was made.
