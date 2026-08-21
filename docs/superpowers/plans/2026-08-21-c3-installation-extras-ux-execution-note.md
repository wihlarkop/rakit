# C3 Install Command Interface Note

The implementation plan defined `uv_add_command(...)` as subprocess argv. During source execution, runtime diagnostics also needed a shell-display form that preserves quoting without putting quote characters into argv.

C3 therefore uses both internal helpers:

```python
uv_add_command(*extras: InstallExtra, packages: tuple[str, ...] = ()) -> tuple[str, ...]
format_uv_add_command(*extras: InstallExtra, packages: tuple[str, ...] = ()) -> str
```

`uv_add_command(...)` is for subprocess/scaffold argv. `format_uv_add_command(...)` is for human-readable hints such as:

```text
uv add "rakit[sqlalchemy]"
```

This clarifies, rather than changes, the approved design requirement that canonical install command formatting have one source of truth.
