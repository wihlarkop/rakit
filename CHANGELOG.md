# Changelog

All notable user-facing changes to Rakit are recorded here.

The project follows Semantic Versioning. Until a release is actually tagged, changes stay under
`Unreleased`; the maintainer assigns the final version/date at release time.

## [Unreleased]

### Added

- Initial Rakit framework alpha implementation across runtime/compiler, resources, SQLAlchemy,
  authentication/RBAC, forms and writes, relationships, actions, pages, endpoints, dashboards,
  local storage, themes, accessibility, server adapters, reusable adapter contract suites, official
  examples, documentation, governance, and release verification.
- Release-level integration/security regressions and clean-artifact verification foundations.
- Tag-gated trusted-publishing workflow preparation without a release tag or publish action.

### Security

- Fail-closed configuration, host/proxy, CSRF, permission re-check, concurrency, idempotency,
  confirmation, upload/path, private-file, production-error, and shutdown/readiness release gates.
