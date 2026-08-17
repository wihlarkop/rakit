# Relationships

This example declares the relationship shapes Rakit v0.1 supports while keeping the
persistence adapter deliberately small and readable.

It demonstrates:

- many-to-one (`orders.customer`)
- many-to-many (`orders.tags`)
- one-to-many (`orders.line_items`)
- association object (`orders.enrollments` -> `courses`)

Check the declarations:

```bash
uv run rakit check examples.relationships.main:admin
```

Run the admin:

```bash
uv run rakit run examples.relationships.main:admin
```

The data source is intentionally read-only. Writable relationship examples belong in
applications that install a persistence adapter capable of the corresponding mutation
contracts.
