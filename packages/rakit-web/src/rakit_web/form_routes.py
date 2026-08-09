"""Secure create-form routes over an explicitly supplied mutation service."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from rakit_core.forms import FormSchema, FormValidationError
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path
from .results import mutation_success


class CreateMutationService(Protocol):
    async def create(self, submitted: dict[str, object]) -> object: ...


Verifier = Callable[[Request], Awaitable[bool]]
SubmissionTokenIssuer = Callable[[Request], str]


@dataclass(frozen=True)
class WriteResourceBinding:
    path: str
    label: str
    form_schema: FormSchema
    mutation_service: CreateMutationService
    templates: Jinja2Templates
    authorize: Verifier
    verify_csrf: Verifier
    issue_submission_token: SubmissionTokenIssuer

    @property
    def create_path(self) -> str:
        return f"{self.path}/new"


async def _parse_form(request: Request, schema: FormSchema) -> dict[str, object] | None:
    form = await request.form(max_files=0, max_fields=len(schema.fields) + 3)
    items = form.multi_items()
    names = [name for name, _ in items]
    if len(names) != len(set(names)):
        return None
    return {
        name: value
        for name, value in items
        if name not in {"csrf_token", "submission_token", "concurrency_token"}
    }


def _render_form(
    binding: WriteResourceBinding,
    request: Request,
    *,
    submitted: dict[str, object] | None = None,
    issues: tuple[object, ...] = (),
    status_code: int = 200,
) -> Response:
    return binding.templates.TemplateResponse(
        request,
        "forms/form.html",
        {
            "label": binding.label,
            "fields": tuple(field for field in binding.form_schema.fields if field.writable),
            "submitted": submitted or {},
            "issues": issues,
            "action_url": mounted_path(request, binding.create_path),
            "submission_token": binding.issue_submission_token(request),
        },
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def build_write_routes(binding: WriteResourceBinding) -> list[Route]:
    async def create_get(request: Request) -> Response:
        if not await binding.authorize(request):
            return PlainTextResponse(
                "Forbidden", status_code=403, headers={"Cache-Control": "no-store"}
            )
        return _render_form(binding, request)

    async def create_post(request: Request) -> Response:
        if not await binding.authorize(request):
            return PlainTextResponse(
                "Forbidden", status_code=403, headers={"Cache-Control": "no-store"}
            )
        if not await binding.verify_csrf(request):
            return PlainTextResponse(
                "Invalid CSRF token", status_code=403, headers={"Cache-Control": "no-store"}
            )
        submitted = await _parse_form(request, binding.form_schema)
        if submitted is None:
            return PlainTextResponse(
                "Invalid form", status_code=400, headers={"Cache-Control": "no-store"}
            )
        try:
            binding.form_schema.parse(submitted)
            await binding.mutation_service.create(submitted)
        except FormValidationError as exc:
            return _render_form(
                binding,
                request,
                submitted=submitted,
                issues=exc.state.issues,
                status_code=422,
            )
        except ValueError:
            return PlainTextResponse(
                "Invalid form", status_code=400, headers={"Cache-Control": "no-store"}
            )
        return mutation_success(request, location=mounted_path(request, binding.path))

    return [
        Route(
            binding.create_path,
            create_get,
            methods=["GET"],
            name=f"resource:{binding.path}:create",
        ),
        Route(
            binding.create_path,
            create_post,
            methods=["POST"],
            name=f"resource:{binding.path}:create.submit",
        ),
    ]
