import json
from base64 import urlsafe_b64encode
from datetime import timedelta

import pytest
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_web.security.csrf import CsrfService


def _b64(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _service() -> CsrfService:
    token_service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    return CsrfService(token_service)


def test_issued_token_verifies_for_the_same_session() -> None:
    service = _service()
    token = service.issue("session-1")
    assert service.verify(token, session_id="session-1")


def test_token_does_not_verify_for_a_different_session() -> None:
    service = _service()
    token = service.issue("session-1")
    assert not service.verify(token, session_id="session-2")


def test_malformed_token_does_not_verify() -> None:
    service = _service()
    assert not service.verify("not-a-real-token", session_id="session-1")


def test_token_from_a_different_purpose_does_not_verify_as_csrf() -> None:
    token_service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    service = CsrfService(token_service)
    other_purpose_token = token_service.issue_in(
        "confirmation", {"session_id": "session-1"}, timedelta(hours=1)
    )
    assert not service.verify(other_purpose_token, session_id="session-1")


@pytest.mark.parametrize(
    "malformed_header",
    [[], [1, 2, 3], None, "just-a-string", 12345, True],
)
def test_non_dict_header_shape_returns_false_not_a_raw_exception(malformed_header: object) -> None:
    """Before crypto.py's shape hardening, a non-dict decoded header (e.g.
    `[]`) made `TokenService.verify()` raise `AttributeError` (`.get()` on a
    list), which `CsrfService.verify()`'s `except ValueError` did not catch
    -- an attacker-controlled malformed token could crash the request
    instead of being rejected. This proves it now returns `False` cleanly
    for every such shape, never propagating a raw exception."""
    service = _service()
    header_b64 = _b64(json.dumps(malformed_header).encode())
    payload_b64 = _b64(json.dumps({"session_id": "session-1"}).encode())
    token = f"{header_b64}.{payload_b64}.AAAA"

    assert service.verify(token, session_id="session-1") is False


def test_empty_string_token_returns_false() -> None:
    assert _service().verify("", session_id="session-1") is False


def test_token_with_wrong_number_of_segments_returns_false() -> None:
    assert _service().verify("only.two", session_id="session-1") is False


# --- Token lifetime must not fall short of the session it protects ------


def test_default_csrf_lifetime_covers_a_long_lived_session() -> None:
    """A CSRF token shorter-lived than the session it protects makes logout
    permanently impossible once it lapses: the cookie is stale, no code path
    re-issues it, and every subsequent logout POST is rejected 403 forever.
    The default must therefore cover the default session absolute lifetime
    (14 days), not expire after 4 hours of continuous use."""
    from rakit_web.security.csrf import DEFAULT_CSRF_TTL

    assert timedelta(days=14) <= DEFAULT_CSRF_TTL


def test_csrf_lifetime_is_configurable() -> None:
    token_service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    service = CsrfService(token_service, ttl=timedelta(minutes=30))
    token = service.issue("session-1")
    assert service.verify(token, session_id="session-1")


def test_expired_csrf_token_does_not_verify() -> None:
    """The token still genuinely expires -- a longer default lifetime must
    not mean tokens never expire at all."""
    import time

    token_service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    service = CsrfService(token_service, ttl=timedelta(seconds=1))
    token = service.issue("session-1")
    assert service.verify(token, session_id="session-1")
    time.sleep(1.1)
    assert not service.verify(token, session_id="session-1")
