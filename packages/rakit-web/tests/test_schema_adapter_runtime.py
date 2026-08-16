from dataclasses import dataclass

import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, EndpointAccessPolicy, EndpointContext, EndpointResult
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.definitions import PageDefinition
from rakit_core.pages import PageContext
from rakit_core.schema import SchemaField, SchemaValidationError, SchemaValidationIssue
from rakit_web.page_routes import _field_views, _model_values, _unknown_input_issues


class PlainSchema:
    pass


@dataclass(frozen=True)
class PlainValue:
    name: str
    count: int


class PlainSchemaAdapter:
    provider = CapabilityProvider(
        provider_id="schema.plain",
        capabilities=CapabilitySet.of(
            "schema.field-introspection",
            "schema.input-validation",
            "schema.output-serialization",
        ),
    )

    def fields(self, schema: type[object]) -> tuple[SchemaField, ...]:
        assert schema is PlainSchema
        return (
            SchemaField(name="name", title="Display name", description="Human-readable name"),
            SchemaField(name="count", title="Count"),
        )

    def field_names(self, schema: type[object]) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields(schema))

    def validate_input(self, schema: type[object], values: dict[str, object]) -> object:
        assert schema is PlainSchema
        try:
            name = str(values["name"])
            count = int(values["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(
                (
                    SchemaValidationIssue(
                        location=("count",),
                        code="invalid_count",
                        message="Count must be an integer",
                    ),
                )
            ) from exc
        return PlainValue(name=name, count=count)

    def serialize_output(self, schema: type[object], value: object) -> object:
        assert schema is PlainSchema
        if not isinstance(value, PlainValue):
            raise SchemaValidationError(
                (
                    SchemaValidationIssue(
                        location=("__root__",),
                        code="invalid_value",
                        message="Expected PlainValue",
                    ),
                )
            )
        return {"name": value.name, "count": value.count}


@pytest.mark.anyio
async def test_custom_endpoint_uses_configured_non_pydantic_schema_adapter() -> None:
    adapter = PlainSchemaAdapter()
    admin = Admin(title="Schema Adapter", debug=True, schema_adapter=adapter)

    @admin.api.get(
        "/api/plain",
        endpoint_id="plain",
        input_schema=PlainSchema,
        output_schema=PlainSchema,
        access_policy=EndpointAccessPolicy.PUBLIC,
    )
    async def plain(context: EndpointContext) -> EndpointResult[PlainValue]:
        assert isinstance(context.values, PlainValue)
        return EndpointResult(
            PlainValue(name=context.values.name.upper(), count=context.values.count + 1)
        )

    app = admin.asgi()
    async with (
        LifespanDriver(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://testserver",
        ) as client,
    ):
        response = await client.get("/api/plain", params={"name": "rakit", "count": "2"})

    assert response.status_code == 200
    assert response.json() == {"name": "RAKIT", "count": 3}
    assert tuple(provider.provider_id for provider in admin.builder.capability_providers) == (
        "web.starlette",
        "schema.plain",
    )


def test_custom_page_schema_helpers_use_schema_adapter_metadata_and_validation() -> None:
    adapter = PlainSchemaAdapter()
    page = PageDefinition(
        page_id="plain",
        path="/plain",
        label="Plain",
        input_schema=PlainSchema,
    )

    assert page.input_schema is PlainSchema
    assert _unknown_input_issues(adapter, PlainSchema, {"name": "rakit", "extra": "no"}) == {
        "extra": ("Unknown page input field",)
    }
    assert _field_views(adapter, PlainSchema, {"name": "rakit"}, {}) == (
        {
            "id": "rakit-page-name",
            "name": "name",
            "label": "Display name",
            "description": "Human-readable name",
            "value": "rakit",
            "issues": (),
        },
        {
            "id": "rakit-page-count",
            "name": "count",
            "label": "Count",
            "description": None,
            "value": "",
            "issues": (),
        },
    )
    values = _model_values(adapter, PlainSchema, {"name": "rakit", "count": "2"})
    assert values == PlainValue(name="rakit", count=2)
    context = PageContext(definition=page, values=values)
    assert context.values == PlainValue(name="rakit", count=2)
