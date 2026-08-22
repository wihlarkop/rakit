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

The Core provider currently proves the canonical `persistence.read`, `persistence.write`, and
`transactions.root-uow` v1 capabilities. Generated scalar create, partial update, and delete
operations share one root `AsyncConnection` / transaction, so commit and rollback remain owned by
the Rakit operation lifecycle rather than individual mutation helpers.

Core deliberately does not advertise `persistence.relationships` merely because a table has
foreign keys. It also does not advertise `concurrency.atomic-optimistic`: D3.1 does not introduce
a Core-specific version-field convention solely to chase capability parity. Those capabilities
remain unavailable until a portable declaration and real behavior can satisfy their canonical
contracts without backend-specific semantic distortion.

SQLAlchemy ORM and Core may be installed together because their claim subjects are disjoint:
mapped ORM classes are handled by `persistence.sqlalchemy`, while native `Table` objects are
handled by `persistence.sqlalchemy-core`.

For a minimal custom source see `examples/custom_datasource`; for SQLAlchemy ORM see
`examples/fastapi_sqlalchemy`.
