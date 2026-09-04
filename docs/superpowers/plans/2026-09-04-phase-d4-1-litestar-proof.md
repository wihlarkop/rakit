# Phase D4.1 — Litestar host portability proof

Date: 2026-09-04
Branch: `phase-d4-1-litestar-proof`
Baseline: `28ae57934443bb0234274ba41fe17c7dc2b04344`
Tested host: Litestar `2.24.0`

## Scope

This work proves the existing generic ASGI composition contract against a
real Litestar host. It does not introduce a Litestar runtime adapter, a
framework bridge, or a broader compatibility policy.

The composition root is the outer application. It receives the original ASGI
scope, decides host versus Rakit ownership, and passes host-owned scopes to
Litestar. Litestar may perform its own internal routing and path normalization
only after that boundary.

## Evidence checklist

1. Canonical baseline verified — **Complete**: `origin/main` and the branch
   parent resolve to `28ae57934443bb0234274ba41fe17c7dc2b04344`; canonical CI
   run `33795752898` is green. The implementation branch currently starts at
   `5d671217ca938b05622d88245286256dcfaa5751`.
2. Litestar stable research verified — **Complete**: PyPI and stable `/2`
   documentation/source were checked; the bounded proof targets 2.24.0.
3. D4.1 design approved — **Complete**: maintainer approval received on
   2026-09-04.
4. Development dependency added — **Complete**: root dev group contains
   `litestar==2.24.0` and the test-graph compatibility floor
   `python-multipart>=0.0.15`; `uv.lock` is updated and locked sync succeeds.
5. Real Litestar HTTP ownership proof complete — **Complete**: host routes,
   Rakit routes, exact boundary, and query behavior pass.
6. Lifecycle proof complete — **Complete**: real Litestar hooks and Rakit
   callbacks pass the exact-once nesting-order assertion.
7. Failure/rollback proof complete — **Complete**: host startup failure does
   not start Rakit; Rakit startup failure rolls Litestar back.
8. Root-path proof complete — **Complete**: separate and mount-inclusive
   `/proxy` representations pass, including false-boundary ownership.
9. Middleware/security/state ownership proof complete — **Complete**: the
   host marker and real Litestar guard are host-visible only; no state or
   security bridge is introduced, and the ownership boundary is documented.
10. WebSocket proof complete — **Complete**: a real Litestar WebSocket route
    remains host-owned.
11. Native mount investigation recorded — **Complete**: pinned 2.24.0 probe
    confirms native mounting does not drive the Rakit child lifecycle; it is
    not made a supported D4.1 path or a permanent suite dependency.
12. Focused D4.1 suite complete — **Complete**: 7 tests pass.
13. Existing D4.0 regressions complete — **Complete**: ASGI composition and
    reusable host-conformance suites pass 24 tests.
14. Full repository verification complete — **Complete**: serial Python
    3.12 coverage, Python 3.13/3.14 suites, lowest-direct, and latest suites
    all pass; final Python 3.12 coverage is 85.15%.
15. Documentation complete — **Complete**: web integration documentation now
    records the outer composition boundary, ownership rules, and the bounded
    Litestar 2.24.0 proof.
16. Roadmap updated — Planned.
17. Final code review complete — **Complete**: the independent review found no
    Critical issues; its Important findings were resolved and retested before
    handoff.
18. Commit/push/draft PR complete — **Complete**: commits were pushed to
    `phase-d4-1-litestar-proof` and draft PR #64 was opened against `main`.
19. Exact-head CI complete — Planned.

## Decisions and boundaries

- Litestar is a root development/test dependency only, pinned to 2.24.0 for
  this bounded proof.
- No `rakit-litestar` distribution, `rakit[litestar]` extra, capability
  provider, or production Litestar import is planned.
- Existing D4.0 generic routing, scope-copy, readiness, lifecycle failure,
  and protocol tests remain authoritative and will not be mechanically
  duplicated.
- `/proxy2/admin` must remain host-owned at the Rakit composition boundary.
  Any subsequent Litestar pathname interpretation is upstream host behavior,
  not a Rakit contract.
- Litestar native ASGI mounting is not the D4.1 golden path because the
  investigation showed that it does not coordinate the Rakit child lifecycle.
- The root-only `python-multipart>=0.0.15` floor is required for the approved
  lowest-direct Litestar test graph: Litestar imports `multipart` symbols that
  are absent when the existing Rakit web floor resolves `python-multipart`
  below 0.0.15. No Rakit package runtime dependency was changed.

## Rejected or deferred approaches

- Native Litestar mounting as the golden path — **Rejected —** it does not
  provide the coordinated child lifecycle required by D4.0.
- Litestar-specific production composition code — **Deferred —** only to be
  reconsidered if a real conformance test proves a generic D4.0 defect.
- Broad Litestar 2.x/3.x compatibility claim — **Deferred —** compatibility
  range policy belongs to D4.5.

## Verification evidence

- `uv run pytest packages/rakit-web/tests/test_litestar_conformance.py -q` —
  7 passed.
- `uv run pytest packages/rakit-web/tests/test_litestar_conformance.py
  packages/rakit-web/tests/test_asgi_composition.py
  packages/rakit-web/tests/test_host_conformance.py -q` — 31 passed.
- `uv run ruff format --check .` — 497 files already formatted.
- `uv run ruff check .` — all checks passed.
- `uv run ty check` — all checks passed.
- `uv run pytest packages/rakit-web -q --basetemp=.pytest-tmp-d41-final-web2`
  — 904 passed.
- `uv run pytest --cov --cov-report=term-missing -q
  --basetemp=.pytest-tmp-d41-final-full` — 2,123 passed, 1 skipped;
  final review-fix rerun coverage 85.15%.
- Python 3.13, Python 3.14, lowest-direct, and latest dependency full suites
  — each 2,123 passed, 1 skipped.
- `uv run mkdocs build --strict` — passed.
- `uv run pytest tests/release -v --basetemp=.pytest-tmp-d41-final-release`
  — 9 passed.
- `uv run python scripts/check_artifacts.py` — 15 official distributions
  validated.
- `bun install --frozen-lockfile` and `bun run css:build`, followed by the
  generated CSS diff check — passed with no asset drift.

## Review resolution

The independent review's Important findings were resolved as follows:

- Added a test-only recorder immediately before Litestar to assert the
  host-owned path, root path, query string, state, and absence of Litestar
  framework keys at the composition boundary. Raw-path transformations remain
  covered by the framework-neutral D4.0 suite and the no-query root-path case.
- Added a real Litestar guard proof showing host-local rejection does not
  affect a Rakit-owned route.
- Corrected the baseline statement to distinguish the branch parent from the
  implementation head.
- Removed the TestClient-specific query-bearing `raw_path` assertion; raw-path
  semantics remain owned by the generic D4.0 direct-ASGI tests.

The `/proxy2/admin` real-host test asserts only that the composition boundary
leaves the request Litestar-owned. It does not encode Litestar's subsequent
internal pathname interpretation as a Rakit guarantee.
