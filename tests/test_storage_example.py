from pathlib import Path

import pytest


@pytest.mark.anyio
async def test_storage_example_round_trips_private_object(tmp_path: Path) -> None:
    from examples.storage.main import run_demo

    stored, loaded = await run_demo(tmp_path)

    assert stored.storage_id == "documents"
    assert stored.key.startswith("demo/")
    assert stored.key.endswith(".txt")
    assert loaded == b"Rakit private storage example\n"
    assert not (tmp_path / "documents" / stored.key).exists()
