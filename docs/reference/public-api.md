# Public API

Rakit's compatibility promise follows documented import surfaces rather than every importable
module in the repository.

## Stable for the alpha line

These are the primary application-facing surfaces and receive compatibility review:

- `rakit`: `Admin`, `ResourceAdmin`, `ModelAdmin`, dashboard/page/action/endpoint/relationship public
  declarations and result types;
- `rakit.core`: portable data-source/query/auth/DI/event/operation/permission contracts;
- `rakit.sqlalchemy`: the documented SQLAlchemy plugin/mutation/relationship facade;
- `rakit.auth.sqlalchemy`: documented SQLAlchemy auth facade;
- `rakit_storage` and `rakit_storage_local`: documented storage contracts/backends;
- `rakit_core.testing`: adapter contract suites for extension authors.

"Stable" here means stable within the published pre-1.0 policy, not a 1.0 compatibility promise.

## Provisional

Template extension contracts, generated API details, advanced response escape hatches, and some
adapter capability surfaces are provisional while alpha feedback is collected.

## Experimental

Features explicitly documented as experimental may change more quickly and should not be used as a
long-lived compatibility boundary without pinning Rakit.

## Internal

Undocumented modules, names beginning with `_`, compiler implementation storage, concrete route
helper internals, and test-only fixtures are internal even if Python allows importing them. Examples
and documentation intentionally avoid those imports.
