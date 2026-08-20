# Migration Policy

Database migrations shipped by an official Rakit package are append-only release artifacts.

Rakit-owned persistence also follows the repository namespace invariant documented in
[`rakit-owned-persistence-namespace.md`](rakit-owned-persistence-namespace.md): framework-owned
objects use a `rakit_` namespace and each Rakit Alembic stream owns a dedicated version table rather
than sharing the host application's `alembic_version` table.

## Rules

1. Never edit a migration that has been included in a published package/tag.
2. Correct an already-published migration with a new forward migration.
3. Keep migration ordering deterministic and package-local.
4. Test upgrade paths from the oldest supported schema state, not only creation from empty storage.
5. A migration that changes authentication, permissions, sessions, idempotency, or other
   security-sensitive data receives explicit security/rollback review.
6. Document operator action when a migration cannot be safely reversed.
7. Keep Rakit-owned objects inside the documented `rakit_` namespace and keep each Rakit migration
   history independent from the host application's migration history.

During unreleased development a migration may be rewritten only when maintainers have verified it
has never been published or treated as immutable by downstream users. Once a release is tagged,
that exception ends for every migration contained in the artifact.
