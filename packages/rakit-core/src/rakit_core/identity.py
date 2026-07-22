import base64
import json

from pydantic import BaseModel, ConfigDict, field_validator


class RecordIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    values: dict[str, int | str]

    @field_validator("values")
    @classmethod
    def validate_values(cls, value):
        if not value:
            raise ValueError("RecordIdentity requires at least one field")
        return dict(sorted(value.items()))


class IdentityCodec:
    def encode(self, identity: RecordIdentity) -> str:
        raw = json.dumps(identity.values, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def decode(self, encoded: str) -> RecordIdentity:
        padding = "=" * (-len(encoded) % 4)
        values = json.loads(base64.urlsafe_b64decode(encoded + padding))
        if not isinstance(values, dict):
            raise ValueError("Identity payload must be an object")
        return RecordIdentity(values=values)
