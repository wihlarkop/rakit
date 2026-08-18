from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import BaseModel, Field
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.definitions import CompiledPageDefinition, PageDefinition, RouteDefinition
from rakit_core.mutations import OperationAuthorization
from rakit_core.pages import DomainPageHandler, PageContext, PageResult
from rakit_web.page_payload import PagePayloadKind, page_payload_view
from rakit_web.page_routes import PageBinding, _field_views, build_page_routes
from rakit_web.resource_routes import build_templates
from rakit_web.schema import PydanticSchemaAdapter
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount


class _Input(BaseModel):
    reason: str = Field(min_length=2, description="Why this operation is needed")


class _SeededSecret:
    def __str__(self) -> str:
        raise AssertionError("unsafe str() call")

    def __repr__(self) -> str:
        raise AssertionError("unsafe repr() call")


def _compiled_page(
    definition: PageDefinition,
) -> tuple[RouteDefinition, CompiledPageDefinition]:
    builder = ApplicationBuilder(admin_id="ops")
    builder.add_page(definition)
    compiled = compile_application(builder)
    route = next(
        route for route in compiled.routes if route.route_name == f"page:{definition.page_id}"
    )
    return route, compiled.compiled_pages[0]


def _page_app(definition: PageDefinition, *, template_dirs: tuple[Path, ...] = ()) -> Starlette:
    route, compiled = _compiled_page(definition)

    async def authorize(
        _request: Request, compiled_page: CompiledPageDefinition
    ) -> OperationAuthorization:
        return OperationAuthorization.for_requirement(
            admin_id="ops",
            resource_id=str(definition.page_id),
            operation=f"page:{definition.page_id}",
            principal_id="operator",
            requirement=compiled_page.permission,
        )

    binding = PageBinding(
        routes=((route, compiled),),
        templates=build_templates(template_dirs),
        schema_adapter=PydanticSchemaAdapter(),
        authorize_page=authorize,
        label="Operations",
    )
    return Starlette(routes=build_page_routes(binding))


def test_page_payload_classifier_accepts_only_closed_safe_shapes() -> None:
    scalar_values = (
        "ready",
        7,
        2.5,
        True,
        Decimal("12.50"),
        date(2026, 8, 19),
        datetime(2026, 8, 19, 4, 0, tzinfo=timezone.utc),
        UUID("12345678-1234-5678-1234-567812345678"),
    )
    for value in scalar_values:
        view = page_payload_view(value)
        assert view.kind is PagePayloadKind.SCALAR
        assert view.scalar == value

    assert page_payload_view(None).kind is PagePayloadKind.EMPTY
    for empty in ({}, [], ()):
        assert page_payload_view(empty).kind is PagePayloadKind.EMPTY

    mapping = page_payload_view({"status": "ready", "count": 3})
    assert mapping.kind is PagePayloadKind.MAPPING
    assert mapping.items == (("status", "ready"), ("count", 3))

    table = page_payload_view(
        [
            {"name": "alpha", "count": 1},
            {"name": "beta", "count": 2},
        ]
    )
    assert table.kind is PagePayloadKind.TABLE
    assert table.columns == ("name", "count")
    assert table.rows == (("alpha", 1), ("beta", 2))


def test_page_payload_classifier_rejects_nested_mixed_and_custom_values_without_stringifying() -> None:
    secret = _SeededSecret()

    assert page_payload_view(secret).kind is PagePayloadKind.UNSUPPORTED
    assert page_payload_view({"secret": secret}).kind is PagePayloadKind.UNSUPPORTED
    assert page_payload_view({"nested": {"value": "no"}}).kind is PagePayloadKind.UNSUPPORTED
    assert page_payload_view([{"a": 1}, {"b": 2}]).kind is PagePayloadKind.UNSUPPORTED
    assert page_payload_view([{"a": 1}, "mixed"]).kind is PagePayloadKind.UNSUPPORTED
    assert page_payload_view({1: "non-string-key"}).kind is PagePayloadKind.UNSUPPORTED
    assert page_payload_view({"": "empty-key"}).kind is PagePayloadKind.UNSUPPORTED


@pytest.mark.anyio
async def test_default_page_renderer_never_stringifies_unsupported_payload() -> None:
    secret = _SeededSecret()

    async def handler(_context: PageContext) -> PageResult[object]:
        return PageResult(payload=secret)

    definition = PageDefinition(
        page_id="unsafe-payload",
        path="/unsafe-payload",
        label="Unsafe Payload",
        handler=DomainPageHandler(handler),
    )
    app = _page_app(definition)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/unsafe-payload")

    assert response.status_code == 200
    assert "This page returned content that requires a custom template." in response.text


@pytest.mark.anyio
async def test_explicit_custom_template_retains_raw_payload_access(tmp_path: Path) -> None:
    (tmp_path / "custom.html").write_text(
        "Custom payload: {{ payload['name'] }} / {{ payload['count'] }}",
        encoding="utf-8",
    )

    async def handler(_context: PageContext) -> PageResult[dict[str, object]]:
        return PageResult(payload={"name": "alpha", "count": 3})

    definition = PageDefinition(
        page_id="custom",
        path="/custom",
        label="Custom",
        template="custom.html",
        handler=DomainPageHandler(handler),
    )
    app = _page_app(definition, template_dirs=(tmp_path,))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/custom")

    assert response.status_code == 200
    assert "Custom payload: alpha / 3" in response.text


def test_mutating_page_field_views_have_stable_accessibility_ids() -> None:
    fields = _field_views(
        PydanticSchemaAdapter(),
        _Input,
        {"reason": "x"},
        {"reason": ("String should have at least 2 characters",)},
    )

    assert fields == (
        {
            "id": "rakit-page-reason",
            "name": "reason",
            "label": "Reason",
            "description": "Why this operation is needed",
            "description_id": "rakit-page-reason-description",
            "error_id": "rakit-page-reason-error",
            "value": "x",
            "issues": ("String should have at least 2 characters",),
        },
    )


def test_default_page_template_never_interpolates_raw_payload_and_keeps_page_actions() -> None:
    template_root = Path(__file__).parents[1] / "src" / "rakit_web" / "templates" / "pages"
    page_template = (template_root / "page.html").read_text(encoding="utf-8")
    rejected_template = (template_root / "rejected.html").read_text(encoding="utf-8")

    assert "payload_view" in page_template
    assert "{{ payload }}" not in page_template
    assert "|safe" not in page_template
    assert "This page returned content that requires a custom template." in page_template
    assert "action_group(page_actions" in page_template
    assert 'aria-describedby="{{ described | join(\' \') }}"' in page_template
    assert 'aria-invalid="true"' in page_template
    assert "rejection_message" in rejected_template
    assert "|safe" not in rejected_template


@pytest.mark.anyio
async def test_default_page_navigation_is_mount_aware() -> None:
    definition = PageDefinition(page_id="about", path="/about", label="About")
    app = Starlette(routes=[Mount("/admin", app=_page_app(definition))])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/admin/about")

    assert response.status_code == 200
    assert 'data-rakit-breadcrumb="page"' in response.text
    assert 'href="/admin/"' in response.text
