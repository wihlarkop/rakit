# Adapter Contract Tests

Plan 07 exposes reusable testing helpers from `rakit_core.testing` so third-party adapters can prove
behavior against the same backend-neutral expectations as official adapters.

```python
from rakit_core.testing import DataSourceContractSuite, StorageContractSuite
```

`DataSourceContractSuite` is capability-aware. Read contracts cover identity/list/detail/not-found,
filters/search, deterministic sorting with identity tie-breakers, stable pagination, and count
policy semantics. Write/transaction/concurrency/relationship/cancellation/error checks run only when
the adapter declares the matching capability.

`StorageContractSuite` checks save/open/delete, generated key safety, size/checksum, collision
avoidance, cleanup, private access, and descriptor ownership.

Construct the suite with the fixture/factory hooks defined by the class, then call the relevant
assertions from your normal pytest tests. Do not subclass SQLAlchemy/LocalStorage merely to satisfy
the suite; the purpose is to validate structural compatibility.

The repository's official runs live under `packages/rakit-sqlalchemy/tests/contract` and
`packages/rakit-storage-local/tests/contract`, and core tests include intentionally broken fakes to
prove important contract assertions can fail.
