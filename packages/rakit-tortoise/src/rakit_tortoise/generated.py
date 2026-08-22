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
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.models import Model

from .datasource import TortoiseDataSource
from .uow import TortoiseUnitOfWork


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
class TortoiseGeneratedResourceExecutorProvider(GeneratedResourceExecutorProvider):
    model: type[Model]
    data_source: TortoiseDataSource

    def build(self, context: GeneratedResourceExecutorContext) -> GeneratedResourceExecutor:
        if context.data_source is not self.data_source:
            raise _config_error(
                context.resource_id,
                "generated_api_tortoise_datasource_mismatch",
                "Tortoise generated CRUD data source does not match its provider.",
            )
        if context.concurrency_provider is not None or context.concurrency_tokens is not None:
            raise _config_error(
                context.resource_id,
                "generated_api_tortoise_concurrency_not_supported",
                "Tortoise optimistic concurrency is not enabled by this provider.",
            )
        return TortoiseGeneratedResourceExecutor(
            resource_id=context.resource_id,
            model=self.model,
            data_source=self.data_source,
        )


@dataclass(frozen=True, slots=True)
class TortoiseGeneratedResourceExecutor:
    resource_id: str
    model: type[Model]
    data_source: TortoiseDataSource

    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=False,
    )

    def _uow(self, context: OperationContext) -> TortoiseUnitOfWork:
        uow = context.unit_of_work
        if not isinstance(uow, TortoiseUnitOfWork):
            raise _config_error(
                self.resource_id,
                "generated_api_tortoise_uow_required",
                "Tortoise generated CRUD must execute inside the Rakit root unit of work.",
            )
        return uow

    def _identity_kwargs(self, identity: RecordIdentity) -> dict[str, object]:
        identity_field = self.data_source.identity_fields[0]
        if set(identity.values) != {identity_field}:
            raise _config_error(
                self.resource_id,
                "generated_api_tortoise_identity_invalid",
                "Generated CRUD identity does not match the Tortoise resource.",
            )
        return dict(identity.values)

    async def _record(
        self,
        connection: BaseDBAsyncClient,
        identity: RecordIdentity,
    ) -> Model | None:
        return (
            await self.model.filter(**self._identity_kwargs(identity)).using_db(connection).first()
        )

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
            "generated_api_tortoise_operation_not_supported",
            "Tortoise generated mutation executor received a read operation.",
        )

    async def _create(
        self,
        context: OperationContext,
        connection: BaseDBAsyncClient,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_tortoise_input_required",
                "Generated create input is missing.",
            )
        record = await self.model.create(using_db=connection, **request.input.values)
        identity_field = self.data_source.identity_fields[0]
        identity_value = getattr(record, identity_field)
        if isinstance(identity_value, bool) or not isinstance(identity_value, int | str | UUID):
            raise _config_error(
                self.resource_id,
                "generated_api_tortoise_identity_unavailable",
                "Generated create returned an unsupported primary-key value.",
            )
        identity = RecordIdentity(values={identity_field: identity_value})
        if context.events is not None:
            context.events.publish(ResourceCreated(identity))
        return GeneratedMutationResult(identity=identity, record=record)

    async def _update(
        self,
        context: OperationContext,
        connection: BaseDBAsyncClient,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.identity is None or request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_tortoise_update_request_invalid",
                "Generated update request is incomplete.",
            )
        current = await self._record(connection, request.identity)
        if current is None:
            raise _not_found(self.resource_id)
        updated = (
            await self.model.filter(**self._identity_kwargs(request.identity))
            .using_db(connection)
            .update(**request.input.values)
        )
        if updated != 1:
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
        connection: BaseDBAsyncClient,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.identity is None:
            raise _config_error(
                self.resource_id,
                "generated_api_tortoise_delete_request_invalid",
                "Generated delete request is incomplete.",
            )
        deleted = (
            await self.model.filter(**self._identity_kwargs(request.identity))
            .using_db(connection)
            .delete()
        )
        if deleted != 1:
            raise _not_found(self.resource_id)
        if context.events is not None:
            context.events.publish(ResourceDeleted(request.identity))
        return GeneratedMutationResult(identity=request.identity, record=None)


__all__ = [
    "TortoiseGeneratedResourceExecutor",
    "TortoiseGeneratedResourceExecutorProvider",
]
