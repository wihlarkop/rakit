# Changelog

All notable user-facing changes to Rakit are recorded here.

The project follows Semantic Versioning. Until a release is actually tagged, changes stay under
`Unreleased`; the maintainer assigns the final version/date at release time.

## [Unreleased]

### Added

- Initial Rakit framework implementation across runtime/compiler, resources, SQLAlchemy,
  authentication/RBAC, forms and writes, relationships, actions, pages, endpoints, dashboards,
  local storage, themes, accessibility, server adapters, reusable adapter contract suites, official
  examples, documentation, governance, and verification tooling.
- A complete UI maturity pass covering the application shell, design tokens, reusable components,
  resource list/detail/form flows, bulk and action workflows, relationships/uploads, auth/system
  surfaces, custom pages, responsive behavior, keyboard/accessibility hardening, and final visual
  polish.
- Granian as an explicit optional server adapter alongside Uvicorn.
- User-facing adapter facades including `rakit.server.granian`, neutral `rakit.storage`, and
  `rakit.storage.local` while keeping implementation distributions independently installable.
- Release-level integration/security regressions and clean-artifact verification foundations.
- Reproducible generated-CSS verification and broader installed-artifact checks for bundled web
  runtime assets and optional server adapters.
- A documented `rakit_` namespace invariant for framework-owned persistence and independent Rakit
  migration version tables.
- Tag-gated trusted-publishing workflow preparation without a release tag or publish action.

### Changed

- Public server install guidance now prefers `rakit[uvicorn]` and `rakit[granian]`; the existing
  `server-uvicorn` extra remains a compatibility alias.
- Official examples prefer the `rakit` facade for public contracts and adapters instead of importing
  implementation packages directly when an ergonomic facade exists.

### Security

- Fail-closed configuration, host/proxy, CSRF, permission re-check, concurrency, idempotency,
  confirmation, upload/path, private-file, production-error, and shutdown/readiness verification
  gates.
