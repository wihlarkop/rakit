import pytest
from rakit_core.generated_api import (
    ApiExposure,
    ApiFilterDefinition,
    GeneratedCrudOperation,
    ResourceApiDefinition,
)
from rakit_core.query import FilterOperator


def test_generated_api_defaults_to_no_exposure() -> None:
    definition = ResourceApiDefinition()

    assert definition.exposure is ApiExposure.NONE
    assert definition.operations == ()
    assert definition.read_fields == ()
    assert definition.create_fields == ()
    assert definition.update_fields == ()


def test_read_only_and_crud_exposure_expand_to_stable_operation_sets() -> None:
    read_only = ResourceApiDefinition(exposure=ApiExposure.READ_ONLY)
    crud = ResourceApiDefinition(exposure=ApiExposure.CRUD)

    assert read_only.operations == (
        GeneratedCrudOperation.LIST,
        GeneratedCrudOperation.DETAIL,
    )
    assert crud.operations == (
        GeneratedCrudOperation.LIST,
        GeneratedCrudOperation.DETAIL,
        GeneratedCrudOperation.CREATE,
        GeneratedCrudOperation.UPDATE_PARTIAL,
        GeneratedCrudOperation.DELETE,
    )
    assert "put" not in {operation.value for operation in crud.operations}


def test_field_policies_are_separate_and_immutable() -> None:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email"),
        create_fields=("email",),
        update_fields=("email",),
    )

    assert definition.read_fields == ("id", "email")
    assert definition.create_fields == ("email",)
    assert definition.update_fields == ("email",)
    assert ResourceApiDefinition.__dataclass_params__.frozen is True


def test_duplicate_field_policy_entries_are_rejected() -> None:
    with pytest.raises(ValueError, match="read_fields.*unique"):
        ResourceApiDefinition(read_fields=("email", "email"))


def test_standard_filter_definition_requires_unique_operators() -> None:
    definition = ApiFilterDefinition(
        name="status",
        field="status",
        operators=(FilterOperator.EQ, FilterOperator.IN),
    )

    assert definition.name == "status"
    assert definition.field == "status"
    assert definition.operators == (FilterOperator.EQ, FilterOperator.IN)

    with pytest.raises(ValueError, match="operators.*unique"):
        ApiFilterDefinition(
            name="status",
            field="status",
            operators=(FilterOperator.EQ, FilterOperator.EQ),
        )


def test_custom_schema_slots_are_framework_neutral() -> None:
    class CreateSchema:
        pass

    class UpdateSchema:
        pass

    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        create_schema=CreateSchema,
        update_schema=UpdateSchema,
    )

    assert definition.create_schema is CreateSchema
    assert definition.update_schema is UpdateSchema
