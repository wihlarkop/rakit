# Local File Storage

Rakit stores file descriptors through the portable `FileStorage` contract. The descriptor records
storage id, generated object key, original name, content type, size, checksum, and safe metadata;
it does not expose a backend filesystem path.

`LocalStorage` is the built-in private local-filesystem backend. It:

- creates its root explicitly;
- validates a portable storage id and normalized relative prefix;
- generates collision-resistant object keys;
- streams to a temporary file, flushes/fsyncs, then atomically replaces the final path;
- enforces declared and streaming size limits;
- records SHA-256 checksums;
- prevents path traversal/root escape;
- returns private access by default;
- provides async chunked reads and idempotent delete.

Register one or more named stores with `LocalStoragePlugin`. `FileField.storage_id` chooses the
store; the web mutation pipeline stores the resulting descriptor through the same database
mutation path as other fields.

Replacement keeps the previous object until the database mutation succeeds. Newly stored objects
are best-effort compensated when validation or mutation fails. Record deletion removes an object
only when `delete_behavior="delete"` was explicitly configured and database deletion succeeded.

Run the storage-only demonstration with:

```bash
uv run python -m examples.storage.main
```

Cloud/object storage, presigned/direct uploads, resumable uploads, thumbnails, malware scanning,
and durable orphan reconciliation are outside the alpha local-storage contract.
