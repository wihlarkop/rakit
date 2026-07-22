# Minimal read-only example

This example uses only the Rakit public facade and a small in-memory read data source. From the
repository root:

```console
uv run --extra examples rakit check examples.minimal.main:admin
uv run --extra examples rakit routes examples.minimal.main:admin
uv run --extra examples python -m examples.minimal.main
```

Open `http://127.0.0.1:8000/products`. Bookmarkable queries use repeatable
`filter=<field>:<operator>:<value>` parameters plus `search`, `sort`, `page`, `per_page`, and
`count_policy` (`exact`, `disabled`, or `deferred`).
