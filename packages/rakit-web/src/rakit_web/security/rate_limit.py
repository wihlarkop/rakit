import hashlib
import time
from collections import defaultdict
from collections.abc import Callable


def _default_key(*, admin_id: str, identifier: str, client_ip: str) -> str:
    # The raw identifier (e.g. an email address) is never stored as-is in
    # the limiter's key space.
    identifier_hash = hashlib.sha256(identifier.encode()).hexdigest()
    return f"{admin_id}:{identifier_hash}:{client_ip}"


class LoginRateLimiter:
    """In-memory, fixed-window login rate limiter keyed by
    (admin_id, sha256(identifier), client_ip).

    Development-only: this is a single-process, in-memory backend. A
    production deployment needs a shared store (Redis or equivalent) so the
    limit holds across worker processes -- see the framework design's
    production-validation requirements for development-only shared stores.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def check(self, *, admin_id: str, identifier: str, client_ip: str) -> bool:
        """Record this attempt and return whether it is allowed.

        Every call (allowed or not) counts toward the window -- a denied
        attempt still occupies a slot, so a client cannot reset its own
        limiter by repeatedly failing, then trying again immediately.
        """
        key = _default_key(admin_id=admin_id, identifier=identifier, client_ip=client_ip)
        now = self._clock()
        attempts = self._attempts[key]
        cutoff = now - self._window_seconds
        while attempts and attempts[0] < cutoff:
            attempts.pop(0)
        if len(attempts) >= self._max_attempts:
            attempts.append(now)
            return False
        attempts.append(now)
        return True
