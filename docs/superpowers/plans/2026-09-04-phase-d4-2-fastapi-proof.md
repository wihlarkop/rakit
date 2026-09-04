# Phase D4.2 — FastAPI host-framework portability proof

Branch: `phase-d4-2-fastapi-proof`

Canonical base: `origin/main` at `0c6a5491539df569869c7880a49548995389852b`

## Scope

This log records evidence for a bounded real FastAPI host proof of the
existing generic `compose_asgi(host, admin, path="/admin")` contract. It is
status documentation, not implementation source. The proof must not create a
FastAPI-specific production adapter, dependency extra, capability, or
compatibility-range claim.

## Initial evidence

- Canonical remote state was fetched before branch creation.
- The branch was created explicitly from `origin/main`; `HEAD` is the
  expected canonical base SHA.
- The pre-existing untracked `.pytest-tmp-d41-final-doc/` directory was
  preserved untouched.
- The canonical post-merge CI run `33843233604` is green at the expected
  SHA.
- Current repository dependency declaration remains `fastapi>=0.116`.
- Locked resolution: FastAPI `0.139.2`, Starlette `1.3.1`.
- Lowest-direct resolution: FastAPI `0.133.0`, Starlette `1.3.1`.
- Latest resolution: FastAPI `0.141.1`, Starlette `1.6.0`.
- Current upstream research identified FastAPI `0.141.1` as the current
  stable release at research time and confirmed the documented main-app-only
  lifespan behavior for mounted sub-applications.
- A disposable native-mount probe served a mounted child request but ran
  only the parent lifespan callbacks.

## Acceptance checklist

1. Canonical baseline verified — Complete (origin/main and CI run recorded above)
2. FastAPI current-version research verified — Complete (upstream sources and resolutions recorded above)
3. Existing Rakit FastAPI usage audited — Complete (getting-started guidance, example, C2 guidance, and CI inspected)
4. D4.2 design approved — Complete (maintainer approval in session)
5. FastAPI dependency/version strategy decided — Complete (no declaration change; three resolutions recorded above)
6. HTTP ownership proof — Complete
7. Lifespan proof — Complete
8. Failure/rollback proof — Complete
9. Dependency-injection ownership proof — Complete
10. Middleware/security ownership proof — Complete
11. Root-path proof — Complete
12. OpenAPI/docs ownership proof — Complete
13. WebSocket ownership proof — Complete
14. Exception ownership proof — Complete
15. Native FastAPI mount investigation recorded — Complete (upstream statement and disposable probe recorded above)
16. Focused D4.2 suite complete — Complete
17. Existing D4.0/D4.1 regressions complete — Complete
18. Full repository verification complete — Complete
19. Documentation complete — Complete
20. Roadmap updated — Complete (D4.2 is complete after exact-head CI; D4.3 is Next and not started)
21. Final code review complete — Complete (no Critical findings; the Important stale-roadmap finding was resolved and docs/Ruff checks rerun)
22. Commit/push/draft PR complete — Complete (`e3be2a92d3a72ce778e0a59e2748c9b5b3d035a2` pushed; draft PR #65 created)
23. Exact-head CI complete — Complete (implementation head `e3be2a92d3a72ce778e0a59e2748c9b5b3d035a2` passed run `33851064114`; final documentation head is recorded below)

## Decisions and rejected approaches

- Native FastAPI `.mount()` as the lifecycle-safe golden path — Rejected —
  upstream documentation and the disposable probe show that mounted child
  lifespan callbacks are not executed.
- FastAPI-specific production adapter or composition branch — Deferred — only
  a demonstrated generic contract defect could justify a framework-neutral
  production change.
- Global FastAPI application dependency variation — Deferred — the focused
  route-local `Depends` and protected-route dependency provide deterministic
  ownership evidence without imposing a dependency on host docs routes.
- FastAPI dependency declaration changes — Deferred — existing locked,
  lowest-direct, and latest resolution strategies are sufficient for the
  bounded proof unless verification provides new evidence.

## Focused conformance evidence

Command:

```text
uv --cache-dir C:\Users\Edo\AppData\Local\Temp\rakit-d42-uv-cache run --no-sync pytest -q packages/rakit-web/tests/test_fastapi_conformance.py
```

Result: `8 passed` in the locked environment. The proof covers real FastAPI
typed routing, query parsing, response-model filtering, route-local
`Depends`, host security dependency isolation, host-local middleware and
exception handling, exact composition lifecycle order and rollback, root-path
forms, host/Rakit state separation, OpenAPI/docs ownership, and a FastAPI
WebSocket endpoint.

Ruff format and Ruff check both pass for the new module. The locked Starlette
version emits its existing TestClient/httpx deprecation warning during import;
no dependency was added or changed to suppress it.

The same 8-test FastAPI proof passed in both isolated dependency resolutions:

- lowest-direct: FastAPI `0.133.0`, Starlette `1.3.1`;
- latest: FastAPI `0.141.1`, Starlette `1.6.0`.

The branch `uv.lock` was not changed by these runs. The temporary source copies
used separate environments and retained their resolver-generated lockfiles
outside the repository.

The focused D4 regression command covering `test_asgi_composition.py`,
`test_host_conformance.py`, `test_litestar_conformance.py`, and the new
FastAPI module passed `39 tests`.

The full `rakit-web` package suite passed `912 tests` when run with an isolated
task-scoped pytest base directory and cache directory. Earlier attempts were
environmental failures caused by the repository's ACL-inaccessible generated
pytest paths and nested uv build isolation; neither required changing those
paths or their ACLs.

## Full verification evidence

- Locked full serial suite: `2131 passed, 1 skipped` on Python 3.12, with
  coverage `85.14%` and the `85%` threshold reached.
- Locked full serial suite: `2131 passed, 1 skipped` on Python 3.13.
- Locked full serial suite: `2131 passed, 1 skipped` on Python 3.14.
- Lowest-direct full serial suite: `2131 passed, 1 skipped`.
- Latest full serial suite: `2131 passed, 1 skipped`.
- Ruff format, Ruff check, and ty passed when scoped to repository source and
  excluding the preserved generated `.pytest-tmp-d41-final-doc/` directory.
- Strict MkDocs build passed using an isolated site directory.
- Artifact validation passed for all 15 official distributions, including
  clean-install smoke checks.
- Frozen Bun install, CSS build, and committed CSS reproducibility check
  passed.
- The only observed test warnings are existing upstream/dependency warnings:
  Starlette/httpx TestClient compatibility and the existing Piccolo SQLite
  ILIKE fallback; latest resolution also reports upstream AnyIO and Click
  deprecations. No warning motivated a dependency change.

## Review evidence

The required independent read-only code review found no Critical findings. Its
one Important finding was that the public roadmap still presented D4.2 as the
next unstarted item. The roadmap now records D4.2 as implementation and local
verification complete with exact-head CI pending, while overall D4 remains in
progress and D4.3 remains unstarted. The reviewer found no production leakage,
DI/security/middleware/exception/state bleed, OpenAPI brittleness, dependency
change, or copied Litestar-only test issue.

## Git and CI handoff evidence

- Commit: `e3be2a92d3a72ce778e0a59e2748c9b5b3d035a2`, parent
  `0c6a5491539df569869c7880a49548995389852b`.
- Push: `origin/phase-d4-2-fastapi-proof` created without force-push.
- Draft PR: [#65](https://github.com/wihlarkop/rakit/pull/65), titled
  `feat(web): prove FastAPI host portability`.
- Exact-head implementation CI: [run 33851064114](https://github.com/wihlarkop/rakit/actions/runs/33851064114),
  head `e3be2a92d3a72ce778e0a59e2748c9b5b3d035a2`, conclusion `success`.
  Every job passed: `test (3.12)`, `test (3.13)`, `test (3.14)`,
  `Dependencies (lowest-direct)`, `Dependencies (latest)`, `Web asset
  reproducibility`, `Plan 07 release gate`, and `Artifact dry run`.
- Final documentation-closure CI is recorded on [draft PR #65](https://github.com/wihlarkop/rakit/pull/65)
  and in the final handoff report. No further repository edit is made solely
  to copy external CI results into this log, avoiding a documentation-SHA loop.

## Evidence format

Each completed checklist item will record the command or test evidence that
supports it. Final status will contain no stale `Pending`, `TODO`, or
`In progress` entries: unresolved scope will be explicitly marked `Rejected —`
or `Deferred —` with a reason.
