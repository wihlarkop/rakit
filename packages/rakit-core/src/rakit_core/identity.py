import base64
import binascii
import json
from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ._immutability import freeze_mapping


class RecordIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    values: Mapping[str, int | str | UUID]

    @field_validator("values", mode="before")
    @classmethod
    def normalize_values(cls, value: object) -> object:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("RecordIdentity requires at least one field")
        normalized: dict[str, int | str] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("RecordIdentity field names must be strings")
            if isinstance(item, UUID):
                normalized[key] = str(item)
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
        raw = json.dumps(dict(identity.values), separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def decode(self, encoded: str) -> RecordIdentity:
        try:
            padding = "=" * (-len(encoded) % 4)
            decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
            values = json.loads(decoded)
            if not isinstance(values, dict):
                raise ValueError
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
