# Phase D4.0 — Web Portability / ASGI Integration Contract — Implementation Plan

> **Execution note:** Follow this plan task-by-task in the same checkout. Keep
> the work on `phase-d4-0-web-integration-contract`, preserve unrelated edits,
> and stop after D4.0 review, draft PR creation, and known CI status. Do not
> begin D4.1.

## Goal

Implement the D4.0 protocol-first ASGI integration contract described in
[`2026-09-03-phase-d4-web-portability-design.md`](../specs/2026-09-03-phase-d4-web-portability-design.md).
Rakit application semantics remain framework-neutral while a generic
`rakit-web` composition root safely combines a host ASGI application with
`Admin`.

## Architecture and boundaries

The production dependency graph remains:

```text
rakit-core: semantic contracts and policy; no web-framework imports
    |
rakit-web: current Starlette Rakit runtime + generic ASGI composition
    |
public rakit facade: Admin and compose_asgi
    |
ASGI server: invokes the single composition-root lifespan
```

The composition root will call `admin.asgi()` once, route `http` and
`websocket` scopes by exact segment boundary, transform only the Rakit child
scope, and directly drive both child lifespans. It will not import FastAPI,
Litestar, Sanic, or Flask and will not add host security/context bridges.

## Tech Stack and verification commands

- Python 3.12+; existing package layout and `uv` workspace.
- Existing neutral ASGI protocol types from `rakit-server`/`rakit-core` are
  reused; no duplicate core protocol is introduced.
- AnyIO is used for new web-boundary task/cancellation orchestration and is
  declared directly by `rakit-web` as `anyio>=4.0,<5`.
- Existing Starlette remains the Rakit web runtime.
- Focused tests: `uv run pytest <target> -q`.
- Canonical static gates: `uv run ruff format --check .`,
  `uv run ruff check .`, and `uv run ty check`.
- Canonical test/docs/artifact gates are taken from `.github/workflows/ci.yml`
  and `scripts/`, not invented alternatives.

## Global constraints

- Start every implementation batch by checking branch, HEAD, status, and
  diff-stat; preserve user work.
- Use `apply_patch` for source, test, and documentation edits.
- Do not add framework-specific production dependencies or adapters.
- Do not change provider ID `web.starlette` or invent host capability IDs.
- Do not change `rakit-core` imports/dependencies for web composition.
- Preserve standalone `Admin.asgi()` behavior.
- Do not bump versions, tag, publish, merge, or force-push.
- Keep commits logical and reviewable; stage only intended paths.

## Task 1: Source-first contract probes and regression skeleton

**Files:**

- Add `packages/rakit-web/tests/test_asgi_composition.py`.
- Update `packages/rakit-web/tests/conftest.py` only if a small reusable raw
  ASGI exchange/lifespan helper is needed.
- Inspect, but do not modify, the current neutral contracts in
  `packages/rakit-server/src/rakit_server/targets.py` and
  `packages/rakit-core/src/rakit_core/testing/capability_conformance.py`.

**Steps:**

1. Reconfirm `git status --short`, current branch, `HEAD`, and `git diff --stat`.
2. Define minimal fake/probe ASGI host and Rakit child fixtures in the test
   module. Each probe records received scopes/messages and implements explicit
   lifespan behavior, route responses, and optional failure modes.
3. Add a small deterministic manual-probe test/utility path that exercises host
   startup, Rakit startup, host route, mounted Rakit route, nested `root_path`,
   Rakit shutdown, host shutdown, and one startup rollback. Keep it protocol
   level; do not install or import a host framework.
4. Add permanent failing tests for public composition import, host fallback,
   prefix routing, scope isolation, and the lifecycle/state matrix. Include
   explicit assertions for message ordering and exactly-once invocation.
5. Run only the new module. The expected result at this point is collection or
   assertion failure because the composition API does not exist yet. Record the
   failure as the TDD red baseline; do not weaken the assertions.

## Task 2: Define path validation and isolated scope transformation

**Files:**

- Add `packages/rakit-web/src/rakit_web/asgi_composition.py`.
- Extend `packages/rakit-web/tests/test_asgi_composition.py` with path-focused
  tests if Task 1 did not contain all cases.

**Interface:**

```python
def compose_asgi(
    host: ASGIApplication,
    admin: Admin,
    *,
    path: str = "/admin",
) -> ASGIApplication: ...
```

Use the existing neutral ASGI callable contract rather than introducing a new
protocol in `rakit-core`. Keep implementation details private to `rakit-web`.

**Steps:**

1. Validate the configured prefix as a non-empty absolute path with no query or
   fragment and canonicalize the trailing slash. Reject malformed values
   explicitly at composition time.
2. Implement exact segment-boundary matching. `/admin` and `/admin/` select
   Rakit; `/administrator` does not. `/` is the special all-path prefix.
3. Build a fresh host scope and a fresh Rakit scope for every ordinary dispatch.
   Copy `state` and `path_params` when present; never mutate the incoming scope.
4. For Rakit, remove only the prefix from `path`; map the prefix root and a
   trailing slash to `/`; preserve all other scope keys, including
   `query_string`.
5. Join incoming `root_path` with the configured prefix for Rakit only. Preserve
   the host root path unchanged and avoid duplicate separators.
6. When `raw_path` is present, validate its decoded path against `path`, remove
   the raw prefix without decoding/re-encoding the suffix, and map an empty raw
   suffix to `b"/"`. Preserve absent/`None` values. Raise a clear error for
   inconsistent or unsupported raw metadata rather than fabricating it.
7. Forward non-`http`/`websocket`/`lifespan` scopes to the host copy. Reserve
   `lifespan` for the composition controller in Task 4.
8. Run the focused path tests. Confirm red failures become green without
   changing unrelated Rakit behavior.

## Task 3: Implement the child lifespan protocol controller

**Files:**

- Extend `packages/rakit-web/src/rakit_web/asgi_composition.py` with private
  lifespan-controller types/functions.
- Extend `packages/rakit-web/tests/test_asgi_composition.py` with protocol-level
  child lifespan cases.

**Steps:**

1. Model child lifespan states explicitly: not-started, startup-sent,
   startup-complete, startup-failed, unsupported, shutdown-sent,
   shutdown-complete, and shutdown-failed.
2. Invoke each child with a copied lifespan scope and copied outer state. Use
   AnyIO task groups/streams and cancellation primitives; do not add new
   `asyncio`-specific orchestration to the composition layer.
3. Distinguish an application that raises before accepting a startup event
   (unsupported lifespan) from one that accepts the event and then raises or
   sends `lifespan.startup.failed` (real startup failure). Never reclassify an
   explicit failure as unsupported.
4. Treat explicit startup/shutdown failed messages as failures and preserve the
   underlying exception/message. Reject invalid child event sequences rather
   than hanging or silently succeeding.
5. Ensure child tasks are cancelled and awaited on every failure path. Re-raise
   cancellation according to AnyIO semantics and do not leak background tasks.
6. Add tests for unsupported child lifespan, explicit failure, post-accept
   exception, invalid messages, cancellation cleanup, and exactly-once child
   invocation.
7. Run the new focused tests and inspect task counts/records in the probes.

## Task 4: Add the lifecycle-owning composition root

**Files:**

- Complete `packages/rakit-web/src/rakit_web/asgi_composition.py`.
- Extend `packages/rakit-web/tests/test_asgi_composition.py`.

**Steps:**

1. Call `admin.asgi()` once during `compose_asgi` construction and retain the
   resulting Rakit ASGI child. Do not create a second Admin lifecycle around it.
2. On the root lifespan, start the host child first and Rakit second. Send
   `lifespan.startup.complete` only after both have completed. If host startup
   fails, do not invoke Rakit startup. If Rakit startup fails, attempt host
   shutdown rollback before reporting startup failure.
3. On normal shutdown, stop Rakit first and host second. Attempt host cleanup
   even when Rakit cleanup fails. Send shutdown failure when cleanup fails and
   preserve multiple failures with `ExceptionGroup` on Python 3.12+.
4. Ensure every child starts/stops at most once per root exchange and that no
   request can pass the root readiness gate before both startups succeed.
5. For request scopes, overlay only the selected child's lifespan state onto a
   copy of that request's incoming state. Host requests cannot see Rakit state;
   Rakit requests cannot see host state.
6. Dispatch HTTP and WebSocket scopes through the Task 2 transformer. Verify
   host WebSocket and unknown/non-owned scope behavior remains host-owned.
7. Run the source-level/manual ASGI probe before broad pytest. Confirm the
   recorded sequence is host-start, Rakit-start, host route, Rakit route,
   transformed nested root path, Rakit-stop, host-stop, with rollback also
   observed for a Rakit startup failure.
8. Run all focused composition tests and preserve their output for the final
   report.

## Task 5: Preserve and surface Rakit shutdown failures

**Files:**

- Update `packages/rakit-web/src/rakit_web/lifecycle.py`.
- Update existing lifecycle tests, identified with `rg -n
  "run_shutdown|shutdown failed|on_shutdown|ExceptionGroup"
  packages/rakit-web/tests tests/integration`.
- Update `packages/rakit-web/tests/test_asgi_composition.py` for composed
  Rakit shutdown failures.

**Steps:**

1. Establish the current behavior and test expectations before editing. The
   existing lifecycle manager logs callback failures and continues; D4.0 must
   continue cleanup but cannot silently discard the failure.
2. Keep LIFO callback order and continue attempting every callback. Collect
   ordinary failures and raise one failure after cleanup; use `ExceptionGroup`
   when more than one materially relevant failure exists.
3. Preserve cancellation semantics rather than converting cancellation to a
   successful shutdown. Ensure resolver detachment/close behavior still runs.
4. Update regressions to prove standalone behavior remains compatible except
   that a shutdown failure is now observable, and prove composed cleanup still
   attempts the host after Rakit failure.
5. Run lifecycle regressions plus all composition tests. Inspect logs and
   exception causes so the implementation does not hide the first or later
   failure.

## Task 6: Add the internal D4 host-conformance harness

**Files:**

- Add `packages/rakit-web/src/rakit_web/_host_conformance.py`.
- Add `packages/rakit-web/tests/test_host_conformance.py`.

**Interface shape:**

```python
@dataclass(frozen=True, slots=True)
class ASGIHostConformanceCase:
    name: str
    build_admin: Callable[[], Admin]
    compose: Callable[[ASGIApplication, Admin], ASGIApplication]

async def run_host_conformance(
    case: ASGIHostConformanceCase,
) -> None: ...
```

The exact private result/fixture helpers may be refined while preserving these
semantics. The harness must accept a case-supplied host app and composer, must
not import host frameworks, and must not be exported as a stable third-party
SDK.

**Steps:**

1. Add a fake-host case whose `build_admin` contains no host-framework branch.
2. Have the runner exercise host fallback, Rakit-prefix dispatch, lifecycle
   ordering, exactly-once startup/shutdown, and child state isolation.
3. Make assertions diagnostic enough for D4.1+ to reuse without rewriting the
   contract.
4. Add a test that inspects the production module/import graph for forbidden
   framework imports and confirms no capability/provider ID was added.
5. Run the harness tests and `rakit-web` capability tests together.

## Task 7: Wire the public facade and direct dependency

**Files:**

- Update `packages/rakit/src/rakit/__init__.py` to import and export
  `compose_asgi`.
- Update `packages/rakit-web/pyproject.toml` with the direct bounded AnyIO
  dependency.
- Update `uv.lock` using the repository’s supported lock command after the
  manifest change.
- Add public API assertions to `packages/rakit/tests/test_init_cli.py` or a
  focused facade test under `packages/rakit/tests/`.

**Steps:**

1. Keep all framework imports out of the facade and production composition.
2. Confirm the public import works from the installed workspace package.
3. Regenerate the lockfile deterministically and inspect that only the intended
   package dependency metadata changes.
4. Run facade, packaging, and composition tests with the locked environment.

## Task 8: Correct C2 guidance and existing examples

**Files:**

- Update `packages/rakit/src/rakit/scaffold/render.py`.
- Update `packages/rakit/tests/test_init_cli.py`.
- Update `packages/rakit/tests/test_init_planner.py`.
- Update `docs/getting-started/fastapi.md`.
- Update `examples/fastapi_sqlalchemy/main.py` and any example documentation or
  tests that assert its mount guidance.
- Update `README.md`/`docs/index.md` only where they describe the old direct
  mount as the portable or recommended path.

**Steps:**

1. Replace generated FastAPI/Starlette direct `.mount()` guidance with the
   explicit `compose_asgi(host, admin, path="/admin")` pattern. Keep the
   existing-project scaffold additive and do not edit host files
   automatically.
2. Preserve framework-specific detection only as guidance selection; do not
   add framework-specific runtime imports to `rakit-web`.
3. Update regression tests to assert the portable composition import and call,
   and assert that unsafe direct mount guidance is absent from the generated
   snippet.
4. Update the FastAPI example to use the composition root while leaving its
   FastAPI-owned database lifespan in the host app.
5. Run scaffold tests and the example-read tests before moving to broad docs.

## Task 9: Update architecture, roadmap, and user documentation

**Files:**

- Add `docs/concepts/web-integration.md`.
- Update `docs/concepts/architecture.md`.
- Update `docs/roadmap.md`.
- Update `mkdocs.yml` navigation.
- Update any stale FastAPI/Starlette mounting references found by repository
  search.

**Steps:**

1. Document the four-layer distinction: Rakit application, Rakit web runtime,
   host ASGI application, and ASGI server.
2. Document standalone `admin.asgi()` and composed `compose_asgi(...)` usage,
   lifecycle ownership, root-path/scope/state isolation, security ownership,
   and the fact that direct host `.mount()` is not the canonical lifecycle-safe
   D4 path.
3. State framework-switch portability as a first-class goal without claiming
   D4.1/D4.2 proofs before they exist.
4. Correct any stale D3.6 SQLAlchemy Core capability statement to the proven
   five capabilities:
   `persistence.read`, `persistence.write`,
   `persistence.relationships`, `transactions.root-uow`, and
   `concurrency.atomic-optimistic`. Do not alter truthful Tortoise, Peewee, or
   Piccolo profiles.
5. Replace the old D4 sequence with D4.0 contract, D4.1 Litestar, D4.2
   FastAPI, D4.3 Starlette, D4.4 conditional Sanic, and D4.5 ASGI DX/matrix.
6. Move Flask/WSGI to an explicit postponed/research section outside the D4
   closure gate and make no Flask support claim.
7. Build MkDocs navigation and search all scoped docs/examples for stale
   direct-mount claims.

## Task 10: Focused implementation verification and compatibility checks

**Files:** none unless a failing check identifies an in-scope defect.

**Steps:**

1. Run focused composition, lifecycle, facade, scaffold, and example tests.
2. Run complete `rakit-web` tests and then complete repository pytest with
   coverage.
3. Run `uv run ruff format --check .`, `uv run ruff check .`, and `uv run ty
   check`; fix only in-scope issues.
4. Run the Python 3.12, 3.13, and 3.14 test matrix using installed interpreters
   or the workflow-equivalent `uv run --python` commands. Record unavailable
   interpreters as CI-owned rather than claiming local success.
5. Run lowest-direct and latest-allowed dependency checks using the workflow
   commands. Restore the locked environment afterward and verify `uv.lock` has
   no unintended changes.
6. Run strict MkDocs build, CSS/generated-web reproducibility checks, artifact
   validation, and clean-installed artifact smoke using the exact workflow
   commands discovered from `.github/workflows/ci.yml` and `scripts/`.
7. Inspect generated artifacts and `git diff --check`; distinguish any known
   CRLF notices from actual whitespace errors.

## Task 11: Whole-diff architecture review

**Files:** none unless review finds an in-scope defect.

**Steps:**

1. Review `git diff origin/main...HEAD` in full, including untracked files and
   dependency lock changes.
2. Run the required leakage searches:

   ```text
   rg -n "fastapi|litestar|sanic|flask" packages/rakit-core packages/rakit-web packages/rakit
   rg -n "starlette" packages/rakit-core
   ```

   Framework names may appear only in justified docs, scaffold detection, or
   explicit tests; no generic production implementation dependency may leak in.
3. Confirm no fake UniversalRequest/UniversalResponse/UniversalRouter or
   equivalent speculative abstraction was added.
4. Confirm `Admin.asgi()` standalone behavior, `web.starlette` capability
   identity, security ownership, and the D3 SQLAlchemy Core correction.
5. Run the request-code-review workflow with a read-only independent reviewer.
   Address valid findings, rerun affected tests, and record rejected findings
   with concrete repository evidence.

## Task 12: Final verification, commits, push, and draft PR

**Files:** none unless final review identifies an in-scope defect.

**Steps:**

1. Run `verification-before-completion`: check branch/HEAD/status, rerun the
   final focused and canonical gates, inspect test counts and coverage output,
   and ensure no command is reported as passing unless it actually ran.
2. Use small logical commits, at minimum separating design, plan, runtime/tests,
   guidance/docs, and final remediation where the actual diff supports that
   split. Stage only named accepted paths.
3. Before pushing, verify branch is
   `phase-d4-0-web-integration-contract`, parent/base is
   `006ea9fff92ea1a68cb32400c108f468a1faa5cc`, and no unrelated work is staged.
4. Push only:

   ```text
   origin HEAD:phase-d4-0-web-integration-contract
   ```

   Use no force option.
5. Create or update a DRAFT PR against `main` titled
   `feat(web): add ASGI portability contract`. Include protocol-first
   portability, lifecycle correctness, path/scope/state semantics, security
   isolation, conformance, Flask postponement, the D3 roadmap correction, and
   exact verification status.
6. Query PR checks and exact-head CI. If a required check is pending or fails,
   do not call D4.0 complete; wait or fix/report the blocker accurately.
7. Stop after D4.0. Do not implement Litestar, FastAPI, Starlette hardening,
   Sanic, WSGI, release, or publication work.

## Self-review checklist before implementation

- [x] Design defines the host/runtime distinction and protocol-first decision.
- [x] Design defines exact routing, `root_path`, `raw_path`, scope/state
  isolation, and HTTP/WebSocket behavior.
- [x] Design defines single-owner lifespan startup/shutdown ordering and
  failure/unsupported semantics.
- [x] Design defines security, middleware, exception, capability, and
  dependency ownership.
- [x] Design postpones Flask/WSGI and rejects speculative universal web
  abstractions.
- [x] Plan uses regression-first ordering and names exact files/interfaces.
- [ ] Source-first probe, focused tests, package/full gates, multi-Python,
  dependency, docs/artifact, review, PR, and exact-head CI evidence still need
  to be generated during execution.

