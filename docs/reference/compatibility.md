# Compatibility

Rakit follows Semantic Versioning. All official distributions are versioned in lockstep; the
current unreleased alpha target is `0.1.0a1`. A supported installation should not intentionally mix
official Rakit package versions from different releases.

## Pre-1.0 changes and deprecation

Before 1.0, documented public APIs may still evolve. When practical, a public breaking change is
announced with `RakitDeprecationWarning` and retained through at least two subsequent minor-version
lines before removal. Security vulnerabilities, unsafe defaults, or contracts that cannot be
implemented correctly may require a faster break; those changes must be prominent in the changelog
and migration guidance.

Supported Python starts at 3.12. Removing a supported Python line is a compatibility change and must
be documented with the release that changes the floor.

## Stability categories

- **stable**: documented application/extension facade for the current pre-1.0 policy;
- **provisional**: documented but expected to receive alpha feedback-driven refinement;
- **experimental**: no two-minor deprecation expectation unless stated otherwise;
- **internal**: no compatibility promise.

## Plugin API

Third-party plugins/adapters should target documented compiler/service/capability protocols and the
reusable contract suites. There is no independent plugin-protocol version number in the alpha: the
Rakit package version is the compatibility version. A future independent plugin ABI/API version
would be introduced explicitly rather than inferred from private compiler objects.

## Events

Only event names/payloads explicitly documented as public are compatibility surfaces. Public event
payload evolution is additive by default and consumers should ignore unknown fields. Removing or
changing the meaning/type of an existing documented payload field follows the public deprecation
policy unless a security/correctness exception applies. Undocumented internal events are internal.

## Templates

Template compatibility covers documented override/context/block seams, not arbitrary DOM structure,
Tailwind utility strings, or private template filenames. Application-owned custom templates remain
the application's responsibility. Copying an entire internal template creates a stronger coupling
than using a documented extension seam.

## Migrations

Published migration files are immutable. Corrections ship as a new migration rather than editing a
migration users may already have applied. See `docs/migrations/README.md`.
