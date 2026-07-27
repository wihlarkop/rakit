import threading

import pytest
from rakit_core.errors import RakitError
from rakit_web.security.rate_limit import LoginRateLimiter, RateLimiter
from rakit_web.security.validation import validate_rate_limiter_for_production


def test_allows_attempts_under_the_limit() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60.0)
    for _ in range(3):
        assert limiter.check(
            admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1"
        )


def test_denies_attempts_over_the_limit() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60.0)
    for _ in range(3):
        limiter.check(admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1")
    assert not limiter.check(
        admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1"
    )


def test_limits_are_scoped_per_identifier() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60.0)
    assert limiter.check(admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1")
    assert not limiter.check(
        admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1"
    )
    assert limiter.check(admin_id="operations", identifier="grace@example.com", client_ip="1.1.1.1")


def test_limits_are_scoped_per_client_ip() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60.0)
    assert limiter.check(admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1")
    assert not limiter.check(
        admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1"
    )
    assert limiter.check(admin_id="operations", identifier="ada@example.com", client_ip="2.2.2.2")


def test_limits_are_scoped_per_admin_id() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=60.0)
    assert limiter.check(admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1")
    assert limiter.check(admin_id="other-admin", identifier="ada@example.com", client_ip="1.1.1.1")


def test_window_expiry_allows_new_attempts() -> None:
    clock = [0.0]
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=10.0, clock=lambda: clock[0])
    assert limiter.check(admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1")
    assert not limiter.check(
        admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1"
    )
    clock[0] = 11.0
    assert limiter.check(admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1")


def test_development_limiter_is_not_production_safe_by_default() -> None:
    limiter = LoginRateLimiter()
    assert limiter.production_safe is False


def test_development_limiter_satisfies_the_rate_limiter_protocol() -> None:
    limiter: RateLimiter = LoginRateLimiter()
    assert isinstance(limiter, RateLimiter)


def test_constructor_rejects_non_positive_max_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        LoginRateLimiter(max_attempts=0)
    with pytest.raises(ValueError, match="max_attempts"):
        LoginRateLimiter(max_attempts=-1)


def test_constructor_rejects_non_positive_window_seconds() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        LoginRateLimiter(window_seconds=0)
    with pytest.raises(ValueError, match="window_seconds"):
        LoginRateLimiter(window_seconds=-1.0)


def test_constructor_rejects_non_positive_max_tracked_keys() -> None:
    with pytest.raises(ValueError, match="max_tracked_keys"):
        LoginRateLimiter(max_tracked_keys=0)


def test_total_tracked_keys_are_bounded_via_lru_eviction() -> None:
    """10,000 unique identifiers must not retain 10,000 dictionary entries
    forever -- once max_tracked_keys is exceeded, the least-recently-used
    key is evicted so memory stays bounded regardless of how many distinct
    identifiers have ever been seen."""
    limiter = LoginRateLimiter(max_attempts=5, window_seconds=60.0, max_tracked_keys=100)

    for index in range(150):
        limiter.check(
            admin_id="operations", identifier=f"user-{index}@example.com", client_ip="1.1.1.1"
        )

    assert len(limiter._attempts) <= 100


def test_lru_eviction_keeps_the_most_recently_used_key() -> None:
    limiter = LoginRateLimiter(max_attempts=5, window_seconds=60.0, max_tracked_keys=2)

    limiter.check(admin_id="operations", identifier="a@example.com", client_ip="1.1.1.1")
    limiter.check(admin_id="operations", identifier="b@example.com", client_ip="1.1.1.1")
    # Touch "a" again so it becomes the most-recently-used of the two.
    limiter.check(admin_id="operations", identifier="a@example.com", client_ip="1.1.1.1")
    # A third distinct key must evict "b" (the least-recently-used), not "a".
    limiter.check(admin_id="operations", identifier="c@example.com", client_ip="1.1.1.1")

    assert len(limiter._attempts) == 2
    # "a" was touched most recently before the eviction, so it survives;
    # its own limit bookkeeping (2 recorded attempts) is still intact.
    remaining_result = limiter.check(
        admin_id="operations", identifier="a@example.com", client_ip="1.1.1.1"
    )
    assert remaining_result is True


def test_concurrent_checks_do_not_lose_or_corrupt_counts() -> None:
    """Hammer the same key from many threads at once -- the limiter must
    neither raise nor silently under-count attempts (which would let more
    requests through than max_attempts allows)."""
    limiter = LoginRateLimiter(max_attempts=1000, window_seconds=60.0)
    results: list[bool] = []
    lock = threading.Lock()

    def _hit() -> None:
        allowed = limiter.check(
            admin_id="operations", identifier="ada@example.com", client_ip="1.1.1.1"
        )
        with lock:
            results.append(allowed)

    threads = [threading.Thread(target=_hit) for _ in range(200)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 200
    assert sum(1 for allowed in results if allowed) == 200


# --- Round 3: shared normalization, bounded memory, real validation -----


class _ManualClock:
    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_identifier_normalization_is_shared_with_the_auth_backend() -> None:
    """The limiter and the backend must agree on what "the same user" is.
    If they normalize differently, `Admin@Example.com ` and
    `admin@example.com` are one account to the backend but distinct keys to
    the limiter -- so an attacker gets N tries per spelling of one email.
    """
    from rakit_auth_sqlalchemy.backend import _normalize_identifier
    from rakit_core.auth import normalize_identifier

    assert _normalize_identifier is normalize_identifier


@pytest.mark.parametrize(
    "spelling",
    ["ADMIN@EXAMPLE.COM", " admin@example.com", "admin@example.com ", "\tAdmin@Example.Com\n"],
)
def test_case_and_whitespace_variants_share_one_limiter_bucket(spelling: str) -> None:
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60.0)
    assert limiter.check(admin_id="a", identifier="admin@example.com", client_ip="1.1.1.1")
    assert limiter.check(admin_id="a", identifier="admin@example.com", client_ip="1.1.1.1")
    assert not limiter.check(admin_id="a", identifier=spelling, client_ip="1.1.1.1")


def test_per_key_storage_is_bounded_under_continuous_denied_attempts() -> None:
    """A denied attempt still counts, so a determined attacker generates an
    unbounded number of timestamps for a single key. Storage must not grow
    with the attack.
    """
    clock = _ManualClock()
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60.0, clock=clock)
    for _ in range(5_000):
        limiter.check(admin_id="a", identifier="victim@example.com", client_ip="1.1.1.1")
        clock.advance(0.01)
    (attempts,) = limiter._attempts.values()
    assert len(attempts) <= 3


def test_continuous_denied_attempts_never_reopen_the_window() -> None:
    """Because every attempt counts, hammering past the window boundary must
    keep the caller locked out rather than letting the bound roll forward.
    """
    clock = _ManualClock()
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60.0, clock=clock)
    for _ in range(3):
        assert limiter.check(admin_id="a", identifier="v@example.com", client_ip="1.1.1.1")
    for _ in range(600):  # ten window-lengths of continuous hammering
        clock.advance(1.0)
        assert not limiter.check(admin_id="a", identifier="v@example.com", client_ip="1.1.1.1")


def test_the_window_reopens_once_attempts_actually_stop() -> None:
    clock = _ManualClock()
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60.0, clock=clock)
    for _ in range(3):
        assert limiter.check(admin_id="a", identifier="v@example.com", client_ip="1.1.1.1")
    assert not limiter.check(admin_id="a", identifier="v@example.com", client_ip="1.1.1.1")
    clock.advance(61.0)
    assert limiter.check(admin_id="a", identifier="v@example.com", client_ip="1.1.1.1")


def test_stale_keys_are_reclaimed_without_waiting_for_the_lru_bound() -> None:
    """A credential-stuffing sweep across many identifiers leaves keys whose
    windows have all lapsed. Those must be reclaimed opportunistically, not
    held until `max_tracked_keys` is reached.
    """
    clock = _ManualClock()
    limiter = LoginRateLimiter(
        max_attempts=3, window_seconds=60.0, clock=clock, max_tracked_keys=10_000
    )
    for index in range(500):
        limiter.check(admin_id="a", identifier=f"user{index}@example.com", client_ip="1.1.1.1")
    assert len(limiter._attempts) == 500
    clock.advance(61.0)
    for _ in range(600):
        limiter.check(admin_id="a", identifier="live@example.com", client_ip="1.1.1.1")
    assert len(limiter._attempts) < 500


def test_total_tracked_keys_stay_bounded() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=600.0, max_tracked_keys=64)
    for index in range(5_000):
        limiter.check(admin_id="a", identifier=f"user{index}@example.com", client_ip="1.1.1.1")
    assert len(limiter._attempts) <= 64


def test_check_is_thread_safe() -> None:
    """Under concurrent callers the limiter must grant exactly `max_attempts`
    -- a lost update would grant more.
    """
    limiter = LoginRateLimiter(max_attempts=50, window_seconds=600.0)
    granted: list[int] = []
    barrier = threading.Barrier(16)

    def worker() -> None:
        barrier.wait()
        for _ in range(25):
            if limiter.check(admin_id="a", identifier="v@example.com", client_ip="1.1.1.1"):
                granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(granted) == 50


def test_login_rate_limiter_satisfies_the_rate_limiter_protocol() -> None:
    assert isinstance(LoginRateLimiter(), RateLimiter)


def test_admin_annotates_the_rate_limiter_as_the_protocol_not_the_concrete_class() -> None:
    """A custom production limiter is the supported path; the public
    signature must not name the development-only implementation.
    """
    import typing

    from rakit_web.admin import Admin

    hints = typing.get_type_hints(Admin.__init__)
    assert RateLimiter in typing.get_args(hints["login_rate_limiter"])


def test_production_validation_rejects_a_limiter_without_a_callable_check() -> None:
    """`production_safe = True` is self-declared. An object that declares it
    but cannot actually be called would blow up at the first login attempt
    -- in production, on the request path. Reject it at construction.
    """

    class Broken:
        production_safe = True
        check = "not callable"

    with pytest.raises(RakitError) as caught:
        validate_rate_limiter_for_production(Broken(), debug=False, auth_enabled=True)
    assert caught.value.details["reason"] == "rate_limiter_not_callable"


def test_production_validation_rejects_a_truthy_but_non_true_production_safe() -> None:
    class Sloppy:
        production_safe = "yes"

        def check(self, *, admin_id: str, identifier: str, client_ip: str) -> bool:
            return True

    with pytest.raises(RakitError) as caught:
        validate_rate_limiter_for_production(Sloppy(), debug=False, auth_enabled=True)
    assert caught.value.details["reason"] == "development_only_rate_limiter"


def test_production_validation_rejects_a_limiter_with_a_wrong_check_signature() -> None:
    class WrongSignature:
        production_safe = True

        def check(self, identifier: str) -> bool:
            return True

    with pytest.raises(RakitError) as caught:
        validate_rate_limiter_for_production(WrongSignature(), debug=False, auth_enabled=True)
    assert caught.value.details["reason"] == "rate_limiter_not_callable"


def test_production_validation_accepts_a_real_production_limiter() -> None:
    class Real:
        production_safe = True

        def check(self, *, admin_id: str, identifier: str, client_ip: str) -> bool:
            return True

    validate_rate_limiter_for_production(Real(), debug=False, auth_enabled=True)
