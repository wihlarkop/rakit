# Internal tools

A compact internal-admin composition showing four extension surfaces together:

- a custom page at `/reports`
- a page action (`refresh_report`)
- an application-scoped `ReportService` registered in Rakit's service registry
- a typed JSON endpoint at `/api/report`

The example uses explicit constructor/closure injection for the service so application code keeps
its dependencies visible while the same service instance is registered application-wide.

Check it:

```bash
uv run rakit check examples.internal_tools.main:admin
```

Run it:

```bash
uv run rakit run examples.internal_tools.main:admin
```

The JSON endpoint is public for demonstration. The page is authenticated; use
`operator@example.com` / `demo-password`. The in-memory auth/session implementation is development
only.
