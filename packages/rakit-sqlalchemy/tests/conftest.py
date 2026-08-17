import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run SQLAlchemy adapter AnyIO tests on Rakit's supported asyncio backend."""
    return "asyncio"
