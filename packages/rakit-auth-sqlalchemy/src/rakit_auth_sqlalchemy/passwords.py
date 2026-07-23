import anyio
from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError


class Argon2PasswordHasher:
    """Argon2id password hashing (via argon2-cffi directly, never a custom
    implementation), with hashing and verification bounded off the event
    loop by a shared `anyio.CapacityLimiter` -- Argon2 is intentionally
    slow, so running it inline would stall the event loop and an
    unbounded number of concurrent `to_thread.run_sync` calls would
    exhaust worker threads under a login-flood."""

    def __init__(self, *, limiter: anyio.CapacityLimiter | None = None) -> None:
        self._hasher = PasswordHasher()
        self._limiter = limiter or anyio.CapacityLimiter(4)

    async def hash(self, password: str) -> str:
        async with self._limiter:
            return await to_thread.run_sync(self._hasher.hash, password)

    async def verify(self, password: str, encoded: str) -> bool:
        async with self._limiter:
            try:
                return await to_thread.run_sync(self._hasher.verify, encoded, password)
            except (VerifyMismatchError, VerificationError, InvalidHash):
                return False

    def needs_rehash(self, encoded: str) -> bool:
        return self._hasher.check_needs_rehash(encoded)
