from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from piccolo.table import Table
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

from .datasource import PiccoloDataSource
from .uow import PiccoloUnitOfWork


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
class PiccoloGeneratedResourceExecutorProvider(GeneratedResourceExecutorProvider):
    model: type[Table]
    data_source: PiccoloDataSource

    def build(self, context: GeneratedResourceExecutorContext) -> GeneratedResourceExecutor:
        if context.data_source is not self.data_source:
            raise _config_error(
                context.resource_id,
                "generated_api_piccolo_datasource_mismatch",
                "Piccolo generated CRUD data source does not match its provider.",
            )
        if context.concurrency_provider is not None or context.concurrency_tokens is not None:
            raise _config_error(
                context.resource_id,
                "generated_api_piccolo_concurrency_not_supported",
                "Piccolo optimistic concurrency is not enabled by this provider.",
            )
        return PiccoloGeneratedResourceExecutor(
            resource_id=context.resource_id,
            model=self.model,
            data_source=self.data_source,
        )


@dataclass(frozen=True, slots=True)
class PiccoloGeneratedResourceExecutor:
    resource_id: str
    model: type[Table]
    data_source: PiccoloDataSource

    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=False,
    )

    def _uow(self, context: OperationContext) -> PiccoloUnitOfWork:
        uow = context.unit_of_work
        if not isinstance(uow, PiccoloUnitOfWork):
            raise _config_error(
                self.resource_id,
                "generated_api_piccolo_uow_required",
                "Piccolo generated CRUD must execute inside the Rakit root unit of work.",
            )
        if uow.engine is not self.data_source.engine:
            raise _config_error(
                self.resource_id,
                "generated_api_piccolo_engine_mismatch",
                "Piccolo generated CRUD unit of work uses a different engine.",
            )
        return uow

    def _identity_value(self, identity: RecordIdentity) -> object:
        identity_field = self.data_source.identity_fields[0]
        if set(identity.values) != {identity_field}:
            raise _config_error(
                self.resource_id,
                "generated_api_piccolo_identity_invalid",
                "Generated CRUD identity does not match the Piccolo resource.",
            )
        return identity.values[identity_field]

    def _identity_column(self):
        return getattr(self.model, self.data_source.identity_fields[0])

    async def _record(self, identity: RecordIdentity) -> Table | None:
        return (
            await self.model.objects()
            .where(self._identity_column() == self._identity_value(identity))
            .first()
        )

    async def execute(
        self,
        context: OperationContext,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        context.checkpoint()
        self._uow(context)
        if request.operation is GeneratedCrudOperation.CREATE:
            return await self._create(context, request)
        if request.operation is GeneratedCrudOperation.UPDATE_PARTIAL:
            return await self._update(context, request)
        if request.operation is GeneratedCrudOperation.DELETE:
            return await self._delete(context, request)
        raise _config_error(
            self.resource_id,
            "generated_api_piccolo_operation_not_supported",
            "Piccolo generated mutation executor received a read operation.",
        )

    async def _create(
        self,
        context: OperationContext,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_piccolo_input_required",
                "Generated create input is missing.",
            )
        record = await self.model.objects().create(**request.input.values)
        identity_value = getattr(record, self.data_source.identity_fields[0])
        if isinstance(identity_value, bool) or not isinstance(identity_value, int | str | UUID):
            raise _config_error(
                self.resource_id,
                "generated_api_piccolo_identity_unavailable",
                "Generated create returned an unsupported primary-key value.",
            )
        identity = RecordIdentity(values={self.data_source.identity_fields[0]: identity_value})
        if context.events is not None:
            context.events.publish(ResourceCreated(identity))
        return GeneratedMutationResult(identity=identity, record=record)

    async def _update(
        self,
        context: OperationContext,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.identity is None or request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_piccolo_update_request_invalid",
                "Generated update request is incomplete.",
            )
        updated = (
            await self.model.update(dict(request.input.values))
            .where(self._identity_column() == self._identity_value(request.identity))
            .returning(self._identity_column())
        )
        if len(updated) != 1:
            raise _not_found(self.resource_id)
        record = await self._record(request.identity)
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
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.identity is None:
            raise _config_error(
                self.resource_id,
                "generated_api_piccolo_delete_request_invalid",
                "Generated delete request is incomplete.",
            )
        deleted = (
            await self.model.delete()
            .where(self._identity_column() == self._identity_value(request.identity))
            .returning(self._identity_column())
        )
        if len(deleted) != 1:
            raise _not_found(self.resource_id)
        if context.events is not None:
            context.events.publish(ResourceDeleted(request.identity))
        return GeneratedMutationResult(identity=request.identity, record=None)


__all__ = [
    "PiccoloGeneratedResourceExecutor",
    "PiccoloGeneratedResourceExecutorProvider",
]
