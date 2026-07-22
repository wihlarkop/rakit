import pytest
from rakit_core.identity import IdentityCodec, RecordIdentity


def test_identity_round_trip_is_deterministic() -> None:
    identity = RecordIdentity(values={"id": "user/42"})
    codec = IdentityCodec()
    encoded = codec.encode(identity)
    assert "/" not in encoded
    assert codec.decode(encoded) == identity


def test_identity_requires_at_least_one_field() -> None:
    with pytest.raises(ValueError):
        RecordIdentity(values={})
