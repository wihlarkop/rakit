import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from rakit_core.auth import SessionRecord
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


def _record(*, session_id: str = "session-1", absolute_lifetime: timedelta) -> SessionRecord:
    now = datetime.now(UTC)
    return SessionRecord(
        session_id=session_id,
        subject_id="1",
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + absolute_lifetime,
    )


def test_issued_token_verifies_for_the_same_session() -> None:
    service = _service()
    token = service.issue(_record(absolute_lifetime=timedelta(days=14)))
    assert service.verify(token, session_id="session-1")


def test_token_does_not_verify_for_a_different_session() -> None:
    service = _service()
    token = service.issue(_record(absolute_lifetime=timedelta(days=14)))
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


def test_expired_csrf_token_does_not_verify() -> None:
    """The token still genuinely expires -- a longer default lifetime must
    not mean tokens never expire at all."""
    import time

    token_service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    service = CsrfService(token_service)
    token = service.issue(_record(absolute_lifetime=timedelta(seconds=1)))
    assert service.verify(token, session_id="session-1")
    time.sleep(1.1)
    assert not service.verify(token, session_id="session-1")


# --- Round 3: CSRF expiry is derived from the actual session ------------


def _token_expiry(token: str) -> float:
    header_b64 = token.split(".")[0]
    padded = header_b64 + "=" * (-len(header_b64) % 4)
    return json.loads(urlsafe_b64decode(padded))["expires_at"]


@pytest.mark.parametrize("days", [1, 14, 30, 90])
def test_csrf_expiry_tracks_the_session_absolute_expiry(days: int) -> None:
    """The old 14-day constant was hard-coded to `SQLAlchemySessionStore`'s
    default. Any deployment configuring a different absolute session
    lifetime got a CSRF token that either lapsed mid-session (making logout
    permanently 403) or outlived the session it was bound to.
    """
    service = _service()
    record = _record(absolute_lifetime=timedelta(days=days))
    token = service.issue(record)
    expected = record.absolute_expires_at.timestamp()
    assert abs(_token_expiry(token) - expected) < 5.0


def test_csrf_token_never_lapses_before_its_session_does() -> None:
    service = _service()
    for days in (1, 7, 14, 30, 60):
        record = _record(absolute_lifetime=timedelta(days=days))
        token = service.issue(record)
        assert _token_expiry(token) >= record.absolute_expires_at.timestamp() - 5.0


def test_csrf_service_has_no_hard_coded_session_lifetime_default() -> None:
    """A default TTL constant is exactly the coupling that broke: it silently
    encodes one storage adapter's configuration into a different package.
    """
    import inspect

    import rakit_web.security.csrf as csrf_module

    assert not hasattr(csrf_module, "DEFAULT_CSRF_TTL")
    assert "ttl" not in inspect.signature(CsrfService.__init__).parameters


def test_issue_requires_a_session_record_not_a_bare_id() -> None:
    """Passing a bare `session_id` is what made deriving the expiry
    impossible; the record carries the deadline.
    """
    service = _service()
    not_a_record = cast(SessionRecord, "session-1")
    with pytest.raises((TypeError, AttributeError, ValueError)):
        service.issue(not_a_record)


def test_an_already_expired_session_yields_no_usable_token() -> None:
    service = _service()
    expired = _record(absolute_lifetime=timedelta(seconds=-1))
    with pytest.raises(ValueError):
        service.issue(expired)


def test_explicit_expires_at_overrides_the_session_deadline() -> None:
    """A deployment that wants a shorter CSRF window than the session's own
    absolute deadline can ask for one explicitly -- what it cannot do is
    silently inherit some other package's default.
    """
    service = _service()
    record = _record(absolute_lifetime=timedelta(days=30))
    deadline = datetime.now(UTC) + timedelta(days=2)
    token = service.issue(record, expires_at=deadline)
    assert abs(_token_expiry(token) - deadline.timestamp()) < 5.0
    assert service.verify(token, session_id=record.session_id)


def test_rotation_invalidates_the_previous_token() -> None:
    """`SessionStore.rotate()` issues a new session_id, and CSRF tokens are
    bound to that id -- so a token minted before rotation must stop
    verifying afterwards.
    """
    service = _service()
    before = service.issue(_record(session_id="session-1", absolute_lifetime=timedelta(days=14)))
    after = service.issue(_record(session_id="session-2", absolute_lifetime=timedelta(days=14)))
    assert service.verify(before, session_id="session-1")
    assert not service.verify(before, session_id="session-2")
    assert service.verify(after, session_id="session-2")
