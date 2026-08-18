"""Admin composition adapter for compiled BULK action routes."""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

from rakit_core.actions import ActionScope
from rakit_core.compiler import CompiledApplication
from rakit_core.concurrency import ConcurrencyTokenService, ConcurrencyVersionProvider
from rakit_core.crypto import TokenService
from rakit_core.definitions import CompiledActionDefinition
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import IdempotencyStore
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.resources import ResourceService
from rakit_core.transactions import OperationUnitOfWorkFactory
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .action_presentation import action_web_presentation
from .bulk_routes import BulkActionBinding, build_bulk_action_routes


def build_admin_bulk_action_routes(
    *,
    compiled: CompiledApplication,
    resource_services: Mapping[str, ResourceService],
    concurrency_providers: Mapping[str, ConcurrencyVersionProvider],
    templates: Jinja2Templates,
    verify_csrf: Callable[[Request], Awaitable[bool]],
    verify_submission_token: Callable[[Request], Awaitable[bool]],
    issue_submission_token: Callable[[Request], str],
    token_service: TokenService,
    idempotency_store: IdempotencyStore,
    admin_id: str,
    superuser_bypass: bool,
    deadline_seconds: float,
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]],
    unit_of_work_factory: Callable[[], OperationUnitOfWorkFactory | None],
    label: str,
) -> list[Route]:
    """Materialize BULK bindings and list controls from the same compiled graph."""

    routes: list[Route] = []

    def bulk_action_views(request: Request, resource_id: str) -> tuple[dict[str, str], ...]:
        principal = request.scope.get("state", {}).get("principal")
        if principal is None or not principal.authenticated:
            return ()
        return tuple(
            {
                "label": str(compiled_action.definition.label),
                "url": mounted_path(request, route.path),
                "intent": action_web_presentation(compiled_action.definition).intent.value,
            }
            for route, compiled_action in compiled.action_routes
            if compiled_action.definition.scope is ActionScope.BULK
            and compiled_action.definition.resource_id == resource_id
            and compiled_action.permission.matches(
                principal,
                superuser_bypass=superuser_bypass,
            )
        )

    # Resource list templates are shared across bindings. The helper filters
    # per request, so action labels/URLs are not exposed to principals that do
    # not satisfy the exact compiler-resolved permission.
    cast(dict[str, Any], templates.env.globals)["rakit_bulk_actions"] = bulk_action_views

    async def authorize_action(
        request: Request,
        compiled_action: CompiledActionDefinition,
        identity: RecordIdentity | None,
    ) -> OperationAuthorization | None:
        principal = request.scope.get("state", {}).get("principal")
        if principal is None or not principal.authenticated:
            return None
        if not compiled_action.permission.matches(principal, superuser_bypass=superuser_bypass):
            return None
        if principal.subject_id is None:
            return None
        resource_id = compiled_action.definition.resource_id
        assert resource_id is not None
        return OperationAuthorization.for_requirement(
            admin_id=admin_id,
            resource_id=resource_id,
            operation=f"action:{compiled_action.definition.action_id}",
            principal_id=principal.subject_id,
            requirement=compiled_action.permission,
            target_identity=identity,
        )

    for resource_id, service in resource_services.items():
        pairs = tuple(
            (route, action)
            for route, action in compiled.action_routes
            if action.definition.scope is ActionScope.BULK
            and action.definition.resource_id == resource_id
        )
        if not pairs:
            continue
        provider = concurrency_providers.get(resource_id)
        missing_snapshot_provider = tuple(
            str(compiled_action.definition.action_id)
            for _, compiled_action in pairs
            if compiled_action.definition.bulk_policy is not None
            and compiled_action.definition.bulk_policy.require_concurrency_snapshot
            and provider is None
        )
        if missing_snapshot_provider:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message=(
                    f'Resource "{resource_id}" BULK actions require a registered '
                    "concurrency provider: " + ", ".join(missing_snapshot_provider)
                ),
                status_code=500,
                details={
                    "resource_id": resource_id,
                    "actions": missing_snapshot_provider,
                    "reason": "bulk_concurrency_provider_missing",
                },
            )

        async def load_record(
            identity: RecordIdentity,
            service: ResourceService = service,
        ) -> object | None:
            try:
                return await service.detail(identity)
            except RakitError as exc:
                if exc.code == ErrorCode.RESOURCE_NOT_FOUND.value:
                    return None
                raise

        binding = BulkActionBinding(
            routes=pairs,
            templates=templates,
            codec=IdentityCodec(),
            verify_csrf=verify_csrf,
            verify_submission_token=verify_submission_token,
            issue_submission_token=issue_submission_token,
            authorize_action=authorize_action,
            load_record=load_record,
            token_service=token_service,
            idempotency_store=idempotency_store,
            concurrency=ConcurrencyTokenService(token_service) if provider is not None else None,
            concurrency_resource_id=resource_id if provider is not None else None,
            record_version=provider.version_for if provider is not None else None,
            deadline_seconds=deadline_seconds,
            operation_scope=operation_scope,
            unit_of_work_factory=unit_of_work_factory,
            label=label,
        )
        routes.extend(build_bulk_action_routes(binding))
    return routes


__all__ = ["build_admin_bulk_action_routes"]