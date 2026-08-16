from collections.abc import Callable
from importlib.metadata import entry_points
from typing import cast

from .contracts import ServerAdapter, ServerCapabilities
from .errors import ServerAdapterConflictError, ServerAdapterNotFoundError, ServerConfigurationError

SERVER_ENTRY_POINT_GROUP = "rakit.servers"
type ServerAdapterFactory = Callable[[], ServerAdapter]


class ServerRegistry:
    def __init__(self, *, discover_entry_points: bool = True) -> None:
        self._factories: dict[str, ServerAdapterFactory] = {}
        self._discover_entry_points = discover_entry_points

    def register(self, name: str, factory: ServerAdapterFactory) -> None:
        if not name or name != name.strip():
            raise ValueError("Server adapter name must be a non-empty trimmed string")
        if name in self._factories:
            raise ValueError(f'Server adapter "{name}" is already registered')
        self._factories[name] = factory

    def _entry_point_factory(self, name: str) -> ServerAdapterFactory | None:
        if not self._discover_entry_points:
            return None
        matches = tuple(entry_points(group=SERVER_ENTRY_POINT_GROUP, name=name))
        if len(matches) > 1:
            raise ServerAdapterConflictError(
                f'Multiple installed server adapters claim the name "{name}"'
            )
        if not matches:
            return None
        loaded = matches[0].load()
        if not callable(loaded):
            raise ServerConfigurationError(
                f'Server adapter entry point "{name}" must resolve to a callable factory'
            )
        return cast(ServerAdapterFactory, loaded)

    def create(self, name: str) -> ServerAdapter:
        factory = self._factories.get(name)
        if factory is None:
            factory = self._entry_point_factory(name)
        if factory is None:
            raise ServerAdapterNotFoundError(
                f'Server adapter "{name}" is not installed or registered'
            )

        adapter = factory()
        adapter_name = getattr(adapter, "name", None)
        capabilities = getattr(adapter, "capabilities", None)
        run = getattr(adapter, "run", None)
        if adapter_name != name or not isinstance(capabilities, ServerCapabilities) or not callable(run):
            raise ServerConfigurationError(
                f'Server adapter factory for "{name}" returned an invalid adapter'
            )
        return adapter
