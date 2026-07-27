import secrets
from datetime import UTC, datetime

from rakit_core.auth import Principal, normalize_identifier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from .models import Role, User
from .passwords import Argon2PasswordHasher

# Deliberately the shared canonicalization, not a private copy: the login
# rate limiter keys off the same function, and two subtly different
# implementations would let one account occupy several limiter buckets.
_normalize_identifier = normalize_identifier


class SQLAlchemyAuthBackend:
    """Concrete `AuthBackend` (and request-time `resolve_principal`)
    backed by the built-in `User`/`Role`/`Permission` schema.

    Email is the login identifier (the framework design's default).
    Identifiers are normalized (stripped, lowercased) before lookup, the
    same way `User.email` is itself stored normalized -- so "Ada@x" at
    login matches a user stored as "ada@x".
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        password_hasher: Argon2PasswordHasher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._password_hasher = password_hasher or Argon2PasswordHasher()
        self._dummy_hash: str | None = None

    async def _get_dummy_hash(self) -> str:
        # Computed once, lazily, and cached -- every subsequent "unknown or
        # inactive user" rejection pays the same Argon2 cost a real
        # password verification would, so response timing doesn't reveal
        # whether the identifier exists or is merely inactive. The dummy
        # password itself is arbitrary and never used for anything else.
        if self._dummy_hash is None:
            self._dummy_hash = await self._password_hasher.hash(secrets.token_urlsafe(32))
        return self._dummy_hash

    @staticmethod
    def _principal_from_user(user: User) -> Principal:
        permissions = frozenset(
            permission.key
            for role in user.roles
            for permission in role.permissions
            if not permission.orphaned
        )
        return Principal(
            subject_id=str(user.id),
            authenticated=True,
            display_name=user.display_name,
            permissions=permissions,
            is_superuser=user.is_superuser,
        )

    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        normalized = _normalize_identifier(identifier)
        async with self._session_factory() as session:
            user = (
                await session.execute(
                    select(User)
                    .options(selectinload(User.roles).selectinload(Role.permissions))
                    .where(User.email == normalized)
                )
            ).scalar_one_or_none()

            if user is None or not user.is_active:
                await self._password_hasher.verify(password, await self._get_dummy_hash())
                return None

            if not await self._password_hasher.verify(password, user.password_hash):
                return None

            user.last_login_at = datetime.now(UTC)
            principal = self._principal_from_user(user)
            await session.commit()
            return principal

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        try:
            numeric_id = int(subject_id)
        except ValueError:
            return None
        async with self._session_factory() as session:
            user = await session.get(
                User,
                numeric_id,
                options=[selectinload(User.roles).selectinload(Role.permissions)],
            )
            if user is None or not user.is_active:
                return None
            return self._principal_from_user(user)
