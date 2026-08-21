from __future__ import annotations

from dataclasses import replace

import pytest
from rakit_core.adapter_capabilities import (
    CONCURRENCY_ATOMIC_OPTIMISTIC,
    PERSISTENCE_READ,
    PERSISTENCE_WRITE,
    TRANSACTIONS_ROOT_UOW,
)
from rakit_core.capabilities import CapabilitySet
from rakit_core.conformance import (
    CapabilityBehaviorCheck,
    CapabilityConformanceResult,
    CapabilityConformanceSpec,
    ConformanceFailureKind,
    IntegrationConformanceResult,
    build_conformance_spec_registry,
    conformance_matrix_rows,
    run_capability_conformance,
    run_integration_conformance,
    validate_advertised_capabilities,
)
from rakit_core.integrations import IntegrationDescriptor


TEST_PERSISTENCE_INTEGRATION = IntegrationDescriptor(
    integration_id="test.persistence",
    category="persistence",
    display_name="Test Persistence",
    advertised_capabilities=CapabilitySet.of(
        PERSISTENCE_READ,
        PERSISTENCE_WRITE,
        TRANSACTIONS_ROOT_UOW,
        CONCURRENCY_ATOMIC_OPTIMISTIC,
    ),
)


async def _pass(_harness: object) -> None:
    return None


async def _fail_one(_harness: object) -> None:
    raise AssertionError("first failure")


async def _fail_two(_harness: object) -> None:
    raise AssertionError("second failure")


def test_missing_advertised_prerequisites_are_hard_failures() -> None:
    descriptor = replace(
        TEST_PERSISTENCE_INTEGRATION,
        advertised_capabilities=CapabilitySet.of(CONCURRENCY_ATOMIC_OPTIMISTIC),
    )
    failures = validate_advertised_capabilities(descriptor)
    assert len(failures) == 1
    failure = failures[0]
    assert failure.kind is ConformanceFailureKind.ADVERTISEMENT
    assert failure.capability == CONCURRENCY_ATOMIC_OPTIMISTIC.name
    assert PERSISTENCE_WRITE.name in failure.message
    assert TRANSACTIONS_ROOT_UOW.name in failure.message


def test_valid_first_party_shaped_advertisement_has_no_prerequisite_failure() -> None:
    assert validate_advertised_capabilities(TEST_PERSISTENCE_INTEGRATION) == ()


def test_spec_registry_rejects_duplicate_and_wrong_version_specs() -> None:
    spec = CapabilityConformanceSpec(
        PERSISTENCE_READ,
        1,
        (CapabilityBehaviorCheck("read.pass", _pass),),
    )
    with pytest.raises(ValueError, match="Duplicate conformance spec"):
        build_conformance_spec_registry((spec, spec))
    with pytest.raises(ValueError, match="version mismatch"):
        build_conformance_spec_registry(
            (
                CapabilityConformanceSpec(
                    PERSISTENCE_READ,
                    2,
                    (CapabilityBehaviorCheck("read.v2", _pass),),
                ),
            )
        )


@pytest.mark.anyio
async def test_behavior_failures_are_structured_and_deterministic() -> None:
    specs = build_conformance_spec_registry(
        (
            CapabilityConformanceSpec(
                PERSISTENCE_READ,
                1,
                (
                    CapabilityBehaviorCheck("read.first", _fail_one),
                    CapabilityBehaviorCheck("read.second", _fail_two),
                ),
            ),
        )
    )
    result = await run_capability_conformance(
        descriptor=TEST_PERSISTENCE_INTEGRATION,
        capability=PERSISTENCE_READ,
        harness=object(),
        specs=specs,
    )
    assert not result.passed
    assert [failure.kind for failure in result.failures] == [
        ConformanceFailureKind.BEHAVIOR,
        ConformanceFailureKind.BEHAVIOR,
    ]
    assert [failure.check_id for failure in result.failures] == ["read.first", "read.second"]
    assert "first failure" in result.failures[0].message
    assert "second failure" in result.failures[1].message


@pytest.mark.anyio
async def test_missing_spec_and_missing_harness_fail_closed() -> None:
    missing_spec = await run_capability_conformance(
        descriptor=TEST_PERSISTENCE_INTEGRATION,
        capability=PERSISTENCE_READ,
        harness=object(),
        specs={},
    )
    assert not missing_spec.passed
    assert missing_spec.failures[0].kind is ConformanceFailureKind.REGISTRY
    assert "No conformance spec exists" in missing_spec.failures[0].message

    integration_result = await run_integration_conformance(
        descriptor=replace(
            TEST_PERSISTENCE_INTEGRATION,
            advertised_capabilities=CapabilitySet.of(PERSISTENCE_READ),
        ),
        harnesses={},
        specs={},
    )
    assert not integration_result.passed
    assert integration_result.failures[0].kind is ConformanceFailureKind.REGISTRY
    assert "No conformance harness exists" in integration_result.failures[0].message


def test_matrix_rows_sort_without_reordering_runtime_declarations() -> None:
    integration = IntegrationConformanceResult(
        integration_id="example.integration",
        results=(
            CapabilityConformanceResult("z.capability", 1),
            CapabilityConformanceResult("a.capability", 1),
        ),
    )
    rows = conformance_matrix_rows((integration,))
    assert [row.capability for row in rows] == ["a.capability", "z.capability"]
    assert [result.capability for result in integration.results] == [
        "z.capability",
        "a.capability",
    ]
