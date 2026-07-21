import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from rakit import Admin, SecretValue
from starlette.types import ASGIApp


class LifespanDriver:
    """Drives the real ASGI lifespan protocol against a Starlette app.

    httpx.ASGITransport only forwards HTTP requests -- it never sends
    lifespan.startup/lifespan.shutdown events, so using it alone would never
    trigger Admin's lifespan function (and therefore never move
    LifecycleManager past CREATED). This driver runs the app's ASGI callable
    against the "lifespan" scope directly, in a background task, so tests
    exercise the genuine startup/shutdown sequence rather than bypassing it
    by calling LifecycleManager methods directly.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._startup_complete = asyncio.Event()
        self._shutdown_complete = asyncio.Event()
        self._startup_failure_message: str | None = None
        self._shutdown_failure_message: str | None = None
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "LifespanDriver":
        async def receive():
            return await self._receive_queue.get()

        async def send(message):
            if message["type"] == "lifespan.startup.complete":
                self._startup_complete.set()
            elif message["type"] == "lifespan.startup.failed":
                self._startup_failure_message = message.get("message", "")
                self._startup_complete.set()
            elif message["type"] == "lifespan.shutdown.complete":
                self._shutdown_complete.set()
            elif message["type"] == "lifespan.shutdown.failed":
                self._shutdown_failure_message = message.get("message", "")
                self._shutdown_complete.set()

        async def run_app() -> None:
            await self._app({"type": "lifespan"}, receive, send)

        self._task = asyncio.create_task(run_app())
        await self._receive_queue.put({"type": "lifespan.startup"})
        await self._startup_complete.wait()
        if self._startup_failure_message is not None:
            raise RuntimeError(f"ASGI lifespan startup failed: {self._startup_failure_message}")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._receive_queue.put({"type": "lifespan.shutdown"})
        await self._shutdown_complete.wait()
        assert self._task is not None
        await self._task
        if self._shutdown_failure_message is not None:
            raise RuntimeError(f"ASGI lifespan shutdown failed: {self._shutdown_failure_message}")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client,
    ):
        yield http_client
