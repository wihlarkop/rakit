"""Framework-owned bulk delete for writable resources.

This is deliberately not an ``ActionDefinition``.  It is the multi-record
presentation of the resource's built-in DELETE capability and reuses the same
scoped mutation service, confirmation tokens, lifecycle hooks, and per-record
operation context as ordinary resource deletion.
"""

from __future__ import annotations
from http import HTTPStatus

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.idempotency import IdempotencyStatus, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .form_routes import (
    WriteMutationService,
    WriteResourceBinding,
    _authorization,
    _cleanup_deleted_bound_files,
    _execute_with_deadline,
)
from .results import mutation_success
from .security.cookies import CSRF_COOKIE_NAME

_MAX_SELECTED = 1_000
_CONFIRMATION_TTL = timedelta(minutes=15)
_CONFIRMATION_PURPOSE = "bulk_delete_confirmation"


@dataclass(frozen=True)
class BuiltInBulkDeleteBinding:
    """Runtime dependencies for one resource's framework-owned bulk delete."""

    write: WriteResourceBinding
    identity_fields: tuple[str, ...]
    templates: Jinja2Templates
    token_service: TokenService
    label: str

    @property
    def resource_id(self) -> str:
        if self.write.resource_id is None:
            raise ValueError("Built-in bulk delete requires a bound resource id")
        return self.write.resource_id

    @property
    def path(self) -> str:
        return f"{self.write.path}/_bulk/delete-selected"


@dataclass(frozen=True)
class _DeleteTarget:
    encoded: str
    identity: RecordIdentity
    record: object
    confirmation_token: str


def _dialog_mode(request: Request) -> bool:
    return request.headers.get("X-Rakit-Dialog") == "bulk"


def _session_id(request: Request) -> str:
    value = request.scope.get("state", {}).get("session_id")
    return value if isinstance(value, str) else ""


def _render_feedback(
    binding: BuiltInBulkDeleteBinding,
    request: Request,
    *,
    title: str,
    message: str,
    status_code: int,
    tone: str = "danger",
) -> Response:
    template = (
        "actions/_bulk_feedback_content.html"
        if _dialog_mode(request)
        else "actions/bulk_feedback.html"
    )
    return binding.templates.TemplateResponse(
        request,
        template,
        {
            "binding_label": binding.label,
            "title": title,
            "message": message,
            "tone": tone,
            "cancel_url": mounted_path(request, binding.write.path),
            "dialog_mode": _dialog_mode(request),
        },
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _selection(binding: BuiltInBulkDeleteBinding, values: list[str]) -> tuple[RecordIdentity, ...]:
    if not values:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Select at least one resource before running a bulk action.",
            status_code=HTTPStatus.BAD_REQUEST,
        )
    if len(values) > _MAX_SELECTED:
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message=f"Select at most {_MAX_SELECTED} resources per bulk delete.",
            status_code=HTTPStatus.BAD_REQUEST,
        )
    if len(values) != len(set(values)):
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="The bulk selection contains duplicate resources.",
            status_code=HTTPStatus.BAD_REQUEST,
        )

    identities: list[RecordIdentity] = []
    for encoded in values:
        try:
            identity = binding.write.codec.decode(encoded)
        except ValueError as exc:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="The bulk selection is invalid.",
                status_code=HTTPStatus.BAD_REQUEST,
            ) from exc
        if set(identity.values) != set(binding.identity_fields):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="The bulk selection is invalid.",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        identities.append(identity)
    return tuple(identities)


async def _targets_for_review(
    binding: BuiltInBulkDeleteBinding,
    request: Request,
    encoded: list[str],
) -> tuple[_DeleteTarget, ...]:
    identities = _selection(binding, encoded)
    service = cast(WriteMutationService, binding.write.mutation_service)
    targets: list[_DeleteTarget] = []
    for raw, identity in zip(encoded, identities, strict=True):
        authorization = await _authorization(binding.write, request, "delete", identity)
        if authorization is None:
            raise RakitError(
                code=ErrorCode.AUTH_FORBIDDEN,
                message="Permission denied.",
                status_code=HTTPStatus.FORBIDDEN,
            )
        record = await service.get(identity)
        if record is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="A selected resource was not found.",
                status_code=HTTPStatus.NOT_FOUND,
            )
        targets.append(
            _DeleteTarget(
                encoded=raw,
                identity=identity,
                record=record,
                confirmation_token=await service.issue_delete_token(identity),
            )
        )
    return tuple(targets)


def _token_hashes(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(hashlib.sha256(token.encode()).hexdigest() for token in tokens)


def _issue_batch_confirmation(
    binding: BuiltInBulkDeleteBinding,
    request: Request,
    targets: tuple[_DeleteTarget, ...],
) -> str:
    return binding.token_service.issue_in(
        _CONFIRMATION_PURPOSE,
        {
            "resource_id": binding.resource_id,
            "session_id": _session_id(request),
            "selected": tuple(target.encoded for target in targets),
            "delete_token_hashes": _token_hashes(
                tuple(target.confirmation_token for target in targets)
            ),
        },
        _CONFIRMATION_TTL,
    )


def _single(form: FormData, name: str) -> str | None:
    values = form.getlist(name)
    if len(values) != 1 or not isinstance(values[0], str):
        return None
    return values[0]


def _verify_batch_confirmation(
    binding: BuiltInBulkDeleteBinding,
    request: Request,
    *,
    token: str,
    selected: tuple[str, ...],
    delete_tokens: tuple[str, ...],
) -> bool:
    try:
        claims = binding.token_service.verify(token, expected_purpose=_CONFIRMATION_PURPOSE)
    except ValueError:
        return False
    return bool(
        claims.get("resource_id") == binding.resource_id
        and claims.get("session_id") == _session_id(request)
        and tuple(claims.get("selected", ())) == selected
        and tuple(claims.get("delete_token_hashes", ())) == _token_hashes(delete_tokens)
    )


def _fingerprint(selected: tuple[str, ...], delete_tokens: tuple[str, ...]) -> str:
    payload = {
        "operation": "bulk_delete",
        "selected": selected,
        "delete_token_hashes": _token_hashes(delete_tokens),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_builtin_bulk_delete_routes(binding: BuiltInBulkDeleteBinding) -> list[Route]:
    """Build the GET review and POST execution route for one writable resource."""

    async def endpoint(request: Request) -> Response:
        if not await binding.write.authorize(request):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete unavailable",
                message="Permission denied.",
                status_code=HTTPStatus.FORBIDDEN,
            )

        if request.method == "GET":
            encoded = [value for value in request.query_params.getlist("selected") if value]
            try:
                targets = await _targets_for_review(binding, request, encoded)
            except RakitError as exc:
                return _render_feedback(
                    binding,
                    request,
                    title="Bulk action needs attention",
                    message=exc.message,
                    status_code=exc.status_code,
                )
            template = (
                "actions/_bulk_delete_content.html"
                if _dialog_mode(request)
                else "actions/bulk_delete.html"
            )
            return binding.templates.TemplateResponse(
                request,
                template,
                {
                    "binding_label": binding.label,
                    "resource_label": binding.write.label,
                    "selected_count": len(targets),
                    "selected": tuple(target.encoded for target in targets),
                    "delete_tokens": tuple(target.confirmation_token for target in targets),
                    "confirmation_token": _issue_batch_confirmation(binding, request, targets),
                    "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
                    "submission_token": binding.write.issue_submission_token(request),
                    "form_action": mounted_path(request, binding.path),
                    "cancel_url": mounted_path(request, binding.write.path),
                    "dialog_mode": _dialog_mode(request),
                },
                headers={"Cache-Control": "no-store"},
            )

        # Parse once with the bulk-specific bound before CSRF/submission
        # verifiers read the cached form. This avoids the generic form parser's
        # lower default field limit becoming an accidental bulk limit.
        try:
            form = await request.form(max_files=0, max_fields=(_MAX_SELECTED * 2) + 4)
        except HTTPException:
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid bulk delete submission.",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if not await binding.write.verify_csrf(request):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid CSRF token.",
                status_code=HTTPStatus.FORBIDDEN,
            )
        if not await binding.write.verify_submission_token(request):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid or expired submission token.",
                status_code=HTTPStatus.CONFLICT,
            )

        selected_values = form.getlist("selected")
        delete_values = form.getlist("delete_token")
        if not all(isinstance(value, str) for value in (*selected_values, *delete_values)):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid bulk delete submission.",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        selected = cast(tuple[str, ...], tuple(selected_values))
        delete_tokens = cast(tuple[str, ...], tuple(delete_values))
        confirmation_token = _single(form, "confirmation_token")
        submission_token = _single(form, "submission_token")
        if (
            not confirmation_token
            or not submission_token
            or len(selected) != len(delete_tokens)
            or not _verify_batch_confirmation(
                binding,
                request,
                token=confirmation_token,
                selected=selected,
                delete_tokens=delete_tokens,
            )
        ):
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="Invalid or expired bulk delete confirmation.",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        try:
            identities = _selection(binding, list(selected))
        except RakitError as exc:
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message=exc.message,
                status_code=exc.status_code,
            )

        service = cast(WriteMutationService, binding.write.mutation_service)
        preflight: list[tuple[RecordIdentity, object, MutationAuthorization]] = []
        for identity in identities:
            authorization = await _authorization(binding.write, request, "delete", identity)
            if authorization is None:
                return _render_feedback(
                    binding,
                    request,
                    title="Bulk delete rejected",
                    message="Permission denied.",
                    status_code=HTTPStatus.FORBIDDEN,
                )
            record = await service.get(identity)
            if record is None:
                return _render_feedback(
                    binding,
                    request,
                    title="Bulk delete rejected",
                    message="A selected resource was not found.",
                    status_code=HTTPStatus.NOT_FOUND,
                )
            preflight.append((identity, record, authorization))

        store = binding.write.idempotency_store
        if store is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Built-in bulk delete requires an idempotency store.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        try:
            reservation = await store.begin(
                hashlib.sha256(submission_token.encode()).hexdigest(),
                fingerprint=_fingerprint(selected, delete_tokens),
            )
        except ValueError:
            return _render_feedback(
                binding,
                request,
                title="Bulk delete rejected",
                message="This submission token is bound to another bulk delete.",
                status_code=HTTPStatus.CONFLICT,
            )
        if reservation.status is IdempotencyStatus.COMPLETED:
            receipt = reservation.completed_receipt
            payload = receipt.payload if receipt is not None and receipt.payload is not None else {}
            deleted = int(payload.get("deleted", len(selected)))
            failed = int(payload.get("failed", 0))
            if failed:
                return _render_feedback(
                    binding,
                    request,
                    title="Bulk delete partially completed",
                    message=(
                        f"Deleted {deleted} selected record{'s' if deleted != 1 else ''}; "
                        f"{failed} could not be deleted. Refresh the resource before retrying."
                    ),
                    status_code=HTTPStatus.CONFLICT,
                    tone="warning",
                )
            return mutation_success(
                request,
                location=mounted_path(request, binding.write.path),
                message=f"Deleted {deleted} selected record{'s' if deleted != 1 else ''}.",
            )
        if not reservation.claimed:
            return _render_feedback(
                binding,
                request,
                title="Bulk delete already in progress",
                message="This bulk delete submission is already being processed.",
                status_code=HTTPStatus.CONFLICT,
                tone="warning",
            )

        deleted = 0
        failures: list[str] = []
        try:
            for (identity, record, authorization), delete_token in zip(
                preflight, delete_tokens, strict=True
            ):
                try:
                    await _execute_with_deadline(
                        binding.write,
                        request,
                        service.delete(
                            delete_token,
                            identity=identity,
                            authorization=authorization,
                        ),
                        authorization,
                    )
                    await _cleanup_deleted_bound_files(binding.write, record)
                    deleted += 1
                except (RakitError, ValueError) as exc:
                    failures.append(
                        exc.message if isinstance(exc, RakitError) else "Delete rejected"
                    )
            await store.complete(
                reservation,
                OperationReceipt(
                    operation_id=str(uuid.uuid4()),
                    status="partial" if failures else "succeeded",
                    result_kind="bulk_delete",
                    redirect_route=binding.write.path,
                    payload={"deleted": deleted, "failed": len(failures)},
                ),
            )
        except BaseException:
            if deleted:
                await store.fail_final(reservation)
            else:
                await store.release(reservation)
            raise

        if failures:
            return _render_feedback(
                binding,
                request,
                title="Bulk delete partially completed",
                message=(
                    f"Deleted {deleted} selected record{'s' if deleted != 1 else ''}; "
                    f"{len(failures)} could not be deleted. Refresh the resource before retrying."
                ),
                status_code=HTTPStatus.CONFLICT,
                tone="warning",
            )
        return mutation_success(
            request,
            location=mounted_path(request, binding.write.path),
            message=f"Deleted {deleted} selected record{'s' if deleted != 1 else ''}.",
        )

    return [
        Route(
            binding.path,
            endpoint,
            methods=["GET", "POST"],
            name=f"resource:{binding.resource_id}:bulk.delete",
        )
    ]


__all__ = ["BuiltInBulkDeleteBinding", "build_builtin_bulk_delete_routes"]
