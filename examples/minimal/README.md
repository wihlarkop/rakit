# Minimal read-only example

This example uses only the Rakit public facade and a small in-memory read data source. From the
repository root:

```powershell
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Get-Location).Path
uv run --extra examples rakit check examples.minimal.main:admin
uv run --extra examples rakit routes examples.minimal.main:admin
uv run --extra examples python -m examples.minimal.main
$env:PYTHONPATH = $previousPythonPath
```

`examples` is intentionally repository-private rather than a ninth released distribution, so the
explicit `PYTHONPATH` makes the repository root the composition-root import boundary.

Open `http://127.0.0.1:8000/products`. Bookmarkable queries use repeatable
`filter=<field>:<operator>:<value>` parameters plus `search`, `sort`, `page`, `per_page`, and
`count_policy` (`exact`, `disabled`, or `deferred`).
