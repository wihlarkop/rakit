import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run AnyIO-marked tests on Rakit's supported asyncio backend."""
    return "asyncio"
