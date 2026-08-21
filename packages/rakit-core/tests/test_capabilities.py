import pytest
from rakit_core.capabilities import (
    Capability,
    CapabilityProvider,
    CapabilityRequirement,
    CapabilitySet,
    analyze_capabilities,
    evaluate_capabilities,
)


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


def test_analyze_capabilities_reports_every_missing_requirement_deterministically() -> None:
    providers = (
        CapabilityProvider(
            provider_id="example-store",
            capabilities=CapabilitySet.of("persistence.write"),
        ),
    )
    requirements = (
        CapabilityRequirement.of("generated-api.write", "transactions.root-uow"),
        CapabilityRequirement.of(
            "generated-api.patch",
            "persistence.write",
            "concurrency.atomic-optimistic",
        ),
    )

    analysis = analyze_capabilities(reversed(requirements), reversed(providers))

    assert analysis.valid is False
    assert analysis.available.names == ("persistence.write",)
    assert tuple(report.requirement.requirement_id for report in analysis.reports) == (
        "generated-api.patch",
        "generated-api.write",
    )
    assert tuple(
        requirement.requirement_id for requirement in analysis.missing_requirements
    ) == (
        "generated-api.patch",
        "generated-api.write",
    )
    assert analysis.reports[0].missing.names == ("concurrency.atomic-optimistic",)
    assert analysis.reports[1].missing.names == ("transactions.root-uow",)


def test_analyze_capabilities_rejects_duplicate_provider_ids() -> None:
    providers = (
        CapabilityProvider("duplicate", CapabilitySet.of("a")),
        CapabilityProvider("duplicate", CapabilitySet.of("b")),
    )

    with pytest.raises(ValueError, match='Duplicate capability provider id: "duplicate"'):
        analyze_capabilities((), providers)


def test_analyze_capabilities_rejects_duplicate_requirement_ids() -> None:
    requirements = (
        CapabilityRequirement.of("duplicate", "a"),
        CapabilityRequirement.of("duplicate", "b"),
    )

    with pytest.raises(ValueError, match='Duplicate capability requirement id: "duplicate"'):
        analyze_capabilities(requirements, ())
