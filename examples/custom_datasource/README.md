# Custom DataSource

This example is the smallest useful third-party read adapter shape. `TicketDataSource` explicitly
advertises `DataSourceCapabilities(read=True)` and implements list, count, detail, identity, search,
filtering, sorting, and pagination without inheriting from a Rakit implementation class.

Check it:

```bash
uv run rakit check examples.custom_datasource.main:admin
```

Run it:

```bash
uv run rakit run examples.custom_datasource.main:admin
```

Open <http://127.0.0.1:8000/tickets>. The adapter is intentionally read-only; unsupported write
capabilities remain false rather than failing open.
