import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run core AnyIO tests on Rakit's supported asyncio backend."""
    return "asyncio"
