"""Reusable, capability-aware adapter contract suites for Rakit.

Third-party adapter authors can run these backend-neutral suites against their
own ``DataSource`` and ``FileStorage`` implementations to prove they honor the
public contracts. See :mod:`rakit_core.testing.datasource_contract` and
:mod:`rakit_core.testing.storage_contract` for usage.
"""

from rakit_core.testing.datasource_contract import DataSourceContractSuite
from rakit_core.testing.storage_contract import StorageContractSuite

__all__ = ["DataSourceContractSuite", "StorageContractSuite"]
