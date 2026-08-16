# Dashboard example

This example presents the dashboard as a small, runnable operations admin rather than an isolated widget gallery.

It demonstrates:

- a persistent responsive admin shell inspired by mature admin interfaces;
- Tailwind utility-first presentation shared by the shell, dashboard, and resource pages;
- automatic Quick access launchers from registered resources;
- Orders, Customers, Recent operational activity, and Operations runbook list/detail pages;
- search, sorting, pagination, and active navigation state;
- stat, text, list, and table widgets;
- semantic small, medium, and large widget layouts;
- eager and lazy widget loading;
- independent manual widget refresh.

Run it from the repository root:

```bash
uv run rakit run examples.dashboard.main:admin
```

Then open the printed local URL and move between the dashboard and resource pages using the built-in admin navigation.

The example intentionally uses `debug=True`, in-memory data, and no authentication, so it is suitable only for local development.
