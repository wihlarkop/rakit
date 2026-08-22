from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from peewee import DoesNotExist, Model
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

from .datasource import PeeweeDataSource
from .uow import PeeweeUnitOfWork


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
class PeeweeGeneratedResourceExecutorProvider(GeneratedResourceExecutorProvider):
    model: type[Model]
    data_source: PeeweeDataSource

    def build(self, context: GeneratedResourceExecutorContext) -> GeneratedResourceExecutor:
        if context.data_source is not self.data_source:
            raise _config_error(
                context.resource_id,
                "generated_api_peewee_datasource_mismatch",
                "Peewee generated CRUD data source does not match its provider.",
            )
        if context.concurrency_provider is not None or context.concurrency_tokens is not None:
            raise _config_error(
                context.resource_id,
                "generated_api_peewee_concurrency_not_supported",
                "Peewee optimistic concurrency is not enabled by this provider.",
            )
        return PeeweeGeneratedResourceExecutor(
            resource_id=context.resource_id,
            model=self.model,
            data_source=self.data_source,
        )


@dataclass(frozen=True, slots=True)
class PeeweeGeneratedResourceExecutor:
    resource_id: str
    model: type[Model]
    data_source: PeeweeDataSource

    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=False,
    )

    def _uow(self, context: OperationContext) -> PeeweeUnitOfWork:
        uow = context.unit_of_work
        if not isinstance(uow, PeeweeUnitOfWork):
            raise _config_error(
                self.resource_id,
                "generated_api_peewee_uow_required",
                "Peewee generated CRUD must execute inside the Rakit root unit of work.",
            )
        if uow.database is not self.data_source.database:
            raise _config_error(
                self.resource_id,
                "generated_api_peewee_database_mismatch",
                "Peewee generated CRUD unit of work uses a different database.",
            )
        return uow

    def _identity_value(self, identity: RecordIdentity) -> object:
        identity_field = self.data_source.identity_fields[0]
        if set(identity.values) != {identity_field}:
            raise _config_error(
                self.resource_id,
                "generated_api_peewee_identity_invalid",
                "Generated CRUD identity does not match the Peewee resource.",
            )
        return identity.values[identity_field]

    def _identity_field(self) -> object:
        return getattr(self.model, self.data_source.identity_fields[0])

    async def _record(self, identity: RecordIdentity) -> Model | None:
        try:
            return await self.data_source.database.get(
                self.model.select().where(self._identity_field() == self._identity_value(identity))
            )
        except DoesNotExist:
            return None

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
            "generated_api_peewee_operation_not_supported",
            "Peewee generated mutation executor received a read operation.",
        )

    async def _create(
        self,
        context: OperationContext,
        request: GeneratedCrudRequest,
    ) -> GeneratedMutationResult:
        if request.input is None:
            raise _config_error(
                self.resource_id,
                "generated_api_peewee_input_required",
                "Generated create input is missing.",
            )
        identity_value = await self.data_source.database.aexecute(
            self.model.insert(**request.input.values)
        )
        if isinstance(identity_value, bool) or not isinstance(identity_value, int | str | UUID):
            raise _config_error(
                self.resource_id,
                "generated_api_peewee_identity_unavailable",
                "Generated create returned an unsupported primary-key value.",
            )
        identity_field = self.data_source.identity_fields[0]
        identity = RecordIdentity(values={identity_field: identity_value})
        record = await self._record(identity)
        if record is None:
            raise _not_found(self.resource_id)
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
                "generated_api_peewee_update_request_invalid",
                "Generated update request is incomplete.",
            )
        updated = await self.data_source.database.aexecute(
            self.model.update(**request.input.values).where(
                self._identity_field() == self._identity_value(request.identity)
            )
        )
        if updated != 1:
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
                "generated_api_peewee_delete_request_invalid",
                "Generated delete request is incomplete.",
            )
        deleted = await self.data_source.database.aexecute(
            self.model.delete().where(
                self._identity_field() == self._identity_value(request.identity)
            )
        )
        if deleted != 1:
            raise _not_found(self.resource_id)
        if context.events is not None:
            context.events.publish(ResourceDeleted(request.identity))
        return GeneratedMutationResult(identity=request.identity, record=None)


__all__ = [
    "PeeweeGeneratedResourceExecutor",
    "PeeweeGeneratedResourceExecutorProvider",
]
