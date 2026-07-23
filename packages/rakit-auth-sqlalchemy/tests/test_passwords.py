import pytest
from rakit_auth_sqlalchemy.passwords import Argon2PasswordHasher


async def test_password_hash_is_argon2_and_has_no_plaintext() -> None:
    hasher = Argon2PasswordHasher()
    encoded = await hasher.hash("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert "correct horse" not in encoded
    assert await hasher.verify("correct horse battery staple", encoded)


async def test_wrong_password_does_not_verify() -> None:
    hasher = Argon2PasswordHasher()
    encoded = await hasher.hash("correct horse battery staple")
    assert not await hasher.verify("wrong password", encoded)


async def test_malformed_hash_does_not_verify_or_raise() -> None:
    hasher = Argon2PasswordHasher()
    assert not await hasher.verify("anything", "not-a-real-hash")


async def test_two_hashes_of_the_same_password_differ() -> None:
    """Argon2 salts each hash independently -- two hashes of an identical
    password must not be byte-identical, or a database leak would reveal
    which users share a password."""
    hasher = Argon2PasswordHasher()
    first = await hasher.hash("correct horse battery staple")
    second = await hasher.hash("correct horse battery staple")
    assert first != second
    assert await hasher.verify("correct horse battery staple", first)
    assert await hasher.verify("correct horse battery staple", second)


async def test_needs_rehash_is_false_for_a_freshly_issued_hash() -> None:
    hasher = Argon2PasswordHasher()
    encoded = await hasher.hash("correct horse battery staple")
    assert hasher.needs_rehash(encoded) is False


@pytest.mark.parametrize("concurrency", [8])
async def test_concurrent_hashing_does_not_deadlock(concurrency: int) -> None:
    """Hashing runs off the event loop through a bounded capacity limiter --
    this proves multiple concurrent hash() calls all complete rather than
    deadlocking against that bound."""
    import anyio

    hasher = Argon2PasswordHasher()

    async def _hash_one(index: int, results: list[str]) -> None:
        results.append(await hasher.hash(f"password-{index}"))

    results: list[str] = []
    async with anyio.create_task_group() as task_group:
        for index in range(concurrency):
            task_group.start_soon(_hash_one, index, results)

    assert len(results) == concurrency
