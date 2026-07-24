import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol, runtime_checkable

_DEFAULT_MAX_TRACKED_KEYS = 10_000


def _default_key(*, admin_id: str, identifier: str, client_ip: str) -> str:
    # The raw identifier (e.g. an email address) is never stored as-is in
    # the limiter's key space.
    identifier_hash = hashlib.sha256(identifier.encode()).hexdigest()
    return f"{admin_id}:{identifier_hash}:{client_ip}"


@runtime_checkable
class RateLimiter(Protocol):
    """The contract `Admin(login_rate_limiter=...)` accepts. `production_safe`
    is a self-declared attribute, not something this protocol can verify --
    it exists so a limiter backed by a shared store (Redis or equivalent)
    can declare itself safe for a multi-process production deployment,
    while the bundled in-memory `LoginRateLimiter` always declares
    `production_safe = False`.
    """

    production_safe: bool

    def check(self, *, admin_id: str, identifier: str, client_ip: str) -> bool: ...


class LoginRateLimiter:
    """In-memory, fixed-window login rate limiter keyed by
    (admin_id, sha256(identifier), client_ip).

    Development-only (`production_safe = False`): this is a single-process,
    in-memory backend. A production deployment needs a shared store (Redis
    or equivalent) so the limit holds across worker processes -- see the
    framework design's production-validation requirements for
    development-only shared stores. `Admin` refuses to enable this limiter
    when `debug=False` and authentication is configured (see
    `rakit_web.security.validation.validate_rate_limiter_for_production`);
    a caller must supply their own `production_safe = True` implementation
    instead.

    Total tracked keys are bounded by `max_tracked_keys` via LRU eviction,
    so an unbounded number of distinct identifiers (e.g. a credential-
    stuffing sweep trying many different emails) cannot grow this
    structure without limit -- the least-recently-touched key is evicted
    once the bound is exceeded. A `threading.Lock` guards all mutations,
    since nothing about this class assumes it is only ever called from a
    single OS thread.
    """

    production_safe: bool = False

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_tracked_keys: int = _DEFAULT_MAX_TRACKED_KEYS,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_tracked_keys <= 0:
            raise ValueError("max_tracked_keys must be positive")
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._max_tracked_keys = max_tracked_keys
        self._attempts: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, *, admin_id: str, identifier: str, client_ip: str) -> bool:
        """Record this attempt and return whether it is allowed.

        Every call (allowed or not) counts toward the window -- a denied
        attempt still occupies a slot, so a client cannot reset its own
        limiter by repeatedly failing, then trying again immediately.
        """
        key = _default_key(admin_id=admin_id, identifier=identifier, client_ip=client_ip)
        now = self._clock()
        cutoff = now - self._window_seconds

        with self._lock:
            attempts = self._attempts.get(key)
            if attempts is None:
                attempts = []
                self._attempts[key] = attempts
            else:
                self._attempts.move_to_end(key)

            while attempts and attempts[0] < cutoff:
                attempts.pop(0)

            allowed = len(attempts) < self._max_attempts
            attempts.append(now)

            while len(self._attempts) > self._max_tracked_keys:
                self._attempts.popitem(last=False)

            return allowed
