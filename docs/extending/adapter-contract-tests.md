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

## D1 capability conformance

Phase D1 adds a separate, versioned conformance layer for the canonical adapter capability
vocabulary. This layer makes an advertised capability a hard promise: canonical prerequisites must
also be advertised and the matching capability contract must pass. All canonical contracts start at
version 1 without renaming existing identifiers.

D1 intentionally keeps that capability-level registry, runner, harness protocols, and conformance
matrix as **maintainer-internal infrastructure**. They are being pressure-tested by the schema,
persistence, and web adapter work planned for D2-D4 before Rakit freezes a public adapter-authoring
SDK in D5. The existing public `DataSourceContractSuite` and `StorageContractSuite` above are not
removed or made private by D1.

The first-party proof mapping for D1 is:

| Integration | Canonical capabilities | Behavioral evidence |
| --- | --- | --- |
| `persistence.sqlalchemy` | read, write, relationships, root UoW, atomic optimistic concurrency | datasource contract plus generated mutation, relationship, UoW, and concurrency regression suites in `packages/rakit-sqlalchemy/tests/` |
| `schema.pydantic` | field introspection, input validation, output serialization, partial update | Pydantic adapter conformance regression in `packages/rakit-web/tests/test_web_adapter_capability_conformance.py` |
| `web.starlette` | ASGI, HTTP routing, streaming response | raw-ASGI conformance regression in `packages/rakit-web/tests/test_web_adapter_capability_conformance.py` |

The capability-level matrix is maintainer evidence, not a third-party certification or compatibility
badge. A future public authoring/testing surface may reuse these internals, but D5 owns that API
decision.
