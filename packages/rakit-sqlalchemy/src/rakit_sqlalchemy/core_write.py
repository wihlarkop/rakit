from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any, cast

from rakit_core.concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.forms import FormSchema, FormValidationError
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest
from rakit_core.generated_runtime import ResourceWriteServiceContext, ResourceWriteServiceProvider
from rakit_core.idempotency import IdempotencyStatus, IdempotencyStore, OperationReceipt
from rakit_core.identity import RecordIdentity, canonical_identity_payload
from rakit_core.mutations import (
    GraphMutationResult,
    MutationAuthorization,
    MutationResult,
    OperationAuthorizationSet,
)
from rakit_core.operations import current_operation_context
from rakit_core.relationship_mutations import RelationshipChangePlan
from rakit_core.transactions import TransactionPolicy
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncEngine

from .core_concurrency import MappingVersionProvider
from .core_datasource import SQLAlchemyCoreDataSource
from .core_generated import SQLAlchemyCoreGeneratedResourceExecutor
from .core_relationship_mutations import SQLAlchemyCoreRelationshipMutationService
from .core_uow import SQLAlchemyCoreUnitOfWork


def _forbidden(message: str = "Mutation is not authorized.") -> RakitError:
    return RakitError(code=ErrorCode.AUTH_FORBIDDEN, message=message, status_code=403)


def _config(reason: str, message: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID,
        message=message,
        status_code=500,
        details={"reason": reason},
    )


def _validation(exc: ValueError) -> RakitError:
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message="Invalid form submission",
        status_code=422,
        cause=exc,
    )


class SQLAlchemyCoreMutationService:
    """Public form-write bridge for SQLAlchemy Core resources.

    Scalar persistence delegates to the already-conformant generated executor.
    Graph writes remain one transaction owner: the parent claim and every
    relationship step share one ``SQLAlchemyCoreUnitOfWork`` connection.
    """

    def __init__(
        self,
        *,
        resource_id: str,
        data_source: SQLAlchemyCoreDataSource,
        engine: AsyncEngine,
        form_schema: FormSchema,
        writable_fields: tuple[str, ...],
        token_service: TokenService,
        version_field: str | None,
    ) -> None:
        self._resource_id = resource_id
        self._data_source = data_source
        self._engine = engine
        self._form_schema = form_schema
        self._writable_fields = frozenset(writable_fields)
        self._token_service = token_service
        self._concurrency_provider: ConcurrencyVersionProvider | None = (
            MappingVersionProvider(version_field) if version_field is not None else None
        )
        self._concurrency = (
            ConcurrencyTokenService(token_service)
            if self._concurrency_provider is not None
            else None
        )
        self._executor = SQLAlchemyCoreGeneratedResourceExecutor(
            resource_id=resource_id,
            data_source=data_source,
            concurrency_provider=self._concurrency_provider,
            concurrency_tokens=self._concurrency,
        )
        self._relationship_service: SQLAlchemyCoreRelationshipMutationService | None = None
        self._graph_idempotency_store: IdempotencyStore | None = None
        self._delete_nonce_store: IdempotencyStore | None = None
        self._scoped_statement: Callable[[], Select] = data_source.scoped_statement

    def bind_delete_nonce_store(self, store: IdempotencyStore) -> None:
        self._delete_nonce_store = store

    def bind_graph_relationship_service(
        self,
        service: SQLAlchemyCoreRelationshipMutationService,
        *,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._relationship_service = service
        self._graph_idempotency_store = idempotency_store

    def bind_scoped_statement(self, statement: Callable[[], Select]) -> None:
        self._scoped_statement = statement

    def _require_authorization(
        self,
        authorization: MutationAuthorization | None,
        operation: str,
    ) -> MutationAuthorization:
        if (
            authorization is None
            or authorization.resource_id != self._resource_id
            or authorization.operation != operation
            or not authorization.admin_id
            or not authorization.principal_id
            or not authorization.permissions
        ):
            raise _forbidden()
        context = current_operation_context()
        if (
            context is None
            or context.principal is None
            or context.admin_id != authorization.admin_id
            or context.resource_id != authorization.resource_id
            or context.operation != authorization.operation
            or context.principal.subject_id != authorization.principal_id
            or context.permissions != authorization.permissions
            or context.permission_requirement != authorization.requirement
        ):
            raise _forbidden("Mutation authorization does not match this operation.")
        return authorization

    def _require_graph_authorizations(
        self,
        authorizations: OperationAuthorizationSet,
        *,
        operation: str,
        identity: RecordIdentity | None,
        changes: tuple[RelationshipChangePlan, ...],
    ) -> MutationAuthorization:
        root = self._require_authorization(authorizations.root, operation)
        relationship_service = self._relationship_service
        if changes and relationship_service is None:
            raise _config(
                "core_graph_relationship_service_missing",
                "Graph relationship mutation service is not configured.",
            )
        for change in changes:
            assert relationship_service is not None
            entry = relationship_service.compiled_relationship(change.relationship_id)
            if (
                change.authorization_requirement != entry.mutation_permission
                or not entry.definition.effective_writable
            ):
                raise _forbidden("Relationship mutation does not match compiled policy.")
            try:
                authorizations.require(
                    resource_id=entry.source_resource_id,
                    operation=change.operation_id,
                    requirement=entry.mutation_permission,
                    target_identity=identity,
                )
            except ValueError as exc:
                raise _forbidden(
                    "Relationship mutation requires an exact authorization capability."
                ) from exc
        return root

    def _prepare(self, submitted: Mapping[str, Any]) -> GeneratedInput:
        try:
            state = self._form_schema.parse(submitted)
        except (FormValidationError, ValueError) as exc:
            raise _validation(exc) from exc
        values = dict(state.normalized)
        if not set(values) <= self._writable_fields:
            raise _validation(ValueError("Field is not writable"))
        return GeneratedInput(values=values, present_fields=frozenset(values))

    async def _record_in_uow(
        self, uow: SQLAlchemyCoreUnitOfWork, identity: RecordIdentity
    ) -> dict[str, object] | None:
        return await self._data_source.resolve_scoped(uow.connection, identity)

    async def get(self, identity: RecordIdentity) -> object | None:
        if set(identity.values) != set(self._data_source.identity_fields):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid resource identity",
                status_code=400,
            )
        async with self._engine.connect() as connection:
            result = await connection.execute(
                self._scoped_statement().where(*self._data_source.identity_conditions(identity))
            )
            row = result.mappings().one_or_none()
            return None if row is None else dict(row)

    def issue_update_token(self, record: object) -> str:
        if self._concurrency is None or self._concurrency_provider is None:
            raise RuntimeError("This resource has no configured concurrency provider")
        identity = self._data_source.identity_for(record)
        return self._concurrency.issue(
            self._resource_id,
            identity,
            self._concurrency_provider.version_for(record),
            base_snapshot=dict(cast(Mapping[str, object], record)),
        )

    def _delete_purpose(self) -> str:
        return f"core-delete-{self._resource_id}"

    async def issue_delete_token(self, identity: RecordIdentity) -> str:
        record = await self.get(identity)
        if record is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="Resource was not found",
                status_code=404,
            )
        version = (
            self._concurrency_provider.version_for(record)
            if self._concurrency_provider is not None
            else None
        )
        return self._token_service.issue_in(
            self._delete_purpose(),
            {
                "identity": canonical_identity_payload(identity),
                "version": version,
            },
            timedelta(minutes=15),
        )

    async def _open_uow(self) -> SQLAlchemyCoreUnitOfWork:
        raise RuntimeError("SQLAlchemyCoreMutationService._open_uow is not called directly")

    async def _execute_scalar_in_uow(
        self,
        uow: SQLAlchemyCoreUnitOfWork,
        request: GeneratedCrudRequest,
    ):
        context = current_operation_context()
        if context is None:
            raise _forbidden("Mutation requires an active operation context.")
        previous_uow = context.unit_of_work
        object.__setattr__(context, "unit_of_work", uow)
        try:
            return await self._executor.execute(context, request)
        finally:
            object.__setattr__(context, "unit_of_work", previous_uow)

    async def create(
        self,
        submitted: Mapping[str, Any],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> MutationResult:
        graph = await self.create_graph(
            submitted,
            authorizations=OperationAuthorizationSet(
                root=self._require_authorization(authorization, "create")
            ),
        )
        assert graph.record is not None
        return MutationResult(identity=graph.identity, record=graph.record)

    async def create_graph(
        self,
        submitted: Mapping[str, Any],
        *,
        relationship_changes: tuple[RelationshipChangePlan, ...] = (),
        authorizations: OperationAuthorizationSet | None = None,
        idempotency_token: str | None = None,
    ) -> GraphMutationResult:
        if authorizations is None:
            raise _forbidden("Graph mutation requires explicit authorization capabilities.")
        self._require_graph_authorizations(
            authorizations,
            operation="create",
            identity=None,
            changes=relationship_changes,
        )
        prepared = self._prepare(submitted)
        reservation = await self._claim_graph_idempotency(
            "create", None, prepared.values, relationship_changes, idempotency_token
        )
        if reservation is not None and reservation.status is IdempotencyStatus.COMPLETED:
            return await self._graph_replay(reservation.completed_receipt)
        context = current_operation_context()
        assert context is not None
        try:
            async with SQLAlchemyCoreUnitOfWork(
                self._engine,
                policy=TransactionPolicy.AUTO,
                event_publisher=context.events,
                operation_context=context,
            ) as uow:
                created = await self._execute_scalar_in_uow(
                    uow, GeneratedCrudRequest.create(prepared)
                )
                relationship_results: list[object] = []
                for change in relationship_changes:
                    assert self._relationship_service is not None
                    relationship_results.append(
                        await self._relationship_service.execute_in_uow(
                            uow,
                            parent_identity=created.identity,
                            change=change,
                            new_parent=True,
                        )
                    )
                await uow.mark_success()
            result = GraphMutationResult(
                identity=created.identity,
                record=created.record,
                relationship_results=tuple(relationship_results),
            )
        except BaseException:
            await self._release_graph_reservation(reservation)
            raise
        await self._complete_graph_reservation(reservation, result)
        return result

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, Any],
        *,
        concurrency_token: str | None = None,
        authorization: MutationAuthorization | None = None,
        force_overwrite: bool = False,
        force_overwrite_confirmation: str | None = None,
    ) -> MutationResult:
        if force_overwrite or force_overwrite_confirmation is not None:
            raise _config(
                "core_force_overwrite_unsupported",
                "SQLAlchemy Core public writes do not support force overwrite.",
            )
        graph = await self.update_graph(
            identity,
            submitted,
            concurrency_token=concurrency_token,
            authorizations=OperationAuthorizationSet(
                root=self._require_authorization(authorization, "update")
            ),
        )
        assert graph.record is not None
        return MutationResult(identity=identity, record=graph.record)

    async def update_graph(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, Any],
        *,
        relationship_changes: tuple[RelationshipChangePlan, ...] = (),
        concurrency_token: str | None = None,
        authorizations: OperationAuthorizationSet | None = None,
        idempotency_token: str | None = None,
    ) -> GraphMutationResult:
        if authorizations is None:
            raise _forbidden("Graph mutation requires explicit authorization capabilities.")
        self._require_graph_authorizations(
            authorizations,
            operation="update",
            identity=identity,
            changes=relationship_changes,
        )
        prepared = self._prepare(submitted)
        if relationship_changes and self._concurrency_provider is None:
            raise _config(
                "core_graph_parent_concurrency_required",
                "Graph relationship mutation requires parent concurrency.",
            )
        reservation = await self._claim_graph_idempotency(
            "update", identity, prepared.values, relationship_changes, idempotency_token
        )
        if reservation is not None and reservation.status is IdempotencyStatus.COMPLETED:
            return await self._graph_replay(reservation.completed_receipt)
        context = current_operation_context()
        assert context is not None
        try:
            async with SQLAlchemyCoreUnitOfWork(
                self._engine,
                policy=TransactionPolicy.AUTO,
                event_publisher=context.events,
                operation_context=context,
            ) as uow:
                current = await self._record_in_uow(uow, identity)
                if current is None:
                    raise RakitError(
                        code=ErrorCode.RESOURCE_NOT_FOUND,
                        message="Resource was not found",
                        status_code=404,
                    )
                expected_version = (
                    self._concurrency_provider.version_for(current)
                    if self._concurrency_provider is not None
                    else None
                )
                if relationship_changes:
                    assert self._relationship_service is not None
                    assert expected_version is not None
                    for change in relationship_changes:
                        await self._relationship_service.validate_parent_proof_in_uow(
                            uow,
                            parent_identity=identity,
                            change=change,
                            expected_parent_version=expected_version,
                        )
                updated = await self._execute_scalar_in_uow(
                    uow,
                    GeneratedCrudRequest.update_partial(
                        identity,
                        prepared,
                        concurrency_token=concurrency_token,
                    ),
                )
                relationship_results: list[object] = []
                for change in relationship_changes:
                    assert self._relationship_service is not None
                    relationship_results.append(
                        await self._relationship_service.execute_in_uow(
                            uow,
                            parent_identity=identity,
                            change=change,
                            parent_claimed=True,
                        )
                    )
                record = await self._record_in_uow(uow, identity)
                await uow.mark_success()
            result = GraphMutationResult(
                identity=updated.identity,
                record=record,
                relationship_results=tuple(relationship_results),
            )
        except BaseException:
            await self._release_graph_reservation(reservation)
            raise
        await self._complete_graph_reservation(reservation, result)
        return result

    async def delete(
        self,
        token: str,
        *,
        identity: RecordIdentity,
        authorization: MutationAuthorization | None = None,
    ) -> None:
        self._require_authorization(authorization, "delete")
        try:
            claims = self._token_service.verify(token, expected_purpose=self._delete_purpose())
        except ValueError as exc:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Delete confirmation is invalid.",
                status_code=409,
                cause=exc,
            ) from exc
        if claims.get("identity") != canonical_identity_payload(identity):
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Delete confirmation does not match this resource.",
                status_code=409,
            )
        record = await self.get(identity)
        if record is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="Resource was not found",
                status_code=404,
            )
        concurrency_token = None
        if self._concurrency is not None and self._concurrency_provider is not None:
            expected = self._concurrency_provider.version_for(record)
            if claims.get("version") != expected:
                raise RakitError(
                    code=ErrorCode.RESOURCE_CONFLICT,
                    message="Resource changed before deletion.",
                    status_code=409,
                )
            concurrency_token = self._concurrency.issue(self._resource_id, identity, expected)
        context = current_operation_context()
        assert context is not None
        async with SQLAlchemyCoreUnitOfWork(
            self._engine,
            policy=TransactionPolicy.AUTO,
            event_publisher=context.events,
            operation_context=context,
        ) as uow:
            await self._execute_scalar_in_uow(
                uow,
                GeneratedCrudRequest.delete(identity, concurrency_token=concurrency_token),
            )
            await uow.mark_success()

    async def _claim_graph_idempotency(
        self,
        operation: str,
        identity: RecordIdentity | None,
        values: Mapping[str, object],
        changes: tuple[RelationshipChangePlan, ...],
        token: str | None,
    ):
        if not changes:
            return None
        store = self._graph_idempotency_store
        if store is None or not token:
            raise _config(
                "core_graph_idempotency_required",
                "Graph relationship mutation requires durable idempotency.",
            )
        payload = {
            "resource_id": self._resource_id,
            "operation": operation,
            "identity": canonical_identity_payload(identity) if identity is not None else None,
            "values": dict(sorted(values.items())),
            "changes": [change.fingerprint_payload for change in changes],
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        try:
            reservation = await store.begin(
                hashlib.sha256(token.encode()).hexdigest(), fingerprint=fingerprint
            )
        except ValueError as exc:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Graph submission token is bound to another mutation.",
                status_code=409,
                cause=exc,
            ) from exc
        if reservation.status is IdempotencyStatus.COMPLETED:
            return reservation
        if not reservation.claimed:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Graph submission is already in progress or final.",
                status_code=409,
            )
        return reservation

    async def _release_graph_reservation(self, reservation: object | None) -> None:
        if reservation is not None and self._graph_idempotency_store is not None:
            await self._graph_idempotency_store.release(cast(Any, reservation))

    async def _complete_graph_reservation(
        self, reservation: object | None, result: GraphMutationResult
    ) -> None:
        if reservation is None or self._graph_idempotency_store is None:
            return
        await self._graph_idempotency_store.complete(
            cast(Any, reservation),
            OperationReceipt(
                operation_id=hashlib.sha256(
                    json.dumps(canonical_identity_payload(result.identity), sort_keys=True).encode()
                ).hexdigest(),
                status="succeeded",
                result_kind="core_graph_mutation",
                payload={"identity": canonical_identity_payload(result.identity)},
            ),
        )

    async def _graph_replay(self, receipt: OperationReceipt | None) -> GraphMutationResult:
        if receipt is None or receipt.result_kind != "core_graph_mutation" or receipt.payload is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Completed graph submission has no valid receipt.",
                status_code=409,
            )
        raw_identity = receipt.payload.get("identity")
        if not isinstance(raw_identity, Mapping):
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Completed graph submission has no valid identity.",
                status_code=409,
            )
        values = raw_identity.get("values")
        if not isinstance(values, Mapping):
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Completed graph submission has no valid identity.",
                status_code=409,
            )
        identity = RecordIdentity(values=dict(values))
        record = await self.get(identity)
        if record is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Completed graph submission record is unavailable.",
                status_code=409,
            )
        return GraphMutationResult(identity=identity, record=record, replayed=True)


class SQLAlchemyCoreWriteServiceProvider(ResourceWriteServiceProvider):
    def __init__(
        self,
        *,
        data_source: SQLAlchemyCoreDataSource,
        engine: AsyncEngine,
    ) -> None:
        self._data_source = data_source
        self._engine = engine

    def build(self, context: ResourceWriteServiceContext) -> SQLAlchemyCoreMutationService:
        known_fields = set(self._data_source.fields)
        if not set(context.definition.writable_fields) <= known_fields:
            raise _config(
                "core_write_field_unknown",
                "SQLAlchemy Core write policy references an unknown table field.",
            )
        version_field = context.definition.version_field
        if version_field is not None and version_field not in known_fields:
            raise _config(
                "core_write_version_field_unknown",
                "SQLAlchemy Core write policy references an unknown version field.",
            )
        return SQLAlchemyCoreMutationService(
            resource_id=context.resource_id,
            data_source=self._data_source,
            engine=self._engine,
            form_schema=context.definition.form_schema,
            writable_fields=context.definition.writable_fields,
            token_service=context.token_service,
            version_field=version_field,
        )


__all__ = ["SQLAlchemyCoreMutationService", "SQLAlchemyCoreWriteServiceProvider"]
