import hashlib
import hmac
import json
from base64 import urlsafe_b64encode
from datetime import timedelta
from typing import cast

import pytest
import rakit_core.crypto as crypto
from rakit_core.config import SecretValue
from rakit_core.crypto import TOKEN_VERSION, KeyRing, SigningKey, TokenService, _derive_key


def _b64(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _signed_token(
    *,
    key_id: str,
    secret: SecretValue,
    admin_id: str,
    purpose: str,
    claims: dict[str, object],
    issued_at: float,
    expires_at: float,
) -> str:
    """Build a genuinely, validly signed token with caller-controlled
    issued_at/expires_at -- for testing behavior (like expiry) that the
    public `issue_in()` API no longer allows constructing directly, now
    that it validates its own ttl argument."""
    signing_key = SigningKey(key_id, secret)
    header = {
        "purpose": purpose,
        "version": TOKEN_VERSION,
        "key_id": key_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    header_b64 = _b64(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64(json.dumps(claims, separators=(",", ":")).encode())
    mac_key = _derive_key(signing_key, admin_id=admin_id, purpose=purpose, version=TOKEN_VERSION)
    signature = hmac.new(mac_key, f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64(signature)}"


_NO_PAYLOAD = object()


def _raw_token(header: object, payload: object = _NO_PAYLOAD, signature_b64: str = "AAAA") -> str:
    """Build a syntactically-shaped `header.payload.signature` token with an
    arbitrary (possibly malformed) header/payload JSON root, without going
    through `issue_in()` -- used to prove shape validation runs (and rejects
    with a stable ValueError) *before* signature verification, for JSON
    roots that would never come from a legitimate issuer.

    `payload` defaults to a sentinel (not `None`) so passing `None` as an
    explicit malformed-payload test case is distinguishable from "the
    caller didn't pass one at all."
    """
    header_b64 = _b64(json.dumps(header).encode())
    payload_b64 = _b64(json.dumps({} if payload is _NO_PAYLOAD else payload).encode())
    return f"{header_b64}.{payload_b64}.{signature_b64}"


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
    # `issue_in()` itself now rejects a non-positive ttl (see
    # test_issue_in_rejects_non_positive_ttl), so an already-expired token
    # can no longer be produced through the public API -- build one
    # directly with a valid signature but issued_at/expires_at both in the
    # past (still satisfying issued_at <= expires_at).
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = _signed_token(
        key_id="k1",
        secret=SecretValue("x" * 32),
        admin_id="operations",
        purpose="csrf",
        claims={"session_id": "s1"},
        issued_at=0.0,
        expires_at=1.0,
    )

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


# --- Adversarial: malformed JSON roots for header/payload ---------------


@pytest.mark.parametrize(
    "malformed_header",
    [
        [],
        [1, 2, 3],
        None,
        "just-a-string",
        12345,
        3.14,
        True,
    ],
)
def test_non_dict_header_json_root_is_rejected(malformed_header: object) -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = _raw_token(malformed_header, {"a": 1})

    with pytest.raises(ValueError, match="malformed"):
        service.verify(token, expected_purpose="csrf")

    with pytest.raises(ValueError, match="malformed"):
        service.peek_header(token)


@pytest.mark.parametrize(
    "malformed_payload",
    [[], [1, 2, 3], None, "just-a-string", 12345, 3.14, True],
)
def test_non_dict_payload_json_root_is_rejected(malformed_payload: object) -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    valid_header = {
        "purpose": "csrf",
        "version": 1,
        "key_id": "k1",
        "issued_at": 0.0,
        "expires_at": 9999999999.0,
    }
    token = _raw_token(valid_header, malformed_payload)

    with pytest.raises(ValueError, match="malformed"):
        service.verify(token, expected_purpose="csrf")


# --- Adversarial: wrong field types within an otherwise-shaped header ---


def _header(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "purpose": "csrf",
        "version": 1,
        "key_id": "k1",
        "issued_at": 0.0,
        "expires_at": 9999999999.0,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "bad_header",
    [
        _header(purpose=""),
        _header(purpose=None),
        _header(purpose=123),
        _header(key_id=""),
        _header(key_id=None),
        _header(key_id=123),
        _header(version="1"),
        _header(version=1.0),
        _header(version=True),
        _header(issued_at="0"),
        _header(issued_at=None),
        _header(issued_at=float("nan")),
        _header(issued_at=float("inf")),
        _header(issued_at=True),
        _header(expires_at="9999999999"),
        _header(expires_at=None),
        _header(expires_at=float("nan")),
        _header(expires_at=float("inf")),
        _header(issued_at=100.0, expires_at=1.0),
        {k: v for k, v in _header().items() if k != "purpose"},
        {k: v for k, v in _header().items() if k != "key_id"},
        {k: v for k, v in _header().items() if k != "version"},
        {k: v for k, v in _header().items() if k != "issued_at"},
        {k: v for k, v in _header().items() if k != "expires_at"},
    ],
)
def test_malformed_header_field_types_are_rejected(bad_header: dict[str, object]) -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = _raw_token(bad_header, {"a": 1})

    with pytest.raises(ValueError, match="malformed"):
        service.verify(token, expected_purpose="csrf")


# --- Adversarial: malformed base64 / UTF-8 / JSON text -------------------


def test_malformed_base64_header_is_rejected() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = "not-valid-base64!!!." + _b64(b"{}") + ".AAAA"

    with pytest.raises(ValueError, match="malformed"):
        service.verify(token, expected_purpose="csrf")


def test_invalid_utf8_header_is_rejected() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    header_b64 = _b64(b"\xff\xfe\x00\x01")
    token = f"{header_b64}.{_b64(b'{}')}.AAAA"

    with pytest.raises(ValueError, match="malformed"):
        service.verify(token, expected_purpose="csrf")


def test_invalid_json_header_is_rejected() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    header_b64 = _b64(b"not-json{")
    token = f"{header_b64}.{_b64(b'{}')}.AAAA"

    with pytest.raises(ValueError, match="malformed"):
        service.verify(token, expected_purpose="csrf")


def test_malformed_signature_base64_is_rejected() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = _raw_token(_header(), {"a": 1}, signature_b64="not-valid-base64!!!")

    with pytest.raises(ValueError, match="malformed"):
        service.verify(token, expected_purpose="csrf")


# --- Adversarial: KeyRing/issue_in input validation ----------------------


def test_duplicate_key_ids_between_active_and_previous_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        KeyRing(
            active=SigningKey("k1", SecretValue("x" * 32)),
            previous=(SigningKey("k1", SecretValue("y" * 32)),),
        )


def test_duplicate_key_ids_within_previous_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        KeyRing(
            active=SigningKey("active", SecretValue("x" * 32)),
            previous=(
                SigningKey("dup", SecretValue("y" * 32)),
                SigningKey("dup", SecretValue("z" * 32)),
            ),
        )


def test_empty_key_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SigningKey("", SecretValue("x" * 32))


def test_issue_in_rejects_empty_purpose() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    with pytest.raises(ValueError, match="purpose"):
        service.issue_in("", {"a": 1}, timedelta(minutes=5))


def test_issue_in_rejects_non_positive_ttl() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    with pytest.raises(ValueError, match="ttl"):
        service.issue_in("csrf", {"a": 1}, timedelta(0))


def test_issue_in_rejects_unbounded_ttl() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    with pytest.raises(ValueError, match="ttl"):
        service.issue_in("csrf", {"a": 1}, timedelta(days=10_000))


def test_issue_in_rejects_non_serializable_claims() -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    with pytest.raises(ValueError, match="claims"):
        service.issue_in("csrf", {"a": object()}, timedelta(minutes=5))


# --- Round 3: strict identifier validation ------------------------------

# `key_id`, `admin_id`, and `purpose` are not free-form labels: `admin_id`
# and `purpose` are interpolated into the HKDF info string
# `rakit:{admin_id}:{purpose}:v{version}`, and `key_id` is written into the
# token header and compared on the way back in. Anything that is not a
# clean, colon-free ASCII identifier is rejected at construction rather
# than producing a key or a token that misbehaves later.
INVALID_IDENTIFIERS = [
    pytest.param("", id="empty"),
    pytest.param("   ", id="whitespace-only"),
    pytest.param("\t", id="tab-only"),
    pytest.param("\n", id="newline-only"),
    pytest.param(" k1", id="leading-space"),
    pytest.param("k1 ", id="trailing-space"),
    pytest.param("k 1", id="inner-space"),
    pytest.param("k\t1", id="inner-tab"),
    pytest.param("k\n1", id="inner-newline"),
    pytest.param("k1\x00", id="null-byte"),
    pytest.param("k:1", id="colon"),
    pytest.param("k/1", id="slash"),
    pytest.param("k1é", id="non-ascii"),
    pytest.param("k1​", id="zero-width-space"),
    pytest.param("k" * 200, id="over-length"),
]

NON_STRING_IDENTIFIERS = [
    pytest.param(1, id="int"),
    pytest.param(True, id="bool"),
    pytest.param(None, id="none"),
    pytest.param(b"k1", id="bytes"),
    pytest.param(["k1"], id="list"),
]


@pytest.mark.parametrize("key_id", INVALID_IDENTIFIERS)
def test_signing_key_rejects_an_invalid_key_id(key_id: str) -> None:
    with pytest.raises(ValueError):
        SigningKey(key_id, SecretValue("x" * 32))


@pytest.mark.parametrize("key_id", NON_STRING_IDENTIFIERS)
def test_signing_key_rejects_a_non_string_key_id(key_id: object) -> None:
    """A non-string key_id used to be accepted, then written into the token
    header as a non-string and rejected by header validation on the way back
    in -- so every token the key ever signed was unverifiable, discovered at
    verification time rather than at construction.
    """
    with pytest.raises(ValueError):
        SigningKey(cast(str, key_id), SecretValue("x" * 32))


@pytest.mark.parametrize("admin_id", INVALID_IDENTIFIERS)
def test_token_service_rejects_an_invalid_admin_id(admin_id: str) -> None:
    with pytest.raises(ValueError):
        TokenService.single_key(key_id="k1", value=SecretValue("x" * 32), admin_id=admin_id)


@pytest.mark.parametrize("admin_id", NON_STRING_IDENTIFIERS)
def test_token_service_rejects_a_non_string_admin_id(admin_id: object) -> None:
    with pytest.raises(ValueError):
        TokenService.single_key(
            key_id="k1", value=SecretValue("x" * 32), admin_id=cast(str, admin_id)
        )


@pytest.mark.parametrize("purpose", INVALID_IDENTIFIERS)
def test_issue_rejects_an_invalid_purpose(purpose: str) -> None:
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    with pytest.raises(ValueError):
        service.issue_in(purpose, {}, timedelta(minutes=5))


@pytest.mark.parametrize("purpose", INVALID_IDENTIFIERS)
def test_verify_rejects_an_invalid_expected_purpose(purpose: str) -> None:
    """An invalid `expected_purpose` must fail closed rather than deriving
    some other key and silently comparing against the wrong one.
    """
    service = TokenService.single_key(
        key_id="k1", value=SecretValue("x" * 32), admin_id="operations"
    )
    token = service.issue_in("csrf", {}, timedelta(minutes=5))
    with pytest.raises(ValueError):
        service.verify(token, expected_purpose=purpose)


def test_colon_in_an_identifier_would_collide_purpose_separation() -> None:
    """The concrete reason colons are banned. The HKDF info string is
    `rakit:{admin_id}:{purpose}:v{version}`, so admin_id="a"/purpose="b:c"
    and admin_id="a:b"/purpose="c" would derive the *same* key -- one
    admin's session token would verify as another's. Rejecting the colon
    keeps the separator unambiguous.
    """
    with pytest.raises(ValueError):
        TokenService.single_key(key_id="k1", value=SecretValue("x" * 32), admin_id="a:b")
    service = TokenService.single_key(key_id="k1", value=SecretValue("x" * 32), admin_id="a")
    with pytest.raises(ValueError):
        service.issue_in("b:c", {}, timedelta(minutes=5))


def test_key_ring_rejects_duplicate_key_ids_including_the_active_key() -> None:
    secret = SecretValue("x" * 32)
    with pytest.raises(ValueError):
        KeyRing(active=SigningKey("k1", secret), previous=(SigningKey("k1", secret),))
    with pytest.raises(ValueError):
        KeyRing(
            active=SigningKey("k1", secret),
            previous=(SigningKey("k2", secret), SigningKey("k2", secret)),
        )


VALID_IDENTIFIERS = ["k1", "K1", "key-1", "key_1", "key.1", "a", "0", "k" * 128]


@pytest.mark.parametrize("identifier", VALID_IDENTIFIERS)
def test_valid_identifiers_round_trip_issue_and_verify(identifier: str) -> None:
    """Validation must not have narrowed the set of identifiers that
    genuinely work -- each of these still issues and verifies end to end.
    """
    service = TokenService.single_key(
        key_id=identifier, value=SecretValue("x" * 32), admin_id=identifier.lower()
    )
    token = service.issue_in(identifier, {"session_id": "s1"}, timedelta(minutes=5))
    assert service.verify(token, expected_purpose=identifier)["session_id"] == "s1"


def test_rotation_round_trips_across_a_previous_key() -> None:
    secret_a = SecretValue("a" * 32)
    secret_b = SecretValue("b" * 32)
    old = TokenService(KeyRing(active=SigningKey("k1", secret_a)), admin_id="operations")
    token = old.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))

    rotated = TokenService(
        KeyRing(active=SigningKey("k2", secret_b), previous=(SigningKey("k1", secret_a),)),
        admin_id="operations",
    )
    assert rotated.verify(token, expected_purpose="csrf")["session_id"] == "s1"


def test_a_token_from_a_different_admin_id_never_verifies() -> None:
    secret = SecretValue("x" * 32)
    one = TokenService.single_key(key_id="k1", value=secret, admin_id="operations")
    other = TokenService.single_key(key_id="k1", value=secret, admin_id="billing")
    token = one.issue_in("csrf", {"session_id": "s1"}, timedelta(minutes=5))
    with pytest.raises(ValueError):
        other.verify(token, expected_purpose="csrf")


def test_maximum_token_ttl_is_exposed_for_integrations() -> None:
    assert timedelta(days=365) == crypto.MAX_TOKEN_TTL
