import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run local-storage AnyIO tests on Rakit's supported asyncio backend."""
    return "asyncio"
