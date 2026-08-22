from __future__ import annotations

from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.generated_api import ApiExposure, ResourceApiDefinition
from rakit_tortoise.plugin import TortoisePlugin
from tortoise import fields
from tortoise.models import Model


class CompileWidget(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=100)


POLICY = ResourceFieldPolicy(
    list_fields=("id", "name"),
    detail_fields=("id", "name"),
)


def test_tortoise_generated_crud_compiles_with_resource_owned_uow() -> None:
    builder = ApplicationBuilder()
    plugin = TortoisePlugin()
    builder.install(plugin)
    runtime = plugin._claim(CompileWidget, POLICY)
    assert runtime is not None
    assert runtime.generated_executor_provider is not None
    assert runtime.unit_of_work_provider_id == "persistence.tortoise"

    builder.add_resource(
        ResourceDefinition(
            resource_id="widgets",
            path="/widgets",
            label="Widgets",
            singular_label="Widget",
            field_policy=POLICY,
            api=ResourceApiDefinition(
                exposure=ApiExposure.CRUD,
                read_fields=("id", "name"),
                create_fields=("name",),
                update_fields=("name",),
            ),
        ),
        runtime.data_source,
        generated_executor_provider=runtime.generated_executor_provider,
        unit_of_work_provider_id=runtime.unit_of_work_provider_id,
    )

    compiled = compile_application(builder)

    assert tuple(
        requirement.requirement_id
        for requirement in compiled.capability_requirements
    ) == ("generated-api:widgets:write",)
    report = compiled.capability_reports[0]
    assert report.requirement.requirement_id == "generated-api:widgets:write"
    assert report.satisfied is True
    assert report.missing.names == ()
    assert dict(compiled.resource_unit_of_work_provider_ids) == {
        "widgets": "persistence.tortoise"
    }
    assert "widgets" in dict(compiled.generated_resource_executor_providers)
    assert "persistence.tortoise" in dict(compiled.unit_of_work_factories)
    assert tuple(item.integration_id for item in compiled.configured_integrations) == (
        "persistence.tortoise",
    )
