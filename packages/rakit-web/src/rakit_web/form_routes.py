"""Secure, explicit resource write routes.

The binding deliberately receives a compiled ``FormSchema`` and a narrow
mutation service rather than an ORM model.  HTTP concerns (CSRF, identity
decoding, duplicate form fields, redirects) stay here; writable-field and
optimistic-write invariants remain in the datasource service.
"""

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast

from rakit_core.errors import RakitError
from rakit_core.forms import FormSchema, FormValidationError
from rakit_core.idempotency import (
    IdempotencyReservation,
    IdempotencyStatus,
    IdempotencyStore,
    OperationReceipt,
)
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
    new_operation_id,
    run_with_deadline,
)
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .results import mutation_success
from .security.cookies import CSRF_COOKIE_NAME


class CreateMutationService(Protocol):
    async def create(
        self,
        submitted: dict[str, object],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> object: ...


class WriteMutationService(CreateMutationService, Protocol):
    async def get(self, identity: RecordIdentity) -> object | None: ...

    def issue_update_token(self, record: object) -> str: ...

    async def update(
        self,
        identity: RecordIdentity,
        submitted: Mapping[str, object],
        *,
        concurrency_token: str | None,
        authorization: MutationAuthorization | None = None,
    ) -> object: ...

    async def issue_delete_token(self, identity: RecordIdentity) -> str: ...

    async def delete(
        self,
        confirmation_token: str,
        *,
        identity: RecordIdentity,
        authorization: MutationAuthorization | None = None,
    ) -> None: ...


Verifier = Callable[[Request], Awaitable[bool]]
SubmissionTokenIssuer = Callable[[Request], str]
MutationAuthorizer = Callable[
    [Request, MutationOperation, RecordIdentity | None], Awaitable[MutationAuthorization | None]
]


@dataclass(frozen=True)
class WriteResourceBinding:
    path: str
    label: str
    form_schema: FormSchema
    mutation_service: CreateMutationService
    templates: Jinja2Templates
    authorize: Verifier
    verify_csrf: Verifier
    verify_submission_token: Verifier
    issue_submission_token: SubmissionTokenIssuer
    resource_id: str | None = None
    deadline_seconds: float | None = None
    idempotency_store: IdempotencyStore | None = None
    mutation_authorizer: MutationAuthorizer | None = None
    codec: IdentityCodec = field(default_factory=IdentityCodec)

    @property
    def _route_resource_id(self) -> str:
        return self.resource_id or self.path

    @property
    def create_path(self) -> str:
        return f"{self.path}/new"

    @property
    def update_path(self) -> str:
        return f"{self.path}/{{identity}}/edit"

    @property
    def delete_path(self) -> str:
        return f"{self.path}/{{identity}}/delete"


async def _parse_form(
    request: Request, schema: FormSchema
) -> tuple[dict[str, object], dict[str, str]] | None:
    try:
        form = await request.form(max_files=0, max_fields=len(schema.fields) + 4)
    except HTTPException:
        return None
    items = form.multi_items()
    names = [name for name, _ in items]
    if len(names) != len(set(names)):
        return None
    reserved = {"csrf_token", "submission_token", "concurrency_token", "delete_token"}
    values: dict[str, object] = {}
    for name, value in items:
        if name not in reserved:
            if not isinstance(value, str):
                return None
            values[name] = value
    tokens = {name: value for name, value in items if name in reserved and isinstance(value, str)}
    return values, tokens


def _record_values(binding: WriteResourceBinding, record: object) -> dict[str, object]:
    return {
        field.field_id: getattr(record, field.field_id, "")
        for field in binding.form_schema.fields
        if field.writable
    }


def _form_response(
    binding: WriteResourceBinding,
    request: Request,
    *,
    title: str,
    action_path: str,
    submitted: Mapping[str, object] | None = None,
    issues: tuple[object, ...] = (),
    concurrency_token: str | None = None,
    status_code: int = 200,
) -> Response:
    return binding.templates.TemplateResponse(
        request,
        "forms/form.html",
        {
            "title": title,
            "label": binding.label,
            "fields": tuple(field for field in binding.form_schema.fields if field.writable),
            "submitted": submitted or {},
            "issues": issues,
            "action_url": mounted_path(request, action_path),
            "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
            "submission_token": binding.issue_submission_token(request),
            "concurrency_token": concurrency_token,
        },
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _error(status_code: int, message: str) -> PlainTextResponse:
    return PlainTextResponse(
        message, status_code=status_code, headers={"Cache-Control": "no-store"}
    )


def _identity(binding: WriteResourceBinding, encoded: str) -> RecordIdentity | None:
    try:
        return binding.codec.decode(encoded)
    except ValueError:
        return None


def _write_routes_available(binding: WriteResourceBinding) -> bool:
    service = binding.mutation_service
    return all(
        callable(getattr(service, name, None))
        for name in ("get", "issue_update_token", "update", "issue_delete_token", "delete")
    )


async def _execute_with_deadline(
    binding: WriteResourceBinding,
    awaitable: Awaitable[object],
    authorization: MutationAuthorization,
) -> object:
    if binding.deadline_seconds is None:
        return await awaitable
    deadline = Deadline.after(binding.deadline_seconds)
    context = OperationContext(
        deadline=deadline,
        cancellation=CancellationContext(),
        operation_id=new_operation_id(),
        principal_id=authorization.principal_id,
        admin_id=authorization.admin_id,
        resource_id=authorization.resource_id,
        operation=authorization.operation,
        permissions=authorization.permissions,
    )
    with activate_operation_context(context):
        return await run_with_deadline(awaitable, deadline)


async def _claim_submission(
    binding: WriteResourceBinding,
    request: Request,
    *,
    submitted: Mapping[str, object],
    tokens: Mapping[str, str],
    operation: str,
    identity: RecordIdentity | None = None,
) -> tuple[IdempotencyReservation | None, Response | None]:
    """Atomically claim a verified submission token for one canonical operation."""
    if binding.idempotency_store is None:
        return None, None
    token = tokens.get("submission_token")
    if not token:
        return None, _error(409, "Invalid submission token")
    payload = {
        "operation": operation,
        "path": binding.path,
        "identity": dict(identity.values) if identity is not None else None,
        "values": dict(sorted(submitted.items())),
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    reservation = await binding.idempotency_store.begin(
        hashlib.sha256(token.encode()).hexdigest(), fingerprint=fingerprint
    )
    if reservation.status is IdempotencyStatus.COMPLETED:
        return reservation, mutation_success(request, location=mounted_path(request, binding.path))
    if not reservation.claimed:
        return reservation, _error(409, "Submission is already in progress")
    return reservation, None


async def _authorization(
    binding: WriteResourceBinding,
    request: Request,
    operation: MutationOperation,
    identity: RecordIdentity | None,
) -> MutationAuthorization | None:
    if binding.mutation_authorizer is None:
        return None
    return await binding.mutation_authorizer(request, operation, identity)


def build_write_routes(binding: WriteResourceBinding) -> list[Route]:
    async def create_get(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        return _form_response(
            binding, request, title=f"New {binding.label}", action_path=binding.create_path
        )

    async def create_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        authorization = await _authorization(binding, request, "create", None)
        if authorization is None:
            return _error(403, "Forbidden")
        if not await binding.verify_csrf(request):
            return _error(403, "Invalid CSRF token")
        if not await binding.verify_submission_token(request):
            return _error(409, "Invalid submission token")
        parsed = await _parse_form(request, binding.form_schema)
        if parsed is None:
            return _error(400, "Invalid form")
        submitted, tokens = parsed
        try:
            binding.form_schema.parse(submitted)
            reservation, replay = await _claim_submission(
                binding, request, submitted=submitted, tokens=tokens, operation="create"
            )
            if replay is not None:
                return replay
            await _execute_with_deadline(
                binding,
                binding.mutation_service.create(submitted, authorization=authorization),
                authorization,
            )
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.complete(
                    reservation,
                    OperationReceipt(
                        operation_id=str(uuid.uuid4()),
                        status="succeeded",
                        result_kind="redirect",
                        redirect_route=binding.path,
                    ),
                )
        except FormValidationError as exc:
            return _form_response(
                binding,
                request,
                title=f"New {binding.label}",
                action_path=binding.create_path,
                submitted=submitted,
                issues=exc.state.issues,
                status_code=422,
            )
        except RakitError as exc:
            if (
                "reservation" in locals()
                and reservation is not None
                and binding.idempotency_store is not None
            ):
                await binding.idempotency_store.release(reservation)
            return _error(exc.status_code, "Invalid form")
        except ValueError:
            if (
                "reservation" in locals()
                and reservation is not None
                and binding.idempotency_store is not None
            ):
                await binding.idempotency_store.release(reservation)
            return _error(400, "Invalid form")
        return mutation_success(request, location=mounted_path(request, binding.path))

    routes = [
        Route(
            binding.create_path,
            create_get,
            methods=["GET"],
            name=f"resource:{binding._route_resource_id}:create",
        ),
        Route(
            binding.create_path,
            create_post,
            methods=["POST"],
            name=f"resource:{binding._route_resource_id}:create.submit",
        ),
    ]
    if not _write_routes_available(binding):
        return routes
    mutation_service = cast(WriteMutationService, binding.mutation_service)

    async def update_get(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        record = await mutation_service.get(identity)
        if record is None:
            return _error(404, "Resource was not found")
        return _form_response(
            binding,
            request,
            title=f"Edit {binding.label}",
            action_path=f"{binding.path}/{request.path_params['identity']}/edit",
            submitted=_record_values(binding, record),
            concurrency_token=mutation_service.issue_update_token(record),
        )

    async def update_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        authorization = await _authorization(binding, request, "update", identity)
        if authorization is None:
            return _error(403, "Forbidden")
        if not await binding.verify_csrf(request):
            return _error(403, "Invalid CSRF token")
        if not await binding.verify_submission_token(request):
            return _error(409, "Invalid submission token")
        parsed = await _parse_form(request, binding.form_schema)
        if parsed is None:
            return _error(400, "Invalid form")
        submitted, tokens = parsed
        try:
            binding.form_schema.parse(submitted)
            reservation, replay = await _claim_submission(
                binding,
                request,
                submitted=submitted,
                tokens=tokens,
                operation="update",
                identity=identity,
            )
            if replay is not None:
                return replay
            await _execute_with_deadline(
                binding,
                mutation_service.update(
                    identity,
                    submitted,
                    concurrency_token=tokens.get("concurrency_token"),
                    authorization=authorization,
                ),
                authorization,
            )
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.complete(
                    reservation,
                    OperationReceipt(
                        operation_id=str(uuid.uuid4()),
                        status="succeeded",
                        result_kind="redirect",
                        redirect_route=binding.path,
                    ),
                )
        except FormValidationError as exc:
            return _form_response(
                binding,
                request,
                title=f"Edit {binding.label}",
                action_path=f"{binding.path}/{request.path_params['identity']}/edit",
                submitted=submitted,
                issues=exc.state.issues,
                concurrency_token=tokens.get("concurrency_token"),
                status_code=422,
            )
        except RakitError as exc:
            if (
                "reservation" in locals()
                and reservation is not None
                and binding.idempotency_store is not None
            ):
                await binding.idempotency_store.release(reservation)
            return _error(exc.status_code, "Mutation rejected")
        except ValueError:
            if (
                "reservation" in locals()
                and reservation is not None
                and binding.idempotency_store is not None
            ):
                await binding.idempotency_store.release(reservation)
            return _error(400, "Invalid form")
        return mutation_success(request, location=mounted_path(request, binding.path))

    async def delete_get(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        try:
            token = await mutation_service.issue_delete_token(identity)
        except RakitError as exc:
            return _error(exc.status_code, "Resource was not found")
        return binding.templates.TemplateResponse(
            request,
            "forms/delete_confirm.html",
            {
                "action_url": mounted_path(
                    request, f"{binding.path}/{request.path_params['identity']}/delete"
                ),
                "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
                "delete_token": token,
                "submission_token": binding.issue_submission_token(request),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def delete_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return _error(403, "Forbidden")
        identity = _identity(binding, request.path_params["identity"])
        if identity is None:
            return _error(400, "Invalid resource identity")
        authorization = await _authorization(binding, request, "delete", identity)
        if authorization is None:
            return _error(403, "Forbidden")
        if not await binding.verify_csrf(request):
            return _error(403, "Invalid CSRF token")
        if not await binding.verify_submission_token(request):
            return _error(409, "Invalid submission token")
        parsed = await _parse_form(request, binding.form_schema)
        if parsed is None:
            return _error(400, "Invalid form")
        submitted, tokens = parsed
        token = tokens.get("delete_token")
        if not token:
            return _error(400, "Invalid delete confirmation")
        try:
            reservation, replay = await _claim_submission(
                binding,
                request,
                submitted=submitted,
                tokens=tokens,
                operation="delete",
                identity=identity,
            )
            if replay is not None:
                return replay
            await _execute_with_deadline(
                binding,
                mutation_service.delete(token, identity=identity, authorization=authorization),
                authorization,
            )
            if reservation is not None and binding.idempotency_store is not None:
                await binding.idempotency_store.complete(
                    reservation,
                    OperationReceipt(
                        operation_id=str(uuid.uuid4()),
                        status="succeeded",
                        result_kind="redirect",
                        redirect_route=binding.path,
                    ),
                )
        except RakitError as exc:
            if (
                "reservation" in locals()
                and reservation is not None
                and binding.idempotency_store is not None
            ):
                await binding.idempotency_store.release(reservation)
            return _error(exc.status_code, "Delete rejected")
        return mutation_success(request, location=mounted_path(request, binding.path))

    routes.extend(
        (
            Route(
                binding.update_path,
                update_get,
                methods=["GET"],
                name=f"resource:{binding._route_resource_id}:edit",
            ),
            Route(
                binding.update_path,
                update_post,
                methods=["POST"],
                name=f"resource:{binding._route_resource_id}:edit.submit",
            ),
            Route(
                binding.delete_path,
                delete_get,
                methods=["GET"],
                name=f"resource:{binding._route_resource_id}:delete",
            ),
            Route(
                binding.delete_path,
                delete_post,
                methods=["POST"],
                name=f"resource:{binding._route_resource_id}:delete.submit",
            ),
        )
    )
    return routes
