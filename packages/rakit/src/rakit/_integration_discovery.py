from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points

from rakit_core.integrations import IntegrationDescriptor

INTEGRATION_ENTRY_POINT_GROUP = "rakit.integrations"


class InstalledIntegrationDiscoveryError(RuntimeError):
    pass


def discover_installed_integrations(
    *,
    candidates: Iterable[EntryPoint] | None = None,
) -> tuple[IntegrationDescriptor, ...]:
    discovered = (
        tuple(entry_points(group=INTEGRATION_ENTRY_POINT_GROUP))
        if candidates is None
        else tuple(candidates)
    )
    ordered = tuple(sorted(discovered, key=lambda item: (item.name, item.value)))
    descriptors: list[IntegrationDescriptor] = []
    seen: set[str] = set()
    for entry_point in ordered:
        try:
            loaded = entry_point.load()
        except Exception as exc:
            raise InstalledIntegrationDiscoveryError(
                f'Unable to load installed integration "{entry_point.name}": {exc}'
            ) from exc
        if not isinstance(loaded, IntegrationDescriptor):
            raise InstalledIntegrationDiscoveryError(
                f'Installed integration "{entry_point.name}" must resolve to '
                "an IntegrationDescriptor instance"
            )
        if entry_point.name != loaded.integration_id:
            raise InstalledIntegrationDiscoveryError(
                f'Installed integration entry-point name "{entry_point.name}" does not match '
                f'descriptor id "{loaded.integration_id}"'
            )
        if loaded.integration_id in seen:
            raise InstalledIntegrationDiscoveryError(
                f'Duplicate installed integration id "{loaded.integration_id}"'
            )
        seen.add(loaded.integration_id)
        descriptors.append(loaded)
    return tuple(sorted(descriptors, key=lambda item: item.integration_id))


__all__ = [
    "INTEGRATION_ENTRY_POINT_GROUP",
    "InstalledIntegrationDiscoveryError",
    "discover_installed_integrations",
]
