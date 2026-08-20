from rakit_core.generated_runtime import ResourceWriteServiceContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .introspection import inspect_model
from .mutations import SQLAlchemyMutationService


class SQLAlchemyWriteServiceProvider:
    """Materialize Rakit's neutral write declaration for one ORM model."""

    def __init__(
        self,
        *,
        model: type[object],
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._model = model
        self._session_factory = session_factory

    def build(self, context: ResourceWriteServiceContext) -> SQLAlchemyMutationService:
        metadata = inspect_model(self._model)
        return SQLAlchemyMutationService(
            model=self._model,
            session_factory=self._session_factory,
            form_schema=context.definition.form_schema,
            writable_fields=context.definition.writable_fields,
            identity_fields=(metadata.identity_field,),
            token_service=context.token_service,
            version_field=context.definition.version_field,
            resource_id=context.resource_id,
            delete_permission=(
                f"{context.admin_id}.resources.{context.resource_id}.delete"
            ),
            force_overwrite_permission=(
                f"{context.admin_id}.resources.{context.resource_id}.force_overwrite"
            ),
        )


__all__ = ["SQLAlchemyWriteServiceProvider"]
