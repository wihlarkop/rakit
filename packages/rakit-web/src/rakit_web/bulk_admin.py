"""Admin composition adapter for built-in and custom BULK operations."""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from http import HTTPStatus
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
from rakit_core.permissions import PermissionRequirement
from rakit_core.resources import ResourceService
from rakit_core.transactions import OperationUnitOfWorkFactory
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .action_presentation import action_web_presentation
from .bulk_delete import BuiltInBulkDeleteBinding, build_builtin_bulk_delete_routes
from .bulk_review import build_mature_bulk_action_routes
from .bulk_routes import BulkActionBinding
from .form_routes import WriteResourceBinding


def build_admin_bulk_action_routes(
    *,
    compiled: CompiledApplication,
    resource_services: Mapping[str, ResourceService],
    write_resource_bindings: Mapping[str, WriteResourceBinding] | None = None,
    concurrency_providers: Mapping[str, ConcurrencyVersionProvider],
    templates: Jinja2Templates,
    verify_csrf: Callable[[Request], Awaitable[bool]],
    verify_submission_token: Callable[[Request], Awaitable[bool]],
    issue_submission_token: Callable[[Request], str],
    token_service: TokenService,
    idempotency_store: IdempotencyStore | None,
    admin_id: str,
    superuser_bypass: bool,
    deadline_seconds: float,
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]],
    unit_of_work_factory_for_resource: Callable[[str], OperationUnitOfWorkFactory | None],
    label: str,
) -> list[Route]:
    """Materialize framework bulk delete plus compiled custom BULK actions."""

    routes: list[Route] = []
    write_bindings = write_resource_bindings or {}

    def bulk_action_views(request: Request, resource_id: str) -> tuple[dict[str, str], ...]:
        principal = request.scope.get("state", {}).get("principal")
        if principal is None or not principal.authenticated:
            return ()

        views: list[dict[str, str]] = []
        write_binding = write_bindings.get(resource_id)
        if write_binding is not None and write_binding.has_record_write_routes:
            delete_requirement = PermissionRequirement.all_of(
                f"{admin_id}.resources.{resource_id}.delete"
            )
            if delete_requirement.matches(principal, superuser_bypass=superuser_bypass):
                views.append(
                    {
                        "label": "Delete selected",
                        "url": mounted_path(request, f"{write_binding.path}/_bulk/delete-selected"),
                        "intent": "danger",
                        "builtin": "delete",
                    }
                )

        views.extend(
            {
                "label": str(compiled_action.definition.label),
                "url": mounted_path(request, route.path),
                "intent": action_web_presentation(compiled_action.definition).intent.value,
                "builtin": "",
            }
            for route, compiled_action in compiled.action_routes
            if compiled_action.definition.scope is ActionScope.BULK
            and compiled_action.definition.resource_id == resource_id
            and compiled_action.permission.matches(principal, superuser_bypass=superuser_bypass)
        )
        return tuple(views)

    # Resource/action templates are shared across bindings. These helpers are
    # Web-only and filter exact permissions before exposing launchers.
    template_globals = cast(dict[str, Any], templates.env.globals)
    template_globals["rakit_bulk_actions"] = bulk_action_views
    template_globals["rakit_action_web_presentation"] = action_web_presentation

    # Built-in bulk delete exists independently from ActionDefinition. It is
    # simply the resource DELETE capability applied to a selected set.
    for resource_id, write_binding in write_bindings.items():
        if not write_binding.has_record_write_routes:
            continue
        service = resource_services.get(resource_id)
        if service is None:
            continue
        routes.extend(
            build_builtin_bulk_delete_routes(
                BuiltInBulkDeleteBinding(
                    write=write_binding,
                    identity_fields=service.data_source.identity_fields,
                    templates=templates,
                    token_service=token_service,
                    label=label,
                )
            )
        )

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
        if idempotency_store is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Custom bulk actions require an operation idempotency store.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
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
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
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
            unit_of_work_factory=(
                lambda resource_id=resource_id: unit_of_work_factory_for_resource(resource_id)
            ),
            label=label,
        )
        routes.extend(build_mature_bulk_action_routes(binding))
    return routes


__all__ = ["build_admin_bulk_action_routes"]
