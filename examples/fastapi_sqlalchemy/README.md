# FastAPI + SQLAlchemy read-only example

This example declares its optional runtime dependencies in the workspace `examples` extra. It
mounts Rakit at `/admin`, gives Rakit the public `SQLAlchemyPlugin(session_factory=...)` contract,
and keeps engine ownership in the FastAPI lifespan (the current equivalent of `owned=False`).

```powershell
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Get-Location).Path
uv run --extra examples rakit check examples.fastapi_sqlalchemy.main:admin
uv run --extra examples rakit routes examples.fastapi_sqlalchemy.main:admin
uv run --extra examples python -m examples.fastapi_sqlalchemy.main
$env:PYTHONPATH = $previousPythonPath
```

`examples` is intentionally repository-private rather than a ninth released distribution, so the
explicit `PYTHONPATH` makes the repository root the composition-root import boundary.

Open `http://127.0.0.1:8000/admin/users`. The list accepts repeatable
`filter=<field>:<operator>:<value>` parameters plus `search`, `sort`, `page`, `per_page`, and
`count_policy` (`exact`, `disabled`, or `deferred`). All routes in this example are read-only.
