from dataclasses import dataclass
from typing import cast

from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_api import GeneratedCrudOperation
from rakit_core.generated_operations import (
    GeneratedCrudRequest,
    GeneratedMutationResult,
    GeneratedResourceExecutor,
)
from rakit_core.generated_runtime import (
    GeneratedResourceExecutorContext,
    GeneratedResourceExecutorProvider,
)
from rakit_core.mutations import ResourceCreated, ResourceDeleted, ResourceUpdated
from rakit_core.operations import OperationContext, OperationExecutorCapabilities
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from .datasource import SQLAlchemyDataSource
from .uow import SQLAlchemyUnitOfWork


def _config_error(resource_id: str, reason: str, message: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=message,
        status_code=500,
        details={"resource_id": resource_id, "reason": reason},
    )


def _not_found(resource_id: str) -> RakitError:
    return RakitError(
        code=ErrorCode.RESOURCE_NOT_FOUND,
        message="Resource record not found.",
        status_code=404,
        details={"resource_id": resource_id},
    )


def _conflict(resource_id: str) -> RakitError:
    return RakitError(
        code=ErrorCode.RESOURCE_CONFLICT,
        message="The resource changed before the mutation could be applied.",
        status_code=409,
        details={"resource_id": resource_id},
    )


@dataclass(frozen=True, slots=True)
class SQLAlchemyGeneratedResourceExecutorProvider(GeneratedResourceExecutorProvider):
    model: type[object]

    def build(self, context: GeneratedResourceExecutorContext) -> GeneratedResourceExecutor:
        data_source = context.data_source
        if not isinstance(data_source, SQLAlchemyDataSource):
            raise _config_error(
                context.resource_id,
                "generated_api_sqlalchemy_datasource_required",
                "SQLAlchemy generated CRUD requires a SQLAlchemy data source.",
            )
        if getattr(data_source, "_model", None) is not self.model:
            raise _config_error(
                context.resource_id,
                "generated_api_sqlalchemy_model_mismatch",
                "SQLAlchemy generated CRUD model does not match its data source.",
            )
        if (context.concurrency_provider is None) != (context.concurrency_tokens is None):
            raise _config_error(
                context.resource_id,
                "generated_api_sqlalchemy_concurrency_incomplete",
                "SQLAlchemy generated CRUD concurrency requires both provider and token service.",
            )
        return SQLAlchemyGeneratedResourceExecutor(
            resource_id=context.resource_id,
            model=self.model,
            data_source=data_source,
            concurrency_provider=context.concurrency_provider,
            concurrency_tokens=context.concurrency_tokens,
        )


@dataclass(frozen=True, slots=True)
class SQLAlchemyGeneratedResourceExecutor:
    resource_id: str
    model: type[object]
    data_source: SQLAlchemyDataSource
    concurrency_provider: object | None = None
    concurrency_tokens: object | None = None

    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=True,
    )

    def _uow(self, context: OperationContext) -> SQLAlchemyUnitOfWork:
        uow = context.unit_of_work
        if not isinstance(uow, SQLAlchemyUnitOfWork):
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_uow_required",
                "SQLAlchemy generated CRUD must execute inside the Rakit root unit of work.",
            )
        return uow

    async def execute(
        self,
        context: OperationContext,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        context.checkpoint()
        uow = self._uow(context)
        if request.operation is GeneratedCrudOperation.CREATE:
            return await self._create(context, uow.session, request)
        if request.operation is GeneratedCrudOperation.UPDATE_PARTIAL:
            return await self._update(context, uow.session, request)
        if request.operation is GeneratedCrudOperation.DELETE:
            return await self._delete(context, uow.session, request)
        raise _config_error(
            self.resource_id,
            "generated_api_sqlalchemy_operation_not_supported",
            "SQLAlchemy generated mutation executor received a read operation.",
        )

    async def _create(
        self,
        context: OperationContext,
        session: AsyncSession,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_input_required",
                "Generated create input is missing.",
            )
        record = self.model(**dict(request.input.values))
        session.add(record)
        await session.flush()
        identity = self.data_source.identity_for(record)
        if context.events is not None:
            context.events.publish(ResourceCreated(identity))
        return GeneratedMutationResult(identity=identity, record=record)

    def _scoped_identity_subquery(self, identity):
        identity_field = self.data_source.identity_fields[0]
        identity_column = getattr(self.model, identity_field)
        return (
            self.data_source.scoped_statement()
            .where(*self.data_source.identity_conditions(identity))
            .with_only_columns(identity_column)
            .scalar_subquery()
        )

    def _concurrency_values(self, current: object, request: GeneratedCrudRequest):
        provider = self.concurrency_provider
        tokens = self.concurrency_tokens
        if provider is None and tokens is None:
            return {}, {}
        if provider is None or tokens is None:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_concurrency_incomplete",
                "Generated CRUD concurrency runtime is incomplete.",
            )
        token = request.concurrency_token
        if token is None:
            raise _conflict(self.resource_id)
        provider = cast("object", provider)
        tokens = cast("object", tokens)
        verify = getattr(tokens, "verify", None)
        predicate_values_for = getattr(provider, "predicate_values_for", None)
        next_values_for = getattr(provider, "next_values_for", None)
        version_for = getattr(provider, "version_for", None)
        if not all(callable(item) for item in (verify, predicate_values_for, next_values_for, version_for)):
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_concurrency_invalid",
                "Generated CRUD concurrency provider is invalid.",
            )
        verify(token, self.resource_id, request.identity, version_for(current))
        predicate_values = dict(predicate_values_for(current))
        next_values = dict(next_values_for(current))
        return predicate_values, next_values

    async def _update(
        self,
        context: OperationContext,
        session: AsyncSession,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.identity is None or request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_update_request_invalid",
                "Generated update request is incomplete.",
            )
        current = await self.data_source.resolve_scoped(session, request.identity)
        if current is None:
            raise _not_found(self.resource_id)

        changes = dict(request.input.values)
        predicate_values, next_values = self._concurrency_values(current, request)
        overlap = set(changes).intersection(next_values)
        if overlap:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_concurrency_field_writable",
                "Concurrency-managed fields cannot be changed by generated input.",
            )

        identity_column = getattr(self.model, self.data_source.identity_fields[0])
        predicates = [identity_column.in_(self._scoped_identity_subquery(request.identity))]
        predicates.extend(getattr(self.model, key) == value for key, value in predicate_values.items())
        statement = (
            sa_update(self.model)
            .where(*predicates)
            .values({**changes, **next_values})
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(statement)
        if result.rowcount != 1:
            raise _conflict(self.resource_id)
        await session.refresh(current)
        if context.events is not None:
            context.events.publish(
                ResourceUpdated(
                    request.identity,
                    tuple(sorted(request.input.present_fields)),
                )
            )
        return GeneratedMutationResult(identity=request.identity, record=current)

    async def _delete(
        self,
        context: OperationContext,
        session: AsyncSession,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.identity is None:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_delete_request_invalid",
                "Generated delete request is incomplete.",
            )
        current = await self.data_source.resolve_scoped(session, request.identity)
        if current is None:
            raise _not_found(self.resource_id)
        predicate_values, _ = self._concurrency_values(current, request)

        identity_column = getattr(self.model, self.data_source.identity_fields[0])
        predicates = [identity_column.in_(self._scoped_identity_subquery(request.identity))]
        predicates.extend(getattr(self.model, key) == value for key, value in predicate_values.items())
        statement = (
            sa_delete(self.model)
            .where(*predicates)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(statement)
        if result.rowcount != 1:
            raise _conflict(self.resource_id)
        if context.events is not None:
            context.events.publish(ResourceDeleted(request.identity))
        return GeneratedMutationResult(identity=request.identity, record=None)


__all__ = [
    "SQLAlchemyGeneratedResourceExecutor",
    "SQLAlchemyGeneratedResourceExecutorProvider",
]
