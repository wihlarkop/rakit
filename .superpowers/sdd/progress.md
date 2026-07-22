# Plan 02 progress ledger

Task 1: complete (commits c92dfd0..15ada68, review clean — Minor only: identity.py:14 validator
  lacks type annotations, identity.py:29-30 decode() doesn't wrap json.JSONDecodeError/
  binascii.Error in a purpose-built error, test coverage doesn't include malformed-base64/
  mixed-type-values cases. Not blocking, noted for final review roll-up.)
Task 2: complete (commits 15ada68..55bd786, review clean — Minor only: ResourceQuery is
  directly constructible bypassing the sort whitelist (by design, from_params is the
  boundary), duplicate explicit sort fields e.g. "id,-id" aren't deduplicated. Not blocking.)
Task 3: complete (commits 55bd786..ab9c9df, review clean — Minor only: 404 message duplicates
  identity in both message text and details dict, MissingDataSource test fixture duplicates
  FakeDataSource's unused list() body. Not blocking.)
Task 4: complete (commits ab9c9df..2b84b55, review clean — Minor only: EXACT count subquery
  built after order_by is applied (dead ORDER BY in subquery, harmless), sort direction
  compared via .value == "desc" instead of enum equality (style), _claim/constructor both
  call inspect_model (negligible double work). Not blocking. Adds ApplicationBuilder
  .register_adapter/_adapters primitive to compiler.py (design-decisions.md section 3) plus
  ErrorCode.CONFIG_DUPLICATE_ADAPTER, ahead of Task 5's own compiler.py changes.)
Task 5: complete (commits 2b84b55..5f146a3, one fix round — Important finding fixed: retyped
  ApplicationBuilder._adapters/register_adapter against DataSource Protocol instead of object,
  removing an unverified cast() in Admin.register(). Re-review clean. Remaining Minor, not
  blocking: ModelAdmin.model access unguarded (raw AttributeError vs RakitError for the other
  4 attrs), no direct test for CONFIG_DUPLICATE_RESOURCE or resource-registration rollback
  under a failed plugin configure(). Adds admin_types.py (ResourceAdmin/ModelAdmin),
  ApplicationBuilder.add_resource/.resources, CompiledApplication.resources, Admin.register().)
Task 6: complete (commits 5f146a3..e584037, review clean — Minor only: template candidate
  ordering diverges from exact design-section-5 sequence once a theme tier exists (collapses
  to correct order today, no theme system yet), full-page list.html's embedded _table.html
  include doesn't resolve resource-specific overrides (only the standalone fragment route
  does), malformed identity token on /users/<garbage> yields 500 not 404 (codec.decode()
  raises non-RakitError exceptions), 404 JSON response lacks Cache-Control: no-store,
  base.html references /_system/static/htmx.min.js which 404s until Task 8 (expected/noted).
  Not blocking. Extends DataSource Protocol with fields/identity_fields (design-decisions.md
  section 11); adds resource_routes.py, base/list/_table/detail.html, Admin.asgi() real route
  wiring, template_dirs override precedence, RakitError->HTTP exception handler.)
Task 7: complete after typed-filter follow-up (original commits e584037..fb3bd88 plus the focused
  follow-up commit). The unresolved Important finding is fixed at the SQLAlchemy adapter boundary:
  mapped metadata now converts URL text for integer/float/Numeric/boolean/date/datetime/UUID/Enum/
  string fields and `IN` items before predicate construction; invalid values return a stable 400
  `RakitError` before session creation; custom SQLAlchemy types have an explicit safe conversion
  hook; SQLAlchemy Enum persisted names include alias-aware `omit_aliases=False` and
  `values_callable` coverage; `contains` is string-only; PostgreSQL-dialect bind inspection prevents SQLite affinity from
  masking regressions; input queries remain unchanged. Focused SQLAlchemy/web, full pytest, Ruff,
  and ty verification are recorded in task-7-typed-filter-report.md. Remaining Minor (not blocking):
  sort-header links drop active filter params, search form drops active filter params
  (page-reset itself works fine); comparison operators beyond the new string-only `contains` rule
  are not further type-restricted; id-default-sort-header is cosmetic only. Adds
  DISABLED/DEFERRED count policies + search to
  SQLAlchemyDataSource, GET {path}/_count route + _count.html, URL filter/search/count_policy
  parsing in parse_query(), sort-header/search-form UI in _table.html.
Task 8: complete (commit c957b96). Added content-hashed local CSS/HTMX assets,
  immutable and traversal-safe static serving, wheel/sdist resource coverage, mount-aware template
  and resource URLs, an in-memory minimal read-only example, and a FastAPI + application-owned
  SQLAlchemy-engine example mounted at `/admin`. HTMX v2.0.10 source/license provenance verified
  against the authoritative tagged upstream release; 0BSD license and provenance notice bundled.
  Naming ambiguity resolved in favour of importable `examples/fastapi_sqlalchemy/`. Focused RED
  captured (11 expected failures); focused GREEN is 11 passed. Final verification: 256 tests,
  Ruff format/check, ty, diff-check, required CLI commands, wheel/sdist inspection, and isolated
  Python 3.12 installed-wheel resource routes all pass. Full evidence: task-8-report.md.
Task 8 independent-review follow-up: complete (commit 7de96c0). Fixed mounted search
  and sort controls to retain ASGI `root_path`; reverted the root Hatch package so the workspace
  remains virtual and `uv build --all-packages` produces exactly the eight official wheel/sdist
  pairs; documented/tested explicit repository `PYTHONPATH` for private example CLI imports; and
  expanded wheel/sdist tests to enumerate base, list, detail, `_table`, and `_count` templates.
  TDD RED showed `/users` escaping `/admin` and the extra `rakit_workspace` artifact; focused
  follow-up GREEN is 12 passed, full suite is 257 passed, Ruff/ty/diff-check are clean.
Plan 02 final whole-branch review fix wave: complete (commits 134535c, 371b2d4, 0b83409,
  652117d, and 21a499c). Fixed canonical UUID identities and safe
  mapped-PK coercion; deep immutable identity/filter inputs; runtime-equivalent route collision
  checks including built-in home; adapter-enforced identity tie-break ordering; query-state-
  preserving mounted/standalone controls; full-page table override parity; valid `aria-sort`;
  executable README contract coverage; and all requested minor hardening. Focused RED/GREEN
  evidence is in `plan-02-final-review-fixes-report.md`. Final verification: 302 tests passed,
  Ruff format/check passed, ty passed, `uv build --all-packages` produced exactly eight wheels and
  eight sdists at version `0.1.0a1`, every artifact contained `py.typed` and all nine required web
  resources, all four real example CLI checks passed, and the whole-branch diff-check was clean.
