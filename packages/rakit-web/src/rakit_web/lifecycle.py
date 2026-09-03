import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import cast

from rakit_core.errors import ErrorCode, RakitError

logger = logging.getLogger(__name__)


class RuntimeState(StrEnum):
    CREATED = "created"
    COMPILING = "compiling"
    STARTING = "starting"
    READY = "ready"
    DRAINING = "draining"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class _HealthCheck:
    name: str
    check: Callable[[], Awaitable[bool]]
    critical: bool
    timeout_seconds: float
    cache_seconds: float


class LifecycleManager:
    """Owns the runtime state machine plus health/readiness checks.

    Health is intentionally dumber than readiness: it only reflects process
    liveness and never calls a registered check or a database. Readiness
    reflects both the runtime state and the outcome of all registered
    critical health checks.
    """

    def __init__(
        self,
        *,
        max_concurrent_checks: int = 5,
    ) -> None:
        if max_concurrent_checks < 1:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="max_concurrent_checks must be >= 1 (a value of 0 would make the "
                "health-check semaphore block forever).",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={"max_concurrent_checks": max_concurrent_checks},
            )
        self.state: RuntimeState = RuntimeState.CREATED
        self._starting_callbacks: list[Callable[[], Awaitable[None]]] = []
        self._stopping_callbacks: list[Callable[[], Awaitable[None]]] = []
        self._checks: dict[str, _HealthCheck] = {}
        self._cache: dict[str, tuple[bool, float]] = {}
        self._check_semaphore = asyncio.Semaphore(max_concurrent_checks)

    def register_starting_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Register fail-fast application initialization before readiness.

        Startup callbacks run in registration order after the application
        service resolver has opened and before the runtime transitions to
        ``READY``. A callback failure marks startup failed and propagates to
        the ASGI server instead of serving a partially initialized admin.
        """

        self._starting_callbacks.append(callback)

    def register_stopping_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._stopping_callbacks.append(callback)

    def register_health_check(
        self,
        name: str,
        check: Callable[[], Awaitable[bool]],
        *,
        critical: bool,
        timeout_seconds: float = 2.0,
        cache_seconds: float = 5.0,
    ) -> None:
        if not name:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Health check name must be non-empty.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={"name": name},
            )
        if timeout_seconds <= 0:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Health check timeout_seconds must be > 0.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={"name": name, "timeout_seconds": timeout_seconds},
            )
        if cache_seconds < 0:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Health check cache_seconds must be >= 0.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={"name": name, "cache_seconds": cache_seconds},
            )
        if name in self._checks:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=f"Health check {name!r} is already registered.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={"name": name},
            )
        self._checks[name] = _HealthCheck(
            name=name,
            check=check,
            critical=critical,
            timeout_seconds=timeout_seconds,
            cache_seconds=cache_seconds,
        )

    async def run_startup(self) -> None:
        try:
            self.state = RuntimeState.COMPILING
            self.state = RuntimeState.STARTING
            for callback in self._starting_callbacks:
                await callback()
            self.state = RuntimeState.READY
        except Exception:
            self.state = RuntimeState.FAILED
            raise

    async def run_shutdown(self) -> None:
        # Readiness must flip to 503 the instant we leave READY, before any
        # cleanup runs.
        self.state = RuntimeState.DRAINING
        self.state = RuntimeState.STOPPING
        # Shutdown remains cleanup-first rather than fail-fast: run every
        # registered callback in reverse registration order (LIFO, matching
        # AsyncExitStack's reverse acquisition-order close discipline). Keep
        # failures observable after all callbacks have had an opportunity to
        # run; silently logging them would make the ASGI shutdown contract
        # report success for a failed Rakit cleanup.
        failures: list[BaseException] = []
        cancellation: BaseException | None = None
        for callback in reversed(self._stopping_callbacks):
            try:
                await callback()
            except BaseException as error:
                if isinstance(error, asyncio.CancelledError):
                    cancellation = cancellation or error
                    continue
                failures.append(error)
                logger.exception("Shutdown cleanup callback %r failed", callback)
        self.state = RuntimeState.STOPPED
        if cancellation is not None:
            if failures:
                raise BaseExceptionGroup(
                    "Shutdown cleanup was cancelled and also failed",
                    [cancellation, *failures],
                )
            raise cancellation
        if failures:
            if all(isinstance(error, Exception) for error in failures):
                raise ExceptionGroup(
                    "Shutdown cleanup callbacks failed",
                    [cast(Exception, error) for error in failures],
                )
            raise BaseExceptionGroup("Shutdown cleanup callbacks failed", failures)

    async def check_ready(self) -> bool:
        if self.state is not RuntimeState.READY:
            return False
        critical_checks = [check for check in self._checks.values() if check.critical]
        if not critical_checks:
            return True
        results = await asyncio.gather(
            *(self._evaluate_check_bounded(check) for check in critical_checks)
        )
        return all(results)

    async def check_health(self) -> bool:
        # Process liveness only -- deliberately never touches registered
        # checks or any database.
        return self.state not in (RuntimeState.FAILED, RuntimeState.STOPPED)

    async def _evaluate_check_bounded(self, check: _HealthCheck) -> bool:
        async with self._check_semaphore:
            return await self._evaluate_check(check)

    async def _evaluate_check(self, check: _HealthCheck) -> bool:
        cached = self._cache.get(check.name)
        now = time.monotonic()
        if cached is not None:
            result, expiry = cached
            if now < expiry:
                return result

        try:
            result = await asyncio.wait_for(check.check(), timeout=check.timeout_seconds)
        except Exception:
            logger.warning("Health check %r failed", check.name, exc_info=True)
            result = False

        self._cache[check.name] = (bool(result), now + check.cache_seconds)
        return bool(result)
