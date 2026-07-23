from datetime import timedelta

import pytest
from rakit_core.config import SecretValue
from rakit_core.crypto import KeyRing, SigningKey, TokenService


def test_new_tokens_use_active_key() -> None:
    service = TokenService(
        KeyRing(
            active=SigningKey("new", SecretValue("n" * 32)),
            previous=(SigningKey("old", SecretValue("o" * 32)),),
        ),
        admin_id="operations",
    )
    token = service.issue_in("confirmation", {"operation_id": "op-1"}, timedelta(minutes=5))
    assert service.peek_header(token)["key_id"] == "new"


def test_token_cannot_cross_purpose() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = service.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))
    with pytest.raises(ValueError, match="purpose"):
        service.verify(token, expected_purpose="confirmation")


def test_round_trip_returns_original_claims() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = service.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))
    assert service.verify(token, expected_purpose="csrf") == {"session_id": "s1"}


def test_previous_key_still_verifies() -> None:
    key_ring = KeyRing(
        active=SigningKey("new", SecretValue("n" * 32)),
        previous=(SigningKey("old", SecretValue("o" * 32)),),
    )
    old_service = TokenService(
        KeyRing(active=SigningKey("old", SecretValue("o" * 32))), admin_id="operations"
    )
    token = old_service.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))

    verifying_service = TokenService(key_ring, admin_id="operations")

    assert verifying_service.verify(token, expected_purpose="csrf") == {"session_id": "s1"}


def test_unknown_key_id_is_rejected() -> None:
    issuing_service = TokenService.single_key(
        key_id="unknown", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = issuing_service.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))
    verifying_service = TokenService.single_key(
        key_id="k1", value=SecretValue("y" * 32), admin_id="operations"
    )

    with pytest.raises(ValueError, match="key"):
        verifying_service.verify(token, expected_purpose="csrf")


def test_expired_token_is_rejected() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = service.issue_in("csrf", {"session_id": "s1"}, timedelta(seconds=-1))

    with pytest.raises(ValueError, match="expired"):
        service.verify(token, expected_purpose="csrf")


def test_tampered_signature_is_rejected() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = service.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))
    header, payload, signature = token.split(".")
    middle = len(signature) // 2
    flipped_char = "A" if signature[middle] != "A" else "B"
    tampered_signature = signature[:middle] + flipped_char + signature[middle + 1 :]
    tampered = f"{header}.{payload}.{tampered_signature}"

    with pytest.raises(ValueError, match="signature"):
        service.verify(tampered, expected_purpose="csrf")


def test_tampered_payload_is_rejected() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = service.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))
    other_token = service.issue_in("csrf", {"session_id": "s2"}, timedelta(minutes=5))
    header, _, signature = token.split(".")
    _, other_payload, _ = other_token.split(".")
    tampered = f"{header}.{other_payload}.{signature}"

    with pytest.raises(ValueError, match="signature"):
        service.verify(tampered, expected_purpose="csrf")


def test_different_admin_id_cannot_verify_another_admins_token() -> None:
    issuer = TokenService.single_key(key_id="k1", value=SecretValue("x" * 32), admin_id="admin-a")
    token = issuer.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))
    other_admin_verifier = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="admin-b"
    )

    with pytest.raises(ValueError, match="signature"):
        other_admin_verifier.verify(token, expected_purpose="csrf")


def test_signing_key_repr_does_not_leak_secret() -> None:
    key = SigningKey("k1", SecretValue("super-secret-material"))

    assert "super-secret-material" not in repr(key)
