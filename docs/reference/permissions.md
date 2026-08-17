# Permissions

Rakit uses allow-only permission requirements. A principal receives resolved permission keys from
the authentication backend and an operation proceeds only when its compiled requirement matches.

Common generated keys are scoped by Admin id, for example:

```text
operations.access
operations.resources.widgets.read
operations.pages.report.view
operations.actions.refresh_report.execute
```

The compiler is the authority for generated permission requirements; applications should not infer
permissions from URL strings. Custom declarations may provide an explicit `PermissionRequirement`
when the public type allows it.

Authorization is re-evaluated at execution boundaries. GET-time visibility or an earlier signed
confirmation is not a durable authorization grant for a later POST.

`superuser_bypass` is configurable on Admin. It bypasses matching permission keys for an already
authenticated superuser; it does not bypass authentication, input validation, transaction rules, or
other request security checks.
