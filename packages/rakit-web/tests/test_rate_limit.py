from rakit_web.security.rate_limit import LoginRateLimiter


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
