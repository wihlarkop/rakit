"""Admin composition helpers for compiled Plan 05 custom pages."""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager

from rakit_core.actions import ActionDefinition, ActionScope
from rakit_core.auth import Principal
from rakit_core.compiler import ApplicationBuilder, CompiledApplication
from rakit_core.definitions import CompiledPageDefinition, PageDefinition
from rakit_core.di import ServiceResolver
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import IdempotencyStore
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import resolve_operation_executor_capabilities
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from .page_routes import PageBinding, build_page_routes
from .security.validation import validate_idempotency_store_for_production


def register_public_page(
    builder: ApplicationBuilder,
    definition: PageDefinition,
    *,
    actions: tuple[ActionDefinition, ...] = (),
) -> None:
    """Atomically validate and register a Page plus its PAGE-scoped actions."""

    existing_action_ids = {str(action.action_id) for action in builder.actions}
    declared_ids = tuple(str(action.action_id) for action in actions)
    if len(declared_ids) != len(set(declared_ids)) or set(declared_ids) & existing_action_ids:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Invalid page action declaration.",
            status_code=500,
            details={"page_id": str(definition.page_id), "reason": "duplicate_action"},
        )
    for action in actions:
        if action.scope is not ActionScope.PAGE or action.page_id != definition.page_id:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Invalid page action declaration.",
                status_code=500,
                details={
                    "page_id": str(definition.page_id),
                    "action_id": str(action.action_id),
                    "reason": "page_owner_mismatch",
                },
            )
    # All declaration validation happens before mutating the builder so a bad
    # action cannot leave the page half-registered.
    builder.add_page(definition)
    for action in actions:
        builder.add_action(action)


def page_requirement_map(compiled: CompiledApplication) -> dict[str, PermissionRequirement]:
    return {
        compiled_page.definition.path: compiled_page.permission
        for compiled_page in compiled.compiled_pages
    }


def validate_page_runtime(
    compiled: CompiledApplication,
    *,
    auth_enabled: bool,
    idempotency_store: IdempotencyStore | None,
    uow_factory_registered: bool,
    debug: bool,
) -> None:
    if not compiled.compiled_pages:
        return
    if not auth_enabled:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message="Compiled pages require configured authentication.",
            status_code=500,
        )

    mutating_pages = tuple(item for item in compiled.compiled_pages if item.definition.mutating)
    if mutating_pages and idempotency_store is None:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message=(
                "Mutating pages require an operation idempotency store "
                "(Admin(operation_idempotency_store=...))."
            ),
            status_code=500,
        )
    if idempotency_store is not None and mutating_pages:
        validate_idempotency_store_for_production(idempotency_store, debug=debug)

    for compiled_page in mutating_pages:
        page = compiled_page.definition
        capabilities = resolve_operation_executor_capabilities(page.handler)
        if page.transaction_policy in (TransactionPolicy.AUTO, TransactionPolicy.MANUAL):
            if not capabilities.participates_in_uow:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message=(
                        f'Page "{page.page_id}" declares {page.transaction_policy.value} '
                        "transaction policy but its handler does not participate in the "
                        "operation unit of work."
                    ),
                    status_code=500,
                    details={
                        "page_id": str(page.page_id),
                        "transaction_policy": str(page.transaction_policy),
                        "reason": "handler_not_uow_managed",
                    },
                )
            if not uow_factory_registered:
                raise RakitError(
                    code=ErrorCode.CONFIG_INVALID,
                    message=(
                        f'Page "{page.page_id}" requires a registered operation '
                        "unit-of-work provider."
                    ),
                    status_code=500,
                    details={
                        "page_id": str(page.page_id),
                        "transaction_policy": str(page.transaction_policy),
                        "reason": "operation_uow_not_configured",
                    },
                )


def build_admin_page_routes(
    *,
    compiled: CompiledApplication,
    templates: Jinja2Templates,
    admin_id: str,
    superuser_bypass: bool,
    verify_csrf: Callable[[Request], Awaitable[bool]],
    verify_submission_token: Callable[[Request], Awaitable[bool]],
    issue_submission_token: Callable[[Request], str],
    idempotency_store: IdempotencyStore | None,
    deadline_seconds: float,
    operation_scope: Callable[[], AbstractAsyncContextManager[ServiceResolver]],
    unit_of_work_factory: Callable[[], OperationUnitOfWorkFactory | None],
    label: str,
) -> list[Route]:
    if not compiled.compiled_pages:
        return []

    async def authorize_page(
        request: Request,
        compiled_page: CompiledPageDefinition,
    ) -> OperationAuthorization | None:
        state = request.scope.get("state", {})
        principal = state.get("principal") if isinstance(state, Mapping) else None
        if not isinstance(principal, Principal) or not principal.authenticated:
            return None
        if not compiled_page.permission.matches(principal, superuser_bypass=superuser_bypass):
            return None
        if principal.subject_id is None:
            return None
        page = compiled_page.definition
        return OperationAuthorization.for_requirement(
            admin_id=admin_id,
            resource_id=str(page.page_id),
            operation=f"page:{page.page_id}",
            principal_id=principal.subject_id,
            requirement=compiled_page.permission,
        )

    route_by_name = {route.route_name: route for route in compiled.routes}
    pairs = tuple(
        (route_by_name[f"page:{compiled_page.definition.page_id}"], compiled_page)
        for compiled_page in compiled.compiled_pages
    )
    binding = PageBinding(
        routes=pairs,
        templates=templates,
        authorize_page=authorize_page,
        verify_csrf=verify_csrf,
        verify_submission_token=verify_submission_token,
        issue_submission_token=issue_submission_token,
        idempotency_store=idempotency_store,
        deadline_seconds=deadline_seconds,
        operation_scope=operation_scope,
        unit_of_work_factory=unit_of_work_factory,
        label=label,
    )
    return build_page_routes(binding)


__all__ = [
    "build_admin_page_routes",
    "page_requirement_map",
    "register_public_page",
    "validate_page_runtime",
]
