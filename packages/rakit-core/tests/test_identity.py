from typing import Any, cast
from uuid import UUID

import pytest
from rakit_core.identity import IdentityCodec, RecordIdentity, canonical_identity_payload


def test_identity_round_trip_is_deterministic() -> None:
    identity = RecordIdentity(values={"id": "user/42"})
    codec = IdentityCodec()
    encoded = codec.encode(identity)
    assert "/" not in encoded
    assert codec.decode(encoded) == identity


def test_identity_requires_at_least_one_field() -> None:
    with pytest.raises(ValueError):
        RecordIdentity(values={})


def test_uuid_identity_uses_canonical_text_and_round_trips() -> None:
    value = UUID("A0EBC21A-7334-4AB2-8F01-01E5AF6D8A24")

    identity = RecordIdentity(values={"id": value})
    decoded = IdentityCodec().decode(IdentityCodec().encode(identity))

    assert identity.values == {"id": value}
    assert decoded == identity


def test_identity_copies_and_freezes_caller_mapping_without_breaking_serialization() -> None:
    values = {"tenant": "north", "id": 42}
    identity = RecordIdentity(values=values)

    values["id"] = 99

    assert identity.values == {"id": 42, "tenant": "north"}
    assert identity.model_dump() == {"values": {"id": 42, "tenant": "north"}}
    assert identity.model_dump_json() == '{"values":{"id":42,"tenant":"north"}}'
    frozen_values = cast(Any, identity.values)
    with pytest.raises(TypeError, match="immutable"):
        frozen_values["id"] = 7


@pytest.mark.parametrize("encoded", ("not-base64!", "W10", "eyJpZCI6WzFdfQ"))
def test_malformed_or_wrong_shaped_identity_token_has_stable_decode_error(encoded: str) -> None:
    with pytest.raises(ValueError, match="Invalid identity token"):
        IdentityCodec().decode(encoded)


def test_canonical_identity_payload_is_type_stable_and_uuid_safe() -> None:
    integer = canonical_identity_payload(RecordIdentity(values={"id": 1}))
    text = canonical_identity_payload(RecordIdentity(values={"id": "1"}))
    uuid = canonical_identity_payload(
        RecordIdentity(values={"id": UUID("12345678-1234-5678-1234-567812345678")})
    )

    assert integer == {"id": {"type": "int", "value": 1}}
    assert text == {"id": {"type": "str", "value": "1"}}
    assert uuid == {"id": {"type": "uuid", "value": "12345678-1234-5678-1234-567812345678"}}
