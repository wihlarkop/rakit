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
            assert self._task is not None
            task_error: BaseException | None = None
            try:
                await self._task
            except BaseException as error:
                task_error = error
            raise RuntimeError(
                f"ASGI lifespan startup failed: {self._startup_failure_message}"
            ) from task_error
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._receive_queue.put({"type": "lifespan.shutdown"})
        await self._shutdown_complete.wait()
        assert self._task is not None
        await self._task
        if self._shutdown_failure_message is not None:
            raise RuntimeError(f"ASGI lifespan shutdown failed: {self._shutdown_failure_message}")


# C2A intentionally upgrades requires_concurrency from a GET/POST precheck to
# a strong atomic contract. These B2B2 tests pin the superseded precheck-only
# behavior and are kept strict-xfailed until C2B replaces them with the real
# managed atomic mutation path. strict=True makes an unexpected XPASS fail the
# suite so this transition marker cannot silently become permanent.
_C2A_SUPERSEDED_PRECHECK_TESTS = {
    "test_auth_enforcement.py::test_actions_requiring_concurrency_fail_closed",
    "test_auth_enforcement.py::test_concurrent_record_action_missing_provider_fails_closed",
    "test_auth_enforcement.py::test_concurrent_get_issues_token_without_reserving_or_executing",
    "test_auth_enforcement.py::test_concurrent_post_with_unchanged_record_succeeds",
    "test_auth_enforcement.py::test_concurrent_post_with_stale_record_fails_before_executor",
    "test_auth_enforcement.py::test_concurrency_token_for_one_record_cannot_authorize_another",
    "test_auth_enforcement.py::test_snapshot_concurrency_provider_serves_concurrent_action",
    "test_auth_enforcement.py::test_concurrent_off_scope_record_stays_inaccessible",
    "test_auth_enforcement.py::test_stale_concurrent_post_never_reaches_operation_plan",
    "test_actions.py::test_stale_concurrency_is_rejected_before_execution",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    superseded = _C2A_SUPERSEDED_PRECHECK_TESTS
    for item in items:
        # anyio appends parametrization such as ``[asyncio]`` to the node id;
        # normalize that suffix before matching our stable file::test names.
        base_nodeid = item.nodeid.split("[", 1)[0]
        if any(base_nodeid.endswith(suffix) for suffix in superseded):
            item.add_marker(
                pytest.mark.xfail(
                    reason=(
                        "C2A supersedes the precheck-only action concurrency seam; "
                        "C2B owns the replacement atomic managed-mutation path"
                    ),
                    strict=True,
                )
            )


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
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        yield http_client
