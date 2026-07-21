import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

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

    def __init__(self, *, on_stopping: Callable[[], Awaitable[None]] | None = None) -> None:
        self.state: RuntimeState = RuntimeState.CREATED
        self._on_stopping = on_stopping
        self._checks: dict[str, _HealthCheck] = {}
        self._cache: dict[str, tuple[bool, float]] = {}

    def register_health_check(
        self,
        name: str,
        check: Callable[[], Awaitable[bool]],
        *,
        critical: bool,
        timeout_seconds: float = 2.0,
        cache_seconds: float = 5.0,
    ) -> None:
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
            self.state = RuntimeState.READY
        except Exception:
            self.state = RuntimeState.FAILED
            raise

    async def run_shutdown(self) -> None:
        # Readiness must flip to 503 the instant we leave READY, before any
        # cleanup runs.
        self.state = RuntimeState.DRAINING
        self.state = RuntimeState.STOPPING
        if self._on_stopping is not None:
            await self._on_stopping()
        self.state = RuntimeState.STOPPED

    async def check_ready(self) -> bool:
        if self.state is not RuntimeState.READY:
            return False
        for check in self._checks.values():
            if not check.critical:
                continue
            if not await self._evaluate_check(check):
                return False
        return True

    async def check_health(self) -> bool:
        # Process liveness only -- deliberately never touches registered
        # checks or any database.
        return self.state not in (RuntimeState.FAILED, RuntimeState.STOPPED)

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
