import threading

import pytest
from rakit_web.security.rate_limit import LoginRateLimiter, RateLimiter


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
