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

For a minimal custom source see `examples/custom_datasource`; for SQLAlchemy see
`examples/fastapi_sqlalchemy`.
