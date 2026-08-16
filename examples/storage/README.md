# Local storage example

Run the backend-only storage demo with:

```bash
uv run python -m examples.storage.main
```

It registers two named `LocalStorage` backends through `LocalStoragePlugin`, stores a private document using a generated object key, streams it back through the `FileStorage` contract, verifies that direct public access is not exposed, and deletes the object at the end of the run.

The demo intentionally stays independent from authentication and database setup. File-field upload forms and permission-rechecked private downloads are covered by the `rakit-web` integration tests.
