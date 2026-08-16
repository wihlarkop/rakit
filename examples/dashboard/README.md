# Dashboard example

This example presents the dashboard as a small, runnable operations admin rather than an isolated widget gallery.

It demonstrates:

- automatic Quick Access launchers from registered resources;
- Orders, Customers, Activity, and Runbook read-only resource pages;
- resource list/detail navigation back to the dashboard;
- stat, text, list, and table widgets;
- semantic small, medium, and large widget layouts;
- eager and lazy widget loading;
- independent manual widget refresh.

Run it from the repository root:

```bash
uv run rakit run examples.dashboard.main:admin
```

Then open the printed local URL. The example intentionally uses `debug=True` and no authentication, so it is suitable only for local development.
