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

Final HEAD and exact full-gate results are recorded after the documentation commit and final rerun.
