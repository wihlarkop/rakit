import base64
import binascii
import json
from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ._immutability import freeze_mapping


def canonical_identity_payload(identity: "RecordIdentity") -> dict[str, dict[str, int | str]]:
    """Return the one type-stable JSON-safe representation of an identity."""

    payload: dict[str, dict[str, int | str]] = {}
    for field, value in identity.values.items():
        if isinstance(value, UUID):
            payload[field] = {"type": "uuid", "value": str(value)}
        elif isinstance(value, int) and not isinstance(value, bool):
            payload[field] = {"type": "int", "value": value}
        else:
            payload[field] = {"type": "str", "value": value}
    return payload


def identity_from_canonical_payload(payload: Mapping[str, object]) -> "RecordIdentity":
    values: dict[str, int | str | UUID] = {}
    for field, encoded in payload.items():
        if not isinstance(field, str) or not isinstance(encoded, Mapping):
            raise ValueError("Invalid canonical identity")
        kind, value = encoded.get("type"), encoded.get("value")
        if (kind == "int" and isinstance(value, int) and not isinstance(value, bool)) or (
            kind == "str" and isinstance(value, str)
        ):
            values[field] = value
        elif kind == "uuid" and isinstance(value, str):
            values[field] = UUID(value)
        else:
            raise ValueError("Invalid canonical identity")
    return RecordIdentity(values=values)


class RecordIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    values: Mapping[str, int | str | UUID]

    @field_validator("values", mode="before")
    @classmethod
    def normalize_values(cls, value: object) -> object:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("RecordIdentity requires at least one field")
        normalized: dict[str, int | str | UUID] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("RecordIdentity field names must be strings")
            if isinstance(item, UUID):
                normalized[key] = item
            elif isinstance(item, bool) or not isinstance(item, int | str):
                raise ValueError("RecordIdentity values must be integers, strings, or UUIDs")
            else:
                normalized[key] = item
        return dict(sorted(normalized.items()))

    @field_validator("values")
    @classmethod
    def freeze_values(cls, value: dict[str, int | str | UUID]) -> Mapping[str, int | str | UUID]:
        return freeze_mapping(value)


class IdentityCodec:
    def encode(self, identity: RecordIdentity) -> str:
        raw = json.dumps(
            canonical_identity_payload(identity), separators=(",", ":"), sort_keys=True
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def decode(self, encoded: str) -> RecordIdentity:
        try:
            padding = "=" * (-len(encoded) % 4)
            decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
            values = json.loads(decoded)
            if not isinstance(values, dict):
                raise ValueError
            if values and all(
                isinstance(value, Mapping) and "type" in value for value in values.values()
            ):
                return identity_from_canonical_payload(values)
            return RecordIdentity(values=values)
        except (
            binascii.Error,
            json.JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
            UnicodeEncodeError,
            ValidationError,
            ValueError,
        ) as exc:
            raise ValueError("Invalid identity token") from exc
