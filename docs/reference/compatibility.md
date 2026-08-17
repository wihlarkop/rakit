# Compatibility

Rakit follows Semantic Versioning. All official distributions are versioned in lockstep; the
current unreleased alpha target is `0.1.0a1`.

Before 1.0, documented public APIs may still evolve. When practical, a public breaking change is
announced with `RakitDeprecationWarning` and kept through at least two subsequent minor-version
lines before removal. Security vulnerabilities, unsafe defaults, or contracts that cannot be
implemented correctly may require a faster break; those changes must be called out prominently in
the changelog and migration guidance.

Supported Python starts at 3.12. The CI matrix covers the supported interpreter lines declared by
the project.

Compatibility categories:

- **stable**: documented application/extension facade for the current pre-1.0 policy;
- **provisional**: documented but expected to receive alpha feedback-driven refinement;
- **experimental**: no two-minor deprecation expectation unless stated otherwise;
- **internal**: no compatibility promise.

Third-party plugins/adapters should target documented capability/protocol and testing surfaces. A
plugin must not depend on compiler/private storage internals. Public event payloads are additive by
default; consumers should ignore unknown fields. Template compatibility covers documented extension
seams rather than arbitrary DOM/classes or copied internal templates.

Published migration files are immutable. Corrections ship as a new migration rather than editing a
migration users may already have applied.
