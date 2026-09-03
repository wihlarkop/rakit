# Test Suite Performance Optimization Implementation Plan

> **For agentic workers:** Execute this work inline on `chore/test-suite-performance`. This document is an evidence and task-status log; it contains no implementation source code.

**Goal:** Remove the proven duplicate all-package artifact build from the serial pytest suite and document the measured optional xdist fast path without changing test coverage, product behavior, or canonical CI semantics.

**Architecture:** Keep `uv run pytest` serial and unchanged for normal debugging. Add the narrowest session-scoped fixture in the examples-test scope so the two consumers share one immutable all-package build per pytest process while retaining per-test installation and runtime workspaces. Document, but do not make canonical, `uv run pytest -n auto --dist worksteal` until direct CI evidence justifies a CI change.

**Tech Stack:** Python 3.12+, pytest, pytest-xdist, pytest-cov, uv workspace, Ruff, ty, MkDocs, GitHub Actions.

**Spec:** User-approved performance-hardening request in the conversation; no separate architectural specification is required for this bounded optimization.

## Global Constraints

- Starting main is `56f23d06a4ba014cfad74224e0bac055686a7003`; do not reuse an old D4 branch.
- Preserve every test, skip, coverage threshold, supported Python version, dependency matrix, release gate, artifact gate, and generated-asset gate.
- Keep canonical `uv run pytest` serial and unchanged; do not change CI pytest invocation to xdist in this task without direct GitHub Actions evidence.
- Use current repository source as authoritative; do not copy executable implementation from plans or specifications.
- Do not change product behavior, persistence semantics, version, tags, releases, publications, or D4.1 scope.
- Use worker-safe temporary paths and retain test order independence.

---

## Evidence ledger

### Task 1: Establish the canonical baseline — Complete

- `origin/main` was fetched and verified at `56f23d06a4ba014cfad74224e0bac055686a7003`.
- Known post-merge CI run `33779955524` targeted that exact SHA and succeeded.
- Dedicated branch: `chore/test-suite-performance`.
- Measurement host: Windows, 12 logical CPUs, Python 3.12.12, pytest 8.4.2, pytest-xdist 3.8.0, pytest-cov 7.1.0.
- Three healthy serial runs under comparable network-enabled temporary state: 188.724s, 186.785s, 180.374s; median 186.785s.
- Each healthy run reported `2116 passed, 1 skipped`.
- Initial local failures were diagnosed as inaccessible `.pytest-tmp`/`.pytest_cache` and sandbox-blocked PyPI access, not source failures; the isolated reproductions passed after using exact temporary state and network access.

### Task 2: Complete slow-test profiling — Complete

- Full `--durations=50` profile passed in 221.851s with `2116 passed, 1 skipped`.
- Main phases: all-package build 29.66s, second all-package build 27.32s, CLI subprocess checks 5.59s, standalone web artifact build 4.99s, reference-app subprocess 2.38s.
- No expensive fixture setup or teardown phase appeared in the top 50; the dominant avoidable cost is duplicate artifact construction.

### Task 3: Analyze fixture/setup and worker safety — Complete

- Both duplicate-build consumers only read wheel/sdist files after build.
- Each consumer installs into its own `tmp_path` virtual environment and uses its own mutable runtime/database workspace.
- The migration test uses its own SQLite file and environment dictionary; the other test uses a separate installation and import subprocess.
- Neither consumer mutates, replaces, or deletes the shared distribution directory.
- A session fixture remains alive until pytest session cleanup; consumer cleanup cannot remove it early.
- No test-order dependency is required: either consumer can trigger fixture setup first.
- Other suite resources are worker-safe in current source: SQLite and storage paths derive from `tmp_path`; real integration engines use per-test paths; fixed server values are mocked or synthetic client metadata.

### Task 4: Complete controlled xdist experiments — Complete

| Mode | Wall time | Result | Notes |
| --- | ---: | --- | --- |
| Serial median | 186.785s | pass | Three-run median |
| `-n 2` | 129.935s | pass | 30.5% faster than serial median |
| `-n 4` | 132.278s | pass | Contention outweighed extra workers |
| `-n auto` | 126.026s | pass | 12 workers on this host |
| `-n auto --dist worksteal` | 108.546s | pass | Current preferred optional fast mode |

- No exhaustive worker-count matrix is warranted by current evidence.

### Task 5: Select root causes and decisions — Complete

- Adopt one narrow session-scoped all-package build fixture for the two duplicate consumers.
- Keep `uv run pytest` serial and retain serial CI.
- Document `uv run pytest -n auto --dist worksteal` as an optional local fast path.
- **Rejected:** making xdist the default or changing CI now; GitHub Actions direct evidence for the proposed command is not yet available, and local extra-worker contention makes a global default less predictable.
- **Deferred:** changing the standalone `rakit-web` artifact test or CLI/reference-app subprocess behavior; their costs are smaller and their current scopes test distinct artifact/CLI contracts.

---

## Delivery tasks

### Task 6: Add the narrow shared build fixture — Complete

**Files:**

- Create: `tests/examples/conftest.py` for one session-scoped immutable distribution directory per pytest process.
- Modify: `tests/examples/test_read_examples.py` so both existing consumers use that fixture while retaining their per-test installation/database workspaces.

**Acceptance:** Existing assertions remain intact; no test is removed or skipped; the fixture has no cross-worker mutable state or early cleanup path.

- Verified by the focused artifact consumers: `2 passed` with one session-owned build and separate consumer workspaces.

### Task 7: Document the canonical and optional commands — Complete

**Files:**

- Modify: `CONTRIBUTING.md` in the existing development/testing guidance.

**Acceptance:** Documentation states that `uv run pytest` remains canonical serial, identifies the optional work-stealing command, and tells future tests to use pytest-managed worker-safe temporary resources. CI commands remain unchanged.

- Verified in `CONTRIBUTING.md`; no CI workflow file was changed.

### Task 8: Verify focused artifact behavior and serial improvement — Complete

- Run both artifact consumers directly.
- Run three comparable serial full-suite measurements and calculate the post-change median.
- Confirm counts remain `2116 passed, 1 skipped` and compare only against the original serial median.

- Focused consumers: `2 passed`.
- Post-change serial runs: 168.120s, 136.980s, 134.084s; median 136.980s.
- Serial improvement versus the original 186.785s median: 26.7%.
- Every serial run reported `2116 passed, 1 skipped`.

### Task 9: Verify optional fast-mode stability — Complete

- Run `uv run pytest -n auto --dist worksteal` after implementation.
- Run at least three consecutive full-suite passes in the final chosen configuration; restart the sequence if any run fails.
- Compare the final fast-mode timing against the original serial median without combining incomparable measurements.

- Final fast runs: 85.079s, 90.958s, 89.453s; median 89.453s.
- All three consecutive runs reported `2116 passed, 1 skipped`.
- Fast-mode improvement versus the original serial median: 52.1%.

### Task 10: Verify coverage and canonical quality gates — Complete

- Run canonical coverage and confirm it remains at least 85%.
- Run Ruff format/check, `ty`, Python 3.12/3.13/3.14, lowest-direct/latest dependency suites, strict MkDocs, release tests, artifact validation/dry run, and web-asset reproducibility.
- Preserve all CI jobs and inspect direct PR CI timing only if CI commands are changed.

- Origin/main coverage measurement reached 85.16% but had one non-reproducible CLI-example failure in the long extracted-source run; the isolated CLI test passed immediately afterward.
- Final locked coverage passed: `2116 passed, 1 skipped`, 85.13%, with the unchanged 85% threshold.
- Python 3.13 and 3.14 locked suites passed: `2116 passed, 1 skipped` each.
- Lowest-direct and latest dependency suites passed: `2116 passed, 1 skipped` each.
- Ruff format check, Ruff lint, `ty`, strict MkDocs, 9 release tests, full artifact gate for 15 distributions, and Bun CSS reproducibility all passed.
- No CI workflow command was changed, so no GitHub Actions timing comparison is applicable before exact-head PR CI.

### Task 11: Final review, commit, push, draft PR, and exact-head CI — Complete

- Review the final diff against the starting SHA for scope, worker isolation, test/skip/coverage preservation, documentation accuracy, and no D4.1/product changes.
- Stage only intended files, inspect the staged diff, commit, push normally, create a draft PR against `main`, wait for exact-head CI, and inspect every job.
- Do not merge, tag, release, publish, or force-push.

- Final review found only the intended fixture, test, documentation, and work-log changes; no tests were removed or skipped and no product or CI behavior changed.
- The implementation commit was pushed normally, draft PR #63 was created, and exact-head CI completed successfully with every job successful.

## Final acceptance record

- [x] Implementation complete
- [x] Repeated stability verification complete
- [x] Before/after serial and optional fast-mode benchmark complete
- [x] Coverage and canonical quality gates complete
- [x] Exact-head CI complete
- [x] Final review complete
- [x] All completed tasks above marked `Complete`; rejected/deferred decisions retain reasons
