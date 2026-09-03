# Contributing to Rakit

Thanks for helping improve Rakit. The project values small reviewable changes, explicit contracts,
and evidence before compatibility/security claims.

## Development setup

```bash
uv sync --all-packages --dev
uv run ruff format .
uv run ruff check .
uv run ty check
uv run pytest
uv run mkdocs serve
```

Before opening a pull request, use the locked environment where applicable and run the focused tests
for your change plus the full gate that is practical locally.

## Testing

The canonical test command is serial and preserves normal debugging semantics:

```bash
uv run pytest
```

For a faster local full-suite pass, pytest-xdist can use work stealing:

```bash
uv run pytest -n auto --dist worksteal
```

The parallel command is an optional developer shortcut; CI remains serial. Tests that create files,
databases, generated projects, or subprocess workspaces must use pytest-managed temporary paths (or
another worker-isolated resource) rather than fixed shared paths. On the benchmark Windows host,
the final optional command was about 34.7% faster than the final serial median; this is a local
measurement, not a fixed timing guarantee for other machines or CI runners.

## Architecture and dependency direction

Keep portable policy/contracts in `rakit-core`. Web-framework behavior belongs in `rakit-web`;
SQLAlchemy-specific behavior belongs in SQLAlchemy packages; storage/server integrations remain in
their own packages. The `rakit` package is the application facade and must not turn optional
adapters into hard dependencies.

Do not make core import a web framework, ORM, concrete storage backend, or server adapter.

## Development method

Behavior changes should follow TDD: reproduce the missing/incorrect behavior, observe the focused
test fail for that reason, implement the smallest coherent fix, then rerun focused and regression
tests. Tests should exercise real contracts rather than implementation trivia.

Third-party-style DataSource/FileStorage changes must run the reusable adapter contract suites. New
capability claims need both positive and fail-closed tests.

## Public versus internal API

Documented facade/protocol imports receive compatibility review. Undocumented modules and private
names are internal even when importable. A change to permissions, error codes, event payloads,
route names, template extension seams, plugin APIs, or other documented public contracts requires
explicit compatibility review and changelog notes.

## Migrations

Once a migration is published, treat it as immutable. Fix a migration defect with a new migration;
do not edit history that users may already have applied.

## Security-sensitive changes

Authentication, authorization, cookies, CSRF, proxy/host trust, token/crypto behavior, uploads,
path handling, transaction/concurrency semantics, debug/error disclosure, and release publishing
receive additional review. Add both allowed and rejected-path tests; do not weaken a secure default
to make a test/application easier.

Report undisclosed vulnerabilities through the private process in `SECURITY.md`, never a public PR.

## Changelog

User-visible behavior, compatibility changes, deprecations, security fixes, packaging changes, and
release-process changes belong under `CHANGELOG.md` → `Unreleased`. The maintainer moves entries to
a dated release section only when that release is actually tagged.
