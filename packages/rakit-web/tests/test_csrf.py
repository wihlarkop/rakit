from datetime import timedelta

from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_web.security.csrf import CsrfService


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
