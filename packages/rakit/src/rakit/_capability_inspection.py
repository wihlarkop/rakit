from dataclasses import dataclass

from rakit_core.capabilities import CapabilityAnalysis, analyze_capabilities
from rakit_core.compiler import CapabilityConfigurationError, CompiledApplication
from rakit_core.integrations import ConfiguredIntegration, IntegrationDescriptor

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ConfiguredIntegrationInspection:
    integration_id: str | None
    category: str
    display_name: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.integration_id,
            "category": self.category,
            "display_name": self.display_name,
        }


@dataclass(frozen=True, slots=True)
class ProviderInspection:
    provider_id: str
    capabilities: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"id": self.provider_id, "capabilities": list(self.capabilities)}


@dataclass(frozen=True, slots=True)
class RequirementInspection:
    requirement_id: str
    status: str
    required: tuple[str, ...]
    available: tuple[str, ...]
    missing: tuple[str, ...]
    providers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.requirement_id,
            "status": self.status,
            "required": list(self.required),
            "available": list(self.available),
            "missing": list(self.missing),
            "providers": list(self.providers),
        }


@dataclass(frozen=True, slots=True)
class ConfiguredInspection:
    integrations: tuple[ConfiguredIntegrationInspection, ...]
    providers: tuple[ProviderInspection, ...]
    requirements: tuple[RequirementInspection, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "integrations": [item.to_dict() for item in self.integrations],
            "providers": [item.to_dict() for item in self.providers],
            "requirements": [item.to_dict() for item in self.requirements],
        }


@dataclass(frozen=True, slots=True)
class InstalledIntegrationInspection:
    integration_id: str
    category: str
    display_name: str
    advertised_capabilities: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.integration_id,
            "category": self.category,
            "display_name": self.display_name,
            "advertised_capabilities": list(self.advertised_capabilities),
        }


@dataclass(frozen=True, slots=True)
class CapabilityInspectionReport:
    schema_version: int
    target: str | None
    valid: bool | None
    configured: ConfiguredInspection | None
    installed: tuple[InstalledIntegrationInspection, ...] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target": self.target,
            "valid": self.valid,
            "configured": None if self.configured is None else self.configured.to_dict(),
            "installed": (
                None if self.installed is None else [item.to_dict() for item in self.installed]
            ),
        }


def _configured_integration_inspections(
    integrations: tuple[ConfiguredIntegration, ...],
) -> tuple[ConfiguredIntegrationInspection, ...]:
    return tuple(
        ConfiguredIntegrationInspection(
            integration_id=integration.integration_id,
            category=integration.category,
            display_name=integration.display_name,
        )
        for integration in integrations
    )


def _configured_from_analysis(
    integrations: tuple[ConfiguredIntegration, ...],
    analysis: CapabilityAnalysis,
) -> ConfiguredInspection:
    return ConfiguredInspection(
        integrations=_configured_integration_inspections(integrations),
        providers=tuple(
            ProviderInspection(
                provider_id=provider.provider_id,
                capabilities=provider.capabilities.names,
            )
            for provider in analysis.providers
        ),
        requirements=tuple(
            RequirementInspection(
                requirement_id=report.requirement.requirement_id,
                status="satisfied" if report.satisfied else "missing",
                required=report.requirement.required.names,
                available=report.available.names,
                missing=report.missing.names,
                providers=report.provider_ids,
            )
            for report in sorted(
                analysis.reports,
                key=lambda item: item.requirement.requirement_id,
            )
        ),
    )


def _installed_inspections(
    installed: tuple[IntegrationDescriptor, ...] | None,
) -> tuple[InstalledIntegrationInspection, ...] | None:
    if installed is None:
        return None
    return tuple(
        InstalledIntegrationInspection(
            integration_id=descriptor.integration_id,
            category=descriptor.category,
            display_name=descriptor.display_name,
            advertised_capabilities=descriptor.advertised_capabilities.names,
        )
        for descriptor in sorted(installed, key=lambda item: item.integration_id)
    )


def inspection_from_compiled(
    target: str,
    compiled: CompiledApplication,
    *,
    installed: tuple[IntegrationDescriptor, ...] | None = None,
) -> CapabilityInspectionReport:
    analysis = compiled.capability_analysis or analyze_capabilities(
        compiled.capability_requirements,
        compiled.capability_providers,
    )
    return CapabilityInspectionReport(
        schema_version=SCHEMA_VERSION,
        target=target,
        valid=analysis.valid,
        configured=_configured_from_analysis(compiled.configured_integrations, analysis),
        installed=_installed_inspections(installed),
    )


def inspection_from_capability_error(
    target: str,
    error: CapabilityConfigurationError,
    *,
    installed: tuple[IntegrationDescriptor, ...] | None = None,
) -> CapabilityInspectionReport:
    return CapabilityInspectionReport(
        schema_version=SCHEMA_VERSION,
        target=target,
        valid=False,
        configured=_configured_from_analysis(error.configured_integrations, error.analysis),
        installed=_installed_inspections(installed),
    )


def inspection_installed_only(
    installed: tuple[IntegrationDescriptor, ...],
) -> CapabilityInspectionReport:
    return CapabilityInspectionReport(
        schema_version=SCHEMA_VERSION,
        target=None,
        valid=None,
        configured=None,
        installed=_installed_inspections(installed),
    )


def render_capability_inspection(report: CapabilityInspectionReport) -> str:
    lines: list[str] = []
    if report.target is not None:
        lines.append(f"Application: {report.target}")
        lines.append(f"Status: {'valid' if report.valid else 'invalid'}")
        lines.append("")
        assert report.configured is not None
        lines.append("Configured integrations:")
        if report.configured.integrations:
            for integration in report.configured.integrations:
                identifier = integration.integration_id or "custom/unknown"
                lines.append(f"  {identifier}: {integration.display_name} ({integration.category})")
        else:
            lines.append("  none")
        lines.append("")
        lines.append("Capability providers:")
        if report.configured.providers:
            for provider in report.configured.providers:
                lines.append(f"  {provider.provider_id}")
                for capability in provider.capabilities:
                    lines.append(f"    {capability}")
        else:
            lines.append("  none")
        lines.append("")
        lines.append("Requirements:")
        if report.configured.requirements:
            for requirement in report.configured.requirements:
                lines.append(f"  {requirement.requirement_id}: {requirement.status}")
                if requirement.missing:
                    lines.append(f"    missing: {', '.join(requirement.missing)}")
        else:
            lines.append("  none")

    if report.installed is not None:
        if lines:
            lines.append("")
        lines.append("Installed integrations:")
        if report.installed:
            for integration in report.installed:
                lines.append(
                    f"  {integration.integration_id}: {integration.display_name} "
                    f"({integration.category})"
                )
        else:
            lines.append("  none")

    return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION",
    "CapabilityInspectionReport",
    "inspection_from_capability_error",
    "inspection_from_compiled",
    "inspection_installed_only",
    "render_capability_inspection",
]
