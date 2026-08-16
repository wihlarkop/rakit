"""Sanctioned SQLAlchemy mutation executors for action operations.

The ordinary :class:`~rakit_core.actions.PreparedMutationExecutor` can only
promise participation in a Rakit-owned unit of work. This module contains the
narrow adapter-owned path that can additionally prove atomic optimistic
concurrency: a RECORD action delegates to ``SQLAlchemyMutationService``'s
existing ``update_in_uow`` primitive using the active root operation UoW.

The action permission remains the authoritative permission. The executor
creates an exact nested ``update`` capability carrying that same requirement;
it never asks for, invents, or masquerades as the resource's generic update
permission.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from rakit_core.actions import (
    ActionContext,
    ActionScope,
    ActionSuccess,
    PreparedMutationExecutor,
)
from rakit_core.concurrency import AttributeVersionProvider
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.mutations import MutationResult, OperationAuthorization, OperationAuthorizationSet
from rakit_core.operations import OperationExecutorCapabilities, current_operation_context
from rakit_core.transactions import TransactionPolicy

from .mutations import SQLAlchemyMutationService
from .uow import SQLAlchemyUnitOfWork


class SQLAlchemyActionUpdateExecutor(PreparedMutationExecutor):
    """Execute one prepared RECORD update inside the active action root UoW.

    This is the sanctioned C2B path for action-driven SQLAlchemy updates. It
    deliberately advertises ``atomic_concurrency=True`` only because it calls
    ``SQLAlchemyMutationService.update_in_uow`` with the exact active root UoW;
    that primitive performs the concurrency predicate at the SQL UPDATE write
    boundary and defers events/lifecycle observers to the root transaction.

    C2B supports only an atomically advanceable ``AttributeVersionProvider``.
    Snapshot providers intentionally remain unsupported here: their predicate
    can detect stale reads, but because they do not advance a dedicated version
    two concurrent actions that mutate other fields could both match it.
    """

    capabilities = OperationExecutorCapabilities(
        participates_in_uow=True,
        atomic_concurrency=True,
    )

    def __init__(
        self,
        mutation_service: SQLAlchemyMutationService,
        prepare: Callable[[ActionContext], object | Awaitable[object]],
        *,
        message: str | None = None,
    ) -> None:
        provider = mutation_service._concurrency_provider
        if (
            not isinstance(provider, AttributeVersionProvider)
            or mutation_service._concurrency is None
            or not mutation_service._attribute_version_is_safe(provider.field)
        ):
            raise ValueError(
                "SQLAlchemy action updates require an atomically advanceable "
                "attribute concurrency provider"
            )
        self._mutation_service = mutation_service
        self._session_factory = mutation_service._session_factory
        self._message = message
        super().__init__(prepare, self._commit_update)

    async def _commit_update(self, prepared: object, context: ActionContext) -> ActionSuccess:
        if context.scope is not ActionScope.RECORD or context.identity is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Sanctioned SQLAlchemy action updates require RECORD scope.",
                status_code=500,
            )
        if not isinstance(prepared, Mapping):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="SQLAlchemy action update preparation must return a mapping.",
                status_code=500,
            )

        action_authorization = context.authorization
        if (
            action_authorization is None
            or not action_authorization.operation.startswith("action:")
            or action_authorization.target_identity != context.identity
        ):
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Action mutation authorization is invalid.",
                status_code=403,
            )

        operation_context = current_operation_context()
        root_uow = operation_context.unit_of_work if operation_context is not None else None
        if not isinstance(root_uow, SQLAlchemyUnitOfWork):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="SQLAlchemy action updates require the active SQLAlchemy operation UoW.",
                status_code=500,
            )
        if root_uow.policy is not TransactionPolicy.AUTO:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Atomic SQLAlchemy action updates require TransactionPolicy.AUTO.",
                status_code=500,
            )
        if root_uow._session_factory is not self._session_factory:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Action mutation service and operation UoW must share one session factory.",
                status_code=500,
            )

        mutation_authorization = OperationAuthorization.for_requirement(
            admin_id=action_authorization.admin_id,
            resource_id=action_authorization.resource_id,
            operation="update",
            principal_id=action_authorization.principal_id,
            requirement=action_authorization.requirement,
            target_identity=context.identity,
        )
        authorizations = OperationAuthorizationSet(
            root=action_authorization,
            capabilities=(mutation_authorization,),
        )

        record = await self._mutation_service.update_in_uow(
            root_uow,
            context.identity,
            cast(Mapping[str, Any], prepared),
            concurrency_token=context.concurrency_token,
            authorizations=authorizations,
            operation="update",
            requirement=action_authorization.requirement,
        )
        return ActionSuccess(
            payload=MutationResult(identity=context.identity, record=record),
            message=self._message,
        )


__all__ = ["SQLAlchemyActionUpdateExecutor"]
