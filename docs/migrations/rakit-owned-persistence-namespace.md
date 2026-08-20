# Rakit-Owned Persistence Namespace

Status: enforced architecture invariant for Rakit-owned persistence.

## Purpose

Rakit-owned database objects must be immediately distinguishable from application/domain tables in
a shared database. The convention also prevents migration-history collisions when Rakit and the host
application both use SQLAlchemy/Alembic against the same database.

## Current invariant

Every persistence object owned and migrated by Rakit uses a `rakit_` namespace. Package-specific
ownership remains visible where useful. The built-in SQLAlchemy auth package therefore owns:

- `rakit_auth_users`
- `rakit_auth_roles`
- `rakit_auth_permissions`
- `rakit_auth_user_roles`
- `rakit_auth_role_permissions`
- `rakit_auth_sessions`
- `rakit_auth_idempotency`

Its migration stream uses the dedicated version table `rakit_auth_alembic_version`, never the host
application's default `alembic_version` table.

## Rules for official persistence packages

1. Every table or other persistence object owned and migrated by Rakit uses a `rakit_` prefix.
2. Package-specific ownership should remain visible where useful, for example `rakit_auth_*` rather
   than a generic name that loses provenance.
3. Every Rakit-owned Alembic revision stream uses its own `rakit_*_alembic_version` table. A Rakit
   migration stream must never share the host application's `alembic_version` table.
4. Application/domain tables are never renamed or prefixed by Rakit.
5. Names are fixed and predictable by default. A configurable prefix requires a validated deployment
   use case rather than being added speculatively.
6. Prefix-based names are the cross-database baseline because they work consistently across SQLite,
   MySQL, and PostgreSQL. Backend-specific schemas may be added later as an optional isolation tool,
   not as the only namespace mechanism.

## Requirements for a future violation

If an already-published Rakit-owned object is ever found outside this namespace:

- use an explicit data-preserving rename migration;
- preserve indexes, foreign keys, unique constraints, and revision history;
- never drop and recreate an object that may contain user data;
- provide upgrade and downgrade coverage for supported databases where reversal is safe;
- document old and new object names;
- verify host-application migrations remain independent.

During unreleased development, fix a newly introduced violation before it becomes part of a public
artifact.

## Non-goals

This convention does not:

- rename user/domain tables;
- introduce a universal migration language;
- run production migrations automatically at application startup;
- make the prefix configurable without a real requirement;
- flatten useful package-specific prefixes such as `rakit_auth_` for cosmetic consistency.

The invariant is covered by repository regression checks so future Rakit-owned persistence packages
must opt into the same namespace deliberately.
