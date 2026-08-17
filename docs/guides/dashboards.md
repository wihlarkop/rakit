# Dashboards

A dashboard is a permission-aware server-rendered landing surface composed from registered widgets,
resource launchers, and pages.

Register widgets with `admin.register_widget()` and optionally register one explicit
`DashboardDefinition`. Without an explicit definition Rakit builds a default dashboard from the
registered widgets.

Widgets support eager and lazy loading. A lazy widget is fetched through its own framework-owned
route; one failing widget renders an isolated error result rather than taking down the whole
dashboard. Widget execution uses the application operation scope and a bounded timeout.

The built-in navigation and dashboard hide launchers/widgets the current principal cannot access.
Theme preference is `system`, `light`, or `dark`, persists locally, and is resolved by a local
content-addressed script under the existing CSP.

Run the complete showcase:

```bash
uv run rakit run examples.dashboard.main:admin
```

The example includes eager, lazy, and intentionally failing widget behavior.
