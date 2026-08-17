"""The local storage adapter must pass the reusable FileStorage contract suite.

This is the official proof that ``rakit-storage-local`` honors the backend
neutral storage contract: save/open/delete round trips, generated key safety,
size/checksum accuracy, collision avoidance, cleanup semantics, and private-by
-default access behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rakit_core.testing import StorageContractSuite
from rakit_storage_local.storage import LocalStorage


class LocalStorageContract(StorageContractSuite):
    def __init__(self, root: Path) -> None:
        self._root = root

    async def make_storage(self) -> LocalStorage:
        return LocalStorage(
            storage_id="contract",
            root=self._root,
            allowed_extensions=(".txt",),
            chunk_size=4096,
        )


@pytest.mark.anyio
async def test_local_storage_passes_storage_contract(tmp_path: Path) -> None:
    await LocalStorageContract(tmp_path).run_all()
