import pytest
from rakit_core.capabilities import (
    Capability,
    CapabilityProvider,
    CapabilityRequirement,
    CapabilitySet,
    evaluate_capabilities,
    require_capabilities,
)
from rakit_core.errors import RakitError


def test_capability_set_normalizes_duplicate_names_and_is_deterministic() -> None:
    capabilities = CapabilitySet.of(
        "persistence.read",
        Capability("persistence.write"),
        "persistence.read",
    )

    assert capabilities.names == ("persistence.read", "persistence.write")
    assert capabilities.supports("persistence.read")
    assert not capabilities.supports("persistence.transactions")


def test_capability_name_rejects_blank_or_untrimmed_values() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Capability("")

    with pytest.raises(ValueError, match="must not contain surrounding whitespace"):
        Capability(" persistence.read ")


def test_capability_report_aggregates_multiple_providers() -> None:
    requirement = CapabilityRequirement.of(
        "generated-api.write",
        "persistence.write",
        "transactions.root-uow",
    )
    providers = (
        CapabilityProvider(
            provider_id="sqlalchemy",
            capabilities=CapabilitySet.of("persistence.read", "persistence.write"),
        ),
        CapabilityProvider(
            provider_id="operation-runtime",
            capabilities=CapabilitySet.of("transactions.root-uow"),
        ),
    )

    report = evaluate_capabilities(requirement, providers)

    assert report.satisfied is True
    assert report.available.names == (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    )
    assert report.missing.names == ()
    assert report.provider_ids == ("sqlalchemy", "operation-runtime")


def test_require_capabilities_fails_closed_with_actionable_details() -> None:
    requirement = CapabilityRequirement.of(
        "generated-api.patch",
        "persistence.write",
        "concurrency.atomic-optimistic",
    )
    providers = (
        CapabilityProvider(
            provider_id="example-store",
            capabilities=CapabilitySet.of("persistence.write"),
        ),
    )

    with pytest.raises(RakitError) as captured:
        require_capabilities(requirement, providers)

    error = captured.value
    assert error.code == "config.invalid"
    assert error.details == {
        "requirement": "generated-api.patch",
        "required": ["concurrency.atomic-optimistic", "persistence.write"],
        "available": ["persistence.write"],
        "missing": ["concurrency.atomic-optimistic"],
        "providers": ["example-store"],
        "reason": "missing_capabilities",
    }
