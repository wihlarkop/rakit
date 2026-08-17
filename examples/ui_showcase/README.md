# UI Showcase

`examples/ui_showcase` is the visual QA application for Rakit's default admin UI. It intentionally uses the framework's shipped templates, assets, and `.rakit-*` primitives without a private stylesheet.

## Run locally

```powershell
uv sync --extra examples
uv run python -m examples.ui_showcase.main
```

Open `http://127.0.0.1:8000`.

Demo credentials:

```text
Email: operator@example.com
Password: demo-password
```

Useful pages:

- `/` — realistic commerce operations dashboard
- `/orders` — deterministic resource list with enough rows for pagination/filtering
- `/ui-lab` — deterministic component/state inspection surface

The UI Lab is a baseline, not a separate theme. If it needs styling that the default Rakit UI does not provide, the framework UI should be improved in a later UI maturity PR instead of adding showcase-only CSS.
