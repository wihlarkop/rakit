# Resources

A resource is a named admin surface over a `DataSource`. `ResourceAdmin` is backend-neutral;
`ModelAdmin` delegates model claiming to an installed adapter such as SQLAlchemy.

Declare only fields that are safe for each capability:

- `list_fields` and `detail_fields` control visible read fields.
- `filter_fields`, `search_fields`, and `sort_fields` are explicit query allowlists.
- `relationships` declares portable relationship metadata.
- `actions` declares resource/record/bulk actions.
- generated API policy is opt-in through the resource API definition.

A query string cannot promote an undeclared field into a filter/search/sort capability. Invalid
operators and duplicate/contradictory values are rejected before adapter execution.

Use `ModelAdmin` only after installing exactly one adapter that can claim its model. Zero claimers
and ambiguous claimers are configuration errors.

## SQLAlchemy ORM and Core

`rakit-sqlalchemy` contains two distinct persistence integrations. The existing
`persistence.sqlalchemy` provider claims SQLAlchemy ORM mapped classes and remains the default
SQLAlchemy experience. The `persistence.sqlalchemy-core` provider claims native
`sqlalchemy.Table` objects; it does not synthesize ORM classes or take ownership of application
metadata.

The Core provider proves all five canonical v1 capabilities: `persistence.read`,
`persistence.write`, `persistence.relationships`, `transactions.root-uow`, and
`concurrency.atomic-optimistic`. Relationship execution uses explicit table/FK bindings and
mapping records; it does not synthesize ORM classes. Generated scalar and composed graph writes
share one root `AsyncConnection` / transaction, and optimistic UPDATE/DELETE operations include
identity plus expected-state predicates in their authoritative SQL mutation.

Core advertises relationship and atomic-concurrency support because those behaviors are covered by
the same neutral conformance contracts as SQLAlchemy ORM. Foreign keys or a version-looking column
alone do not promote a resource; the adapter must provide the scoped, fail-closed behavior required
by the contract.

SQLAlchemy ORM and Core may be installed together because their claim subjects are disjoint:
mapped ORM classes are handled by `persistence.sqlalchemy`, while native `Table` objects are
handled by `persistence.sqlalchemy-core`.

For a minimal custom source see `examples/custom_datasource`; for SQLAlchemy ORM see
`examples/fastapi_sqlalchemy`.
