# C2 Implementation Plan Interface Clarification

This note is part of the C2 implementation plan and resolves the `PackageResolution` type referenced by Task 1 before source implementation starts.

The existing-project detector returns a typed resolution rather than a bare package string:

```python
@dataclass(frozen=True, slots=True)
class PackageResolution:
    host_package: str | None
    module_package: str
    module_root: Path
```

Semantics:

- conventional `src/my_app` => `host_package="my_app"`, `module_package="my_app.rakit_admin"`, `module_root=<repo>/src/my_app/rakit_admin`;
- conventional flat `my_app` => `host_package="my_app"`, `module_package="my_app.rakit_admin"`, `module_root=<repo>/my_app/rakit_admin`;
- clearly flat/non-package fallback => `host_package=None`, `module_package="rakit_admin"`, `module_root=<repo>/rakit_admin`.

`InitConfig.import_package` stores the full generated module import package (`my_admin` for a new project, `my_app.rakit_admin` or `rakit_admin` for existing-project mode). Renderers therefore never need to infer package placement again.

This clarification does not change the approved product behavior; it only makes the implementation-plan type boundary explicit.