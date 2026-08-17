import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run Uvicorn adapter AnyIO tests on Rakit's supported asyncio backend."""
    return "asyncio"
