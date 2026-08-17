# Custom Storage

Implement the portable `FileStorage` protocol when files belong in an object store or application-
specific backend.

A backend exposes a stable `storage_id` and async `save`, `delete`, `resolve_access` plus streaming
`open`. `save` receives `TemporaryUpload` and returns an immutable `StoredFile` descriptor. Keys must
be backend-portable normalized relative POSIX keys; never derive the object path directly from the
browser filename.

Access should be private by default. A backend that supports public or signed access returns that
choice explicitly through `FileAccess`. The web private-download route still owns resource
authorization for framework-managed private files.

Respect `OperationContext` cancellation/deadline checkpoints where provided and clean up partial
writes on failure. Storage/database consistency is best-effort compensation, not a distributed
transaction.

Before publishing a backend, run `rakit_core.testing.StorageContractSuite`. The built-in
`LocalStorage` is the reference implementation.
