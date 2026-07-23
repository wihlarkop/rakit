import hashlib
import hmac
import json
import math
import time
from base64 import b64decode, urlsafe_b64encode
from datetime import timedelta
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import SecretValue

TOKEN_VERSION = 1
_MAX_TTL = timedelta(days=365)


class SigningKey:
    """A single purpose-agnostic key material entry in a `KeyRing`.

    Holds only a stable `key_id` and a redacting `SecretValue` -- the raw
    secret is never exposed through `repr()`/`str()`, only through the
    explicit `_raw_secret()` accessor used internally for key derivation.
    """

    def __init__(self, key_id: str, secret: SecretValue) -> None:
        if not key_id:
            raise ValueError("SigningKey.key_id must be a non-empty string")
        self.key_id = key_id
        self._secret = secret

    def __repr__(self) -> str:
        return f"SigningKey(key_id={self.key_id!r})"

    def _raw_secret(self) -> bytes:
        return self._secret.get_secret_value().encode("utf-8")


class KeyRing:
    """One active signing key plus zero or more previous verification-only
    keys, supporting rotation without invalidating tokens issued under a
    still-trusted previous key."""

    def __init__(self, *, active: SigningKey, previous: tuple[SigningKey, ...] = ()) -> None:
        all_ids = [active.key_id, *(key.key_id for key in previous)]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("KeyRing key IDs must be unique across active and previous")
        self.active = active
        self.previous = previous

    def resolve(self, key_id: object) -> SigningKey | None:
        if self.active.key_id == key_id:
            return self.active
        for key in self.previous:
            if key.key_id == key_id:
                return key
        return None


def _derive_key(signing_key: SigningKey, *, admin_id: str, purpose: str, version: int) -> bytes:
    """HKDF-SHA256, purpose-separated by `rakit:{admin_id}:{purpose}:v{version}`.

    Binding `admin_id` and `purpose` into the derivation info -- not just
    checking them after the fact -- means a token signed for one admin or
    purpose cannot be verified against a different admin's or purpose's
    derived key at all, not merely rejected by a claims comparison.
    """
    info = f"rakit:{admin_id}:{purpose}:v{version}".encode()
    kdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
    return kdf.derive(signing_key._raw_secret())


def _b64encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    # `base64.urlsafe_b64decode` delegates to `b64decode` with
    # `validate=False`, which silently discards non-alphabet characters
    # instead of rejecting them -- e.g. "not-valid-base64!!!" would decode
    # to *something* rather than raising. `validate=True` makes an
    # out-of-alphabet character raise `binascii.Error` (a `ValueError`
    # subclass), matching the fail-closed contract every caller expects.
    padding = "=" * (-len(data) % 4)
    translated = (data + padding).translate({ord("-"): "+", ord("_"): "/"})
    return b64decode(translated, validate=True)


def _split(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    return parts[0], parts[1], parts[2]


def _decode_json_object(data: str) -> dict[str, Any]:
    """Decode one base64url segment as a JSON *object* (never any other
    JSON root type) -- `urlsafe_b64decode` raises `binascii.Error`, a
    `ValueError` subclass, so malformed base64 is already covered by the
    `ValueError` catch below without a separate import.
    """
    try:
        raw_bytes = _b64decode(data)
    except ValueError as exc:
        raise ValueError("malformed token") from exc
    try:
        decoded_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("malformed token") from exc
    try:
        value = json.loads(decoded_text)
    except ValueError as exc:
        raise ValueError("malformed token") from exc
    if not isinstance(value, dict):
        raise ValueError("malformed token")
    return value


def _as_finite_number(value: object) -> float:
    # `bool` is an `int` subclass -- exclude it explicitly so `True`/`False`
    # never pass as a timestamp.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("malformed token")
    if not math.isfinite(value):
        raise ValueError("malformed token")
    return float(value)


def _validate_header(header: dict[str, Any]) -> tuple[str, int, str, float, float]:
    """Validate decoded header shape and return its fields, or raise a
    stable `ValueError("malformed token")`. Runs before any signature
    verification, so a malformed shape never reaches HMAC comparison."""
    purpose = header.get("purpose")
    version = header.get("version")
    key_id = header.get("key_id")

    if not isinstance(purpose, str) or not purpose:
        raise ValueError("malformed token")
    if not isinstance(key_id, str) or not key_id:
        raise ValueError("malformed token")
    # Exact `int` type, excluding `bool` (an `int` subclass) and `float`.
    if type(version) is not int:
        raise ValueError("malformed token")

    issued_at = _as_finite_number(header.get("issued_at"))
    expires_at = _as_finite_number(header.get("expires_at"))
    if issued_at > expires_at:
        raise ValueError("malformed token")

    return purpose, version, key_id, issued_at, expires_at


class TokenService:
    """Issues and verifies compact, purpose-separated, expiring HMAC tokens.

    Not a general-purpose JWT implementation: the header/payload/signature
    shape is Rakit-internal and only ever produced/consumed by this class.
    """

    def __init__(self, key_ring: KeyRing, *, admin_id: str) -> None:
        self._key_ring = key_ring
        self._admin_id = admin_id

    @classmethod
    def single_key(cls, *, key_id: str, value: SecretValue, admin_id: str) -> "TokenService":
        return cls(KeyRing(active=SigningKey(key_id, value)), admin_id=admin_id)

    def issue_in(self, purpose: str, claims: dict[str, Any], ttl: timedelta) -> str:
        if not isinstance(purpose, str) or not purpose:
            raise ValueError("purpose must be a non-empty string")
        if not isinstance(claims, dict):
            raise ValueError("claims must be a dict")
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        if ttl > _MAX_TTL:
            raise ValueError("ttl exceeds the maximum allowed duration")
        try:
            payload_json = json.dumps(claims, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("claims must be JSON-serializable") from exc

        now = time.time()
        header = {
            "purpose": purpose,
            "version": TOKEN_VERSION,
            "key_id": self._key_ring.active.key_id,
            "issued_at": now,
            "expires_at": now + ttl.total_seconds(),
        }
        header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = _b64encode(payload_json.encode())
        mac_key = _derive_key(
            self._key_ring.active,
            admin_id=self._admin_id,
            purpose=purpose,
            version=TOKEN_VERSION,
        )
        signature = hmac.new(mac_key, f"{header_b64}.{payload_b64}".encode(), hashlib.sha256)
        return f"{header_b64}.{payload_b64}.{_b64encode(signature.digest())}"

    def peek_header(self, token: str) -> dict[str, Any]:
        """Read the header without verifying the signature.

        For introspection/logging of untrusted tokens only (e.g. picking a
        `key_id` to report) -- never trust anything read this way as an
        authenticated claim. `verify()` is the only trust boundary. Still
        shape-validates (see `_validate_header`), so a caller never receives
        a non-dict or a header with missing/mistyped fields.
        """
        header_b64, _, _ = _split(token)
        header = _decode_json_object(header_b64)
        _validate_header(header)
        return header

    def verify(self, token: str, *, expected_purpose: str) -> dict[str, Any]:
        header_b64, payload_b64, signature_b64 = _split(token)
        header = _decode_json_object(header_b64)
        claims = _decode_json_object(payload_b64)
        try:
            signature = _b64decode(signature_b64)
        except ValueError as exc:
            raise ValueError("malformed token") from exc

        purpose, version, key_id, _issued_at, expires_at = _validate_header(header)

        if purpose != expected_purpose:
            raise ValueError("token purpose mismatch")
        if version != TOKEN_VERSION:
            raise ValueError("token version mismatch")

        signing_key = self._key_ring.resolve(key_id)
        if signing_key is None:
            raise ValueError("unknown token key id")

        mac_key = _derive_key(
            signing_key, admin_id=self._admin_id, purpose=purpose, version=version
        )
        expected_signature = hmac.new(
            mac_key, f"{header_b64}.{payload_b64}".encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected_signature, signature):
            raise ValueError("token signature invalid")

        if time.time() > expires_at:
            raise ValueError("token expired")

        return claims
