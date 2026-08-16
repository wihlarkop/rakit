from dataclasses import dataclass

import pytest

from rakit_core.capabilities import (
    CapabilityProvider,
    CapabilityRequirement,
    CapabilitySet,
)
from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.errors import RakitError


def _provider(provider_id: str, *capabilities: str) -> CapabilityProvider:
    return CapabilityProvider(provider_id, CapabilitySet.of(*capabilities))


def test_compilation_records_satisfied_capability_requirements() -> None:
    builder = ApplicationBuilder()
    builder.register_capability_provider(_provider("schema.example", "schema.input-validation"))
    builder.require_capabilities(
        CapabilityRequirement.of("generated-api.input", "schema.input-validation")
    )

    compiled = compile_application(builder)

    assert tuple(provider.provider_id for provider in compiled.capability_providers) == (
        "schema.example",
    )
    assert tuple(requirement.requirement_id for requirement in compiled.capability_requirements) == (
        "generated-api.input",
    )
    assert len(compiled.capability_reports) == 1
    assert compiled.capability_reports[0].satisfied is True


def test_compilation_fails_closed_when_requirement_is_not_satisfied() -> None:
    builder = ApplicationBuilder()
    builder.register_capability_provider(_provider("schema.example", "schema.input-validation"))
    builder.require_capabilities(
        CapabilityRequirement.of(
            "generated-api.patch",
            "schema.input-validation",
            "schema.partial-update",
        )
    )

    with pytest.raises(RakitError) as captured:
        compile_application(builder)

    assert captured.value.code == "config.invalid"
    assert captured.value.details["reason"] == "missing_capabilities"
    assert captured.value.details["requirement"] == "generated-api.patch"
    assert captured.value.details["missing"] == ["schema.partial-update"]
    assert captured.value.details["providers"] == ["schema.example"]


def test_duplicate_capability_provider_id_is_rejected() -> None:
    builder = ApplicationBuilder()
    builder.register_capability_provider(_provider("schema.example", "schema.input-validation"))

    with pytest.raises(RakitError) as captured:
        builder.register_capability_provider(
            _provider("schema.example", "schema.output-serialization")
        )

    assert captured.value.details == {
        "provider": "schema.example",
        "reason": "duplicate_capability_provider",
    }


def test_duplicate_capability_requirement_id_is_rejected() -> None:
    builder = ApplicationBuilder()
    builder.require_capabilities(CapabilityRequirement.of("api.read", "persistence.read"))

    with pytest.raises(RakitError) as captured:
        builder.require_capabilities(CapabilityRequirement.of("api.read", "web.asgi"))

    assert captured.value.details == {
        "requirement": "api.read",
        "reason": "duplicate_capability_requirement",
    }


def test_plugin_failure_rolls_back_capability_provider_registration() -> None:
    @dataclass(frozen=True)
    class BrokenPlugin:
        plugin_id: str = "broken"

        def configure(self, builder: ApplicationBuilder) -> None:
            builder.register_capability_provider(_provider("broken.provider", "example.capability"))
            builder.require_capabilities(
                CapabilityRequirement.of("broken.requirement", "example.capability")
            )
            raise RuntimeError("boom")

    builder = ApplicationBuilder()

    with pytest.raises(RuntimeError, match="boom"):
        builder.install(BrokenPlugin())

    assert builder.capability_providers == ()
    assert builder.capability_requirements == ()
    assert builder.plugins == ()


def test_capability_registration_is_frozen_after_compile() -> None:
    builder = ApplicationBuilder()
    compile_application(builder)

    with pytest.raises(RakitError) as captured:
        builder.register_capability_provider(_provider("late", "late.capability"))

    assert captured.value.code == "config.already_compiled"
