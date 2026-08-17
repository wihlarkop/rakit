# Custom DataSource

A custom data source implements the structural `DataSource` contract and declares
`DataSourceCapabilities`. It does not need to subclass a framework implementation.

At minimum a read source exposes `fields`, `identity_fields`, `list()`, `count()`, and `detail()`.
Adapters that support richer capabilities must make those claims explicit and satisfy the matching
contract tests.

```python
from rakit.core import DataSourceCapabilities


class MySource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query): ...
    async def count(self, query): ...
    async def detail(self, identity): ...
```

Register it on a `ResourceAdmin.data_source`. See `examples/custom_datasource` for a complete
read-only implementation with filtering/search/sorting/pagination.

Do not claim transactions, writes, or optimistic concurrency unless the adapter actually implements
the corresponding semantics. Run the reusable `rakit_core.testing.DataSourceContractSuite` before
publishing an adapter.
