"""SQLAlchemy-backed scoped relationship resolution and mutation execution."""

from collections.abc import Callable

from rakit_core.identity import RecordIdentity
from rakit_core.relationship_mutations import RelationshipCandidate
from sqlalchemy.ext.asyncio import AsyncSession

from .datasource import SQLAlchemyDataSource


class SQLAlchemyRelationshipResolver:
    """Resolve relationship parents/targets solely through a resource scope.

    ``resolve`` returns an adapter-private ORM record for the mutation engine;
    public callers use ``candidate`` and receive only identity plus plain text
    label.  Neither path opens or commits a transaction.
    """

    def __init__(self, data_source: SQLAlchemyDataSource) -> None:
        self._data_source = data_source

    async def resolve(self, session: AsyncSession, identity: RecordIdentity) -> object | None:
        return await self._data_source.resolve_scoped(session, identity)

    async def candidate(
        self,
        session: AsyncSession,
        identity: RecordIdentity,
        *,
        label: Callable[[object], str],
    ) -> RelationshipCandidate | None:
        record = await self.resolve(session, identity)
        if record is None:
            return None
        return RelationshipCandidate(
            identity=self._data_source.identity_for(record), label=label(record)
        )


__all__ = ["SQLAlchemyRelationshipResolver"]
