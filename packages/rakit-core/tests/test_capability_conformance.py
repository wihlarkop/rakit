from dataclasses import replace

import pytest
import rakit_core.adapter_capabilities as adapter_capabilities
import rakit_core.conformance as conformance
from rakit_core.testing.capability_conformance import (
    CANONICAL_CONFORMANCE_SPEC_REGISTRY,
    PersistenceConformanceHarness,
    PersistenceReadConformanceHarness,
)

TEST_PERSISTENCE_INTEGRATION = conformance.IntegrationDescriptor(
    integration_id="test.persistence",
    category="persistence",
    display_name="Test Persistence",
    advertised_capabilities=conformance.CapabilitySet.of(
        adapter_capabilities.PERSISTENCE_READ,
        adapter_capabilities.PERSISTENCE_WRITE,
        adapter_capabilities.TRANSACTIONS_ROOT_UOW,
        adapter_capabilities.CONCURRENCY_ATOMIC_OPTIMISTIC,
    ),
)


class ReadOnlyPersistenceHarness:
    async def assert_read_semantics(self) -> None:
        return None


async def _pass(_harness: object) -> None:
    return None


async def _fail_one(_harness: object) -> None:
    raise AssertionError("first failure")


async def _fail_two(_harness: object) -> None:
    raise AssertionError("second failure")


def test_missing_advertised_prerequisites_are_hard_failures() -> None:
    descriptor = replace(
        TEST_PERSISTENCE_INTEGRATION,
        advertised_capabilities=conformance.CapabilitySet.of(
            adapter_capabilities.CONCURRENCY_ATOMIC_OPTIMISTIC
        ),
    )
    failures = conformance.validate_advertised_capabilities(descriptor)
    assert len(failures) == 1
    failure = failures[0]
    assert failure.kind is conformance.ConformanceFailureKind.ADVERTISEMENT
    assert failure.capability == adapter_capabilities.CONCURRENCY_ATOMIC_OPTIMISTIC.name
    assert adapter_capabilities.PERSISTENCE_WRITE.name in failure.message
    assert adapter_capabilities.TRANSACTIONS_ROOT_UOW.name in failure.message


def test_valid_first_party_shaped_advertisement_has_no_prerequisite_failure() -> None:
    assert conformance.validate_advertised_capabilities(TEST_PERSISTENCE_INTEGRATION) == ()


def test_spec_registry_rejects_duplicate_and_wrong_version_specs() -> None:
    spec = conformance.CapabilityConformanceSpec(
        adapter_capabilities.PERSISTENCE_READ,
        1,
        (conformance.CapabilityBehaviorCheck("read.pass", _pass),),
    )
    with pytest.raises(ValueError, match="Duplicate conformance spec"):
        conformance.build_conformance_spec_registry((spec, spec))
    with pytest.raises(ValueError, match="version mismatch"):
        conformance.build_conformance_spec_registry(
            (
                conformance.CapabilityConformanceSpec(
                    adapter_capabilities.PERSISTENCE_READ,
                    2,
                    (conformance.CapabilityBehaviorCheck("read.v2", _pass),),
                ),
            )
        )


@pytest.mark.anyio
async def test_behavior_failures_are_structured_and_deterministic() -> None:
    specs = conformance.build_conformance_spec_registry(
        (
            conformance.CapabilityConformanceSpec(
                adapter_capabilities.PERSISTENCE_READ,
                1,
                (
                    conformance.CapabilityBehaviorCheck("read.first", _fail_one),
                    conformance.CapabilityBehaviorCheck("read.second", _fail_two),
                ),
            ),
        )
    )
    result = await conformance.run_capability_conformance(
        descriptor=TEST_PERSISTENCE_INTEGRATION,
        capability=adapter_capabilities.PERSISTENCE_READ,
        harness=object(),
        specs=specs,
    )
    assert not result.passed
    assert [failure.kind for failure in result.failures] == [
        conformance.ConformanceFailureKind.BEHAVIOR,
        conformance.ConformanceFailureKind.BEHAVIOR,
    ]
    assert [failure.check_id for failure in result.failures] == ["read.first", "read.second"]
    assert "first failure" in result.failures[0].message
    assert "second failure" in result.failures[1].message


@pytest.mark.anyio
async def test_persistence_conformance_validates_only_the_advertised_capability_harness() -> None:
    descriptor = replace(
        TEST_PERSISTENCE_INTEGRATION,
        advertised_capabilities=conformance.CapabilitySet.of(adapter_capabilities.PERSISTENCE_READ),
    )
    harness = ReadOnlyPersistenceHarness()

    assert isinstance(harness, PersistenceReadConformanceHarness)
    assert not isinstance(harness, PersistenceConformanceHarness)

    result = await conformance.run_capability_conformance(
        descriptor=descriptor,
        capability=adapter_capabilities.PERSISTENCE_READ,
        harness=harness,
        specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
    )

    assert result.passed
    assert result.failures == ()


@pytest.mark.anyio
async def test_missing_spec_and_missing_harness_fail_closed() -> None:
    missing_spec = await conformance.run_capability_conformance(
        descriptor=TEST_PERSISTENCE_INTEGRATION,
        capability=adapter_capabilities.PERSISTENCE_READ,
        harness=object(),
        specs={},
    )
    assert not missing_spec.passed
    assert missing_spec.failures[0].kind is conformance.ConformanceFailureKind.REGISTRY
    assert "No conformance spec exists" in missing_spec.failures[0].message

    integration_result = await conformance.run_integration_conformance(
        descriptor=replace(
            TEST_PERSISTENCE_INTEGRATION,
            advertised_capabilities=conformance.CapabilitySet.of(
                adapter_capabilities.PERSISTENCE_READ
            ),
        ),
        harnesses={},
        specs={},
    )
    assert not integration_result.passed
    assert integration_result.failures[0].kind is conformance.ConformanceFailureKind.REGISTRY
    assert "No conformance harness exists" in integration_result.failures[0].message


def test_matrix_rows_sort_without_reordering_runtime_declarations() -> None:
    integration = conformance.IntegrationConformanceResult(
        integration_id="example.integration",
        results=(
            conformance.CapabilityConformanceResult("z.capability", 1),
            conformance.CapabilityConformanceResult("a.capability", 1),
        ),
    )
    rows = conformance.conformance_matrix_rows((integration,))
    assert [row.capability for row in rows] == ["a.capability", "z.capability"]
    assert [result.capability for result in integration.results] == [
        "z.capability",
        "a.capability",
    ]
