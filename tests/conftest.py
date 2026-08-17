import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run top-level AnyIO tests on Rakit's supported asyncio backend."""
    return "asyncio"
