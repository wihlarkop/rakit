from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

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
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import ResourceCreated, ResourceDeleted, ResourceUpdated
from rakit_core.operations import OperationContext, OperationExecutorCapabilities
from sqlalchemy import delete as sa_delete
from sqlalchemy import insert as sa_insert
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncConnection

from .core_datasource import SQLAlchemyCoreDataSource
from .core_uow import SQLAlchemyCoreUnitOfWork


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


@dataclass(frozen=True, slots=True)
class SQLAlchemyCoreGeneratedResourceExecutorProvider(GeneratedResourceExecutorProvider):
    data_source: SQLAlchemyCoreDataSource

    def build(self, context: GeneratedResourceExecutorContext) -> GeneratedResourceExecutor:
        if context.data_source is not self.data_source:
            raise _config_error(
                context.resource_id,
                "generated_api_sqlalchemy_core_datasource_mismatch",
                "SQLAlchemy Core generated CRUD data source does not match its provider.",
            )
        if context.concurrency_provider is not None or context.concurrency_tokens is not None:
            raise _config_error(
                context.resource_id,
                "generated_api_sqlalchemy_core_concurrency_not_supported",
                "SQLAlchemy Core optimistic concurrency is not enabled by this provider.",
            )
        return SQLAlchemyCoreGeneratedResourceExecutor(
            resource_id=context.resource_id,
            data_source=self.data_source,
        )


@dataclass(frozen=True, slots=True)
class SQLAlchemyCoreGeneratedResourceExecutor:
    resource_id: str
    data_source: SQLAlchemyCoreDataSource

    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=False,
    )

    def _uow(self, context: OperationContext) -> SQLAlchemyCoreUnitOfWork:
        uow = context.unit_of_work
        if not isinstance(uow, SQLAlchemyCoreUnitOfWork):
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_core_uow_required",
                "SQLAlchemy Core generated CRUD must execute inside the Rakit root unit of work.",
            )
        return uow

    async def execute(
        self,
        context: OperationContext,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        context.checkpoint()
        connection = self._uow(context).connection
        if request.operation is GeneratedCrudOperation.CREATE:
            return await self._create(context, connection, request)
        if request.operation is GeneratedCrudOperation.UPDATE_PARTIAL:
            return await self._update(context, connection, request)
        if request.operation is GeneratedCrudOperation.DELETE:
            return await self._delete(context, connection, request)
        raise _config_error(
            self.resource_id,
            "generated_api_sqlalchemy_core_operation_not_supported",
            "SQLAlchemy Core generated mutation executor received a read operation.",
        )

    async def _record(
        self,
        connection: AsyncConnection,
        identity: RecordIdentity,
    ) -> dict[str, object] | None:
        identity_field = self.data_source.identity_fields[0]
        if set(identity.values) != {identity_field}:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_core_identity_invalid",
                "Generated CRUD identity does not match the SQLAlchemy Core resource.",
            )
        column = self.data_source._table.c[identity_field]
        result = await connection.execute(
            select(self.data_source._table).where(column == identity.values[identity_field])
        )
        row = result.mappings().one_or_none()
        return None if row is None else dict(row)

    async def _create(
        self,
        context: OperationContext,
        connection: AsyncConnection,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_core_input_required",
                "Generated create input is missing.",
            )
        result = await connection.execute(
            sa_insert(self.data_source._table).values(**request.input.values)
        )
        inserted_primary_key = result.inserted_primary_key
        if inserted_primary_key is None or len(inserted_primary_key) != 1:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_core_identity_unavailable",
                "Generated create did not return one primary-key value.",
            )
        identity_value = inserted_primary_key[0]
        if isinstance(identity_value, bool) or not isinstance(identity_value, int | str | UUID):
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_core_identity_unavailable",
                "Generated create returned an unsupported primary-key value.",
            )
        identity = RecordIdentity(values={self.data_source.identity_fields[0]: identity_value})
        record = await self._record(connection, identity)
        if record is None:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_core_created_record_missing",
                "Generated create could not reload the inserted record.",
            )
        if context.events is not None:
            context.events.publish(ResourceCreated(identity))
        return GeneratedMutationResult(identity=identity, record=record)

    async def _update(
        self,
        context: OperationContext,
        connection: AsyncConnection,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.identity is None or request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_core_update_request_invalid",
                "Generated update request is incomplete.",
            )
        current = await self._record(connection, request.identity)
        if current is None:
            raise _not_found(self.resource_id)
        identity_field = self.data_source.identity_fields[0]
        column = self.data_source._table.c[identity_field]
        result = await connection.execute(
            sa_update(self.data_source._table)
            .where(column == request.identity.values[identity_field])
            .values(**request.input.values)
        )
        if result.rowcount != 1:
            raise _not_found(self.resource_id)
        record = await self._record(connection, request.identity)
        if record is None:
            raise _not_found(self.resource_id)
        if context.events is not None:
            context.events.publish(
                ResourceUpdated(
                    request.identity,
                    tuple(sorted(request.input.present_fields)),
                )
            )
        return GeneratedMutationResult(identity=request.identity, record=record)

    async def _delete(
        self,
        context: OperationContext,
        connection: AsyncConnection,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.identity is None:
            raise _config_error(
                self.resource_id,
                "generated_api_sqlalchemy_core_delete_request_invalid",
                "Generated delete request is incomplete.",
            )
        identity_field = self.data_source.identity_fields[0]
        column = self.data_source._table.c[identity_field]
        result = await connection.execute(
            sa_delete(self.data_source._table).where(
                column == request.identity.values[identity_field]
            )
        )
        if result.rowcount != 1:
            raise _not_found(self.resource_id)
        if context.events is not None:
            context.events.publish(ResourceDeleted(request.identity))
        return GeneratedMutationResult(identity=request.identity, record=None)


__all__ = [
    "SQLAlchemyCoreGeneratedResourceExecutor",
    "SQLAlchemyCoreGeneratedResourceExecutorProvider",
]
