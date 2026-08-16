from dataclasses import dataclass

from .adapter_capabilities import SCHEMA_INPUT_VALIDATION
from .capabilities import CapabilityProvider, CapabilityReport, CapabilityRequirement, require_capabilities
from .datasource import DataSource
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
    reports: tuple[CapabilityReport, ...]


def compile_generated_resource_apis(
    resources: tuple[ResourceDefinition, ...],
    data_sources: dict[str, DataSource],
    providers: tuple[CapabilityProvider, ...],
) -> GeneratedApiCompilation:
    compiled: list[CompiledResourceApi] = []
    requirements: list[CapabilityRequirement] = []
    reports: list[CapabilityReport] = []

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

        if identity_set.intersection(api.create_fields) or identity_set.intersection(api.update_fields):
            raise _invalid_generated_api(
                resource.resource_id, "generated_api_identity_field_writable"
            )

        filterable_fields = set(resource.field_policy.filter_fields)
        for item in api.filters:
            if item.field not in known_fields or item.field not in filterable_fields:
                raise _invalid_generated_api(
                    resource.resource_id, "generated_api_filter_field_not_allowed"
                )

        if api.exposure is ApiExposure.CRUD:
            capabilities = data_source.capabilities
            if not (capabilities.create and capabilities.update and capabilities.delete):
                raise _invalid_generated_api(
                    resource.resource_id, "generated_api_write_not_supported"
                )
            if not capabilities.transactions:
                raise _invalid_generated_api(
                    resource.resource_id, "generated_api_transactions_not_supported"
                )

        if api.create_schema is not None or api.update_schema is not None:
            requirement = CapabilityRequirement.of(
                f"generated-api:{resource.resource_id}:schema-input",
                SCHEMA_INPUT_VALIDATION,
            )
            requirements.append(requirement)
            reports.append(require_capabilities(requirement, providers))

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
            )
        )

    return GeneratedApiCompilation(
        resources=tuple(compiled),
        requirements=tuple(requirements),
        reports=tuple(reports),
    )


__all__ = ["GeneratedApiCompilation", "compile_generated_resource_apis"]
