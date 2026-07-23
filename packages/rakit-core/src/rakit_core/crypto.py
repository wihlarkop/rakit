import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import timedelta
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import SecretValue

TOKEN_VERSION = 1


class SigningKey:
    """A single purpose-agnostic key material entry in a `KeyRing`.

    Holds only a stable `key_id` and a redacting `SecretValue` -- the raw
    secret is never exposed through `repr()`/`str()`, only through the
    explicit `_raw_secret()` accessor used internally for key derivation.
    """

    def __init__(self, key_id: str, secret: SecretValue) -> None:
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
    padding = "=" * (-len(data) % 4)
    return urlsafe_b64decode(data + padding)


def _split(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    return parts[0], parts[1], parts[2]


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
        now = time.time()
        header = {
            "purpose": purpose,
            "version": TOKEN_VERSION,
            "key_id": self._key_ring.active.key_id,
            "issued_at": now,
            "expires_at": now + ttl.total_seconds(),
        }
        header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = _b64encode(json.dumps(claims, separators=(",", ":")).encode())
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
        authenticated claim. `verify()` is the only trust boundary.
        """
        header_b64, _, _ = _split(token)
        try:
            return json.loads(_b64decode(header_b64))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("malformed token") from exc

    def verify(self, token: str, *, expected_purpose: str) -> dict[str, Any]:
        header_b64, payload_b64, signature_b64 = _split(token)
        try:
            header = json.loads(_b64decode(header_b64))
            claims = json.loads(_b64decode(payload_b64))
            signature = _b64decode(signature_b64)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("malformed token") from exc

        purpose = header.get("purpose")
        version = header.get("version")
        key_id = header.get("key_id")
        expires_at = header.get("expires_at")

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

        if not isinstance(expires_at, int | float) or time.time() > expires_at:
            raise ValueError("token expired")

        return claims
