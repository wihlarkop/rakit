import pytest
from click.testing import CliRunner
from rakit.cli import cli
from rakit_core.capabilities import (
    CapabilityProvider,
    CapabilityReport,
    CapabilityRequirement,
    CapabilitySet,
)
from rakit_core.compiler import CompiledApplication
from rakit_core.errors import ErrorCode, RakitError


class CompilesSuccessfully:
    def compile(self) -> CompiledApplication:
        schema = CapabilityProvider(
            provider_id="schema.pydantic",
            capabilities=CapabilitySet.of(
                "schema.input-validation",
                "schema.output-serialization",
            ),
        )
        web = CapabilityProvider(
            provider_id="web.starlette",
            capabilities=CapabilitySet.of("web.asgi", "web.http-routing"),
        )
        requirement = CapabilityRequirement.of(
            "generated-api.input",
            "schema.input-validation",
            "web.http-routing",
        )
        report = CapabilityReport(
            requirement=requirement,
            providers=(schema, web),
            available=schema.capabilities.union(web.capabilities),
            missing=CapabilitySet(),
        )
        return CompiledApplication(
            routes=(),
            plugins=("example",),
            resources=(),
            capability_providers=(web, schema),
            capability_requirements=(requirement,),
            capability_reports=(report,),
        )


class CompilesWithoutCapabilityMetadata:
    def compile(self) -> CompiledApplication:
        return CompiledApplication(routes=(), plugins=(), resources=())


class MissingCapabilities:
    def compile(self) -> CompiledApplication:
        raise RakitError(
            code=ErrorCode.CONFIG_INVALID,
            message='Capability requirement "generated-api.patch" is not satisfied.',
            status_code=500,
            details={
                "requirement": "generated-api.patch",
                "required": ["schema.input-validation", "schema.partial-update"],
                "available": ["schema.input-validation"],
                "missing": ["schema.partial-update"],
                "providers": ["schema.pydantic"],
                "reason": "missing_capabilities",
            },
        )


def test_check_prints_sorted_provider_and_requirement_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rakit.cli.load_object", lambda target: CompilesSuccessfully())

    result = CliRunner().invoke(cli, ["check", "example:admin"])

    assert result.exit_code == 0
    assert result.output == (
        "Rakit configuration is valid.\n"
        "Routes: 0\n"
        "Plugins: 1\n"
        "Capability providers:\n"
        "  schema.pydantic: schema.input-validation, schema.output-serialization\n"
        "  web.starlette: web.asgi, web.http-routing\n"
        "Capability requirements:\n"
        "  generated-api.input: satisfied\n"
    )


def test_check_handles_apps_without_capability_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rakit.cli.load_object", lambda target: CompilesWithoutCapabilityMetadata())

    result = CliRunner().invoke(cli, ["check", "example:admin"])

    assert result.exit_code == 0
    assert "Capability providers: none\n" in result.output
    assert "Capability requirements: none\n" in result.output


def test_check_explains_missing_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rakit.cli.load_object", lambda target: MissingCapabilities())

    result = CliRunner().invoke(cli, ["check", "example:admin"])

    assert result.exit_code == 1
    assert "Rakit configuration is invalid." in result.output
    assert "Capability requirement: generated-api.patch" in result.output
    assert "Missing capabilities: schema.partial-update" in result.output
    assert "Available capabilities: schema.input-validation" in result.output
    assert "Providers: schema.pydantic" in result.output
    assert "Required adapter capabilities are not available." in result.output
