# C3 Execution State

- Design: approved.
- Implementation plan: approved and executed inline with the user's source-first workflow.
- Branch: `phase-c3-installation-extras-ux`.
- Baseline source commit: `7bf5cd45eebf1b3e58cf9a69d854dd82d6c4531d` (`main` after C2).
- Local isolated checkout: unavailable in this environment; GitHub branch state is authoritative and GitHub Actions provides clean execution verification.
- Source implementation completed before C3 regression tests: canonical package metadata, typed install vocabulary, optional dependency diagnostics/facades, C2 scaffold integration, installation docs, and release-smoke alignment.
- Manual/source-first verification: `C3 source smoke` run #2 (`32442774805`) passed locked dependency sync, exact-six-extra metadata, install vocabulary and scaffold matrix, optional diagnostics, transitive failure preservation, and active-surface removal of `server-uvicorn`.
- `uv.lock` was refreshed because changing optional-dependency metadata correctly made the previous lock stale; locked sync then passed.
- Regression coverage was added/updated for install metadata and vocabulary, optional facades, C2 scaffold combinations, auth CLI optional imports, and release artifact semantics.
- Pre-closure acceptance CI: run #1029 (`32444922842`) on head `e0ad94fb7e455a08058c398efab33dd94cf382cf` passed Python 3.12/3.13/3.14 Ruff format, Ruff lint, `ty`, and full pytest; lowest-direct/latest dependency suites; coverage; strict MkDocs; clean artifact validation; artifact dry-run; and web asset reproducibility.
- All temporary source-smoke, formatter/lint-writer, maintenance workflow, and trigger/debug artifacts were removed; canonical `.github/workflows/ci.yml` was restored byte-for-byte before acceptance verification.
- Closure documentation updates this execution record, `CHANGELOG.md`, and the roadmap from C3 **Complete** to C4 **Next**. Because these documentation commits change the branch head, one final exact-head full CI run is required before C3 completion is reported.
- Merge/release/tag/version-bump/TestPyPI/PyPI publication remain out of scope until separately requested.
