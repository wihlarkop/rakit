# Migration Policy

Database migrations shipped by an official Rakit package are append-only release artifacts.

## Rules

1. Never edit a migration that has been included in a published package/tag.
2. Correct an already-published migration with a new forward migration.
3. Keep migration ordering deterministic and package-local.
4. Test upgrade paths from the oldest supported schema state, not only creation from empty storage.
5. A migration that changes authentication, permissions, sessions, idempotency, or other
   security-sensitive data receives explicit security/rollback review.
6. Document operator action when a migration cannot be safely reversed.

During unreleased development a migration may be rewritten only when maintainers have verified it
has never been published or treated as immutable by downstream users. Once a release is tagged,
that exception ends for every migration contained in the artifact.
