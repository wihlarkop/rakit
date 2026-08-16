from dataclasses import dataclass

from .adapter_capabilities import (
    PERSISTENCE_WRITE,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    TRANSACTIONS_ROOT_UOW,
)
from .capabilities import CapabilityRequirement
from .datasource import DataSource, resolve_resource_field_definitions
from .definitions import ResourceDefinition
from .errors import ErrorCode, RakitError
from .generated_api import ApiExposure, CompiledResourceApi


def _invalid_generated_api(resource_id: str, reason: str) -> RakitError:
    return RakitError(
        code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
        message=f'Resource "{resource_id}" has an invalid generated API policy.',
        status_code=500,
        details={"resource_id": resource_id, "reason": reason},
    )


@dataclass(frozen=True, slots=True)
class GeneratedApiCompilation:
    resources: tuple[CompiledResourceApi, ...]
    requirements: tuple[CapabilityRequirement, ...]


def compile_generated_resource_apis(
    resources: tuple[ResourceDefinition, ...],
    data_sources: dict[str, DataSource],
) -> GeneratedApiCompilation:
    compiled: list[CompiledResourceApi] = []
    requirements: list[CapabilityRequirement] = []

    for resource in resources:
        api = resource.api
        if api.exposure is ApiExposure.NONE:
            continue

        data_source = data_sources[resource.resource_id]
        known_fields = set(data_source.fields)
        identity_fields = tuple(data_source.identity_fields)
        identity_set = set(identity_fields)

        read_fields = api.read_fields or resource.field_policy.detail_fields
        for policy_fields in (read_fields, api.create_fields, api.update_fields):
            if not set(policy_fields) <= known_fields:
                raise _invalid_generated_api(resource.resource_id, "generated_api_unknown_field")

        if identity_set.intersection(api.create_fields) or identity_set.intersection(
            api.update_fields
        ):
            raise _invalid_generated_api(
                resource.resource_id, "generated_api_identity_field_writable"
            )

        filterable_fields = set(resource.field_policy.filter_fields)
        for item in api.filters:
            if item.field not in known_fields or item.field not in filterable_fields:
                raise _invalid_generated_api(
                    resource.resource_id, "generated_api_filter_field_not_allowed"
                )

        field_definitions = ()
        if api.exposure is ApiExposure.CRUD:
            resolved = resolve_resource_field_definitions(data_source)
            if resolved is None:
                raise _invalid_generated_api(
                    resource.resource_id, "generated_api_field_metadata_not_supported"
                )
            definitions_by_name = {field.field_id: field for field in resolved}
            if set(definitions_by_name) != known_fields:
                raise _invalid_generated_api(
                    resource.resource_id, "generated_api_field_metadata_mismatch"
                )
            non_writable = {
                name
                for name in (*api.create_fields, *api.update_fields)
                if not definitions_by_name[name].writable
            }
            if non_writable:
                raise _invalid_generated_api(
                    resource.resource_id, "generated_api_non_writable_field"
                )
            field_definitions = resolved
            requirements.append(
                CapabilityRequirement.of(
                    f"generated-api:{resource.resource_id}:write",
                    PERSISTENCE_WRITE,
                    TRANSACTIONS_ROOT_UOW,
                )
            )

        if api.create_schema is not None or api.update_schema is not None:
            requirements.append(
                CapabilityRequirement.of(
                    f"generated-api:{resource.resource_id}:schema-input",
                    SCHEMA_INPUT_VALIDATION,
                    SCHEMA_OUTPUT_SERIALIZATION,
                )
            )

        if api.output_schema is not None:
            requirements.append(
                CapabilityRequirement.of(
                    f"generated-api:{resource.resource_id}:schema-output",
                    SCHEMA_OUTPUT_SERIALIZATION,
                )
            )

        compiled.append(
            CompiledResourceApi(
                resource_id=resource.resource_id,
                definition=api,
                operations=api.operations,
                read_fields=read_fields,
                create_fields=api.create_fields,
                update_fields=api.update_fields,
                identity_fields=identity_fields,
                filters=api.filters,
                field_definitions=field_definitions,
            )
        )

    return GeneratedApiCompilation(
        resources=tuple(compiled),
        requirements=tuple(requirements),
    )


__all__ = ["GeneratedApiCompilation", "compile_generated_resource_apis"]
