import importlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from .errors import InvalidServerTargetError


class ASGIApplication(Protocol):
    async def __call__(self, scope: object, receive: object, send: object) -> None: ...


class ServerTargetKind(StrEnum):
    IMPORT_STRING = "import-string"
    APPLICATION = "application"


@dataclass(frozen=True, slots=True)
class ServerTarget:
    kind: ServerTargetKind
    import_string: str | None = None
    application: ASGIApplication | None = None

    def __post_init__(self) -> None:
        if self.kind is ServerTargetKind.IMPORT_STRING:
            if self.import_string is None or self.application is not None:
                raise ValueError("Import-string targets must contain only import_string")
        elif self.kind is ServerTargetKind.APPLICATION and (
            self.application is None or self.import_string is not None
        ):
            raise ValueError("Application targets must contain only application")


def _validate_import_string(spec: str) -> str:
    if spec != spec.strip() or ":" not in spec:
        raise InvalidServerTargetError(
            "String server targets must use the module:attribute import-string form"
        )
    module_name, attribute = spec.split(":", 1)
    if not module_name or not attribute:
        raise InvalidServerTargetError(
            "String server targets must use the module:attribute import-string form"
        )
    return spec


def resolve_server_target(target: object) -> ServerTarget:
    if isinstance(target, str):
        return ServerTarget(
            kind=ServerTargetKind.IMPORT_STRING,
            import_string=_validate_import_string(target),
        )

    asgi = getattr(target, "asgi", None)
    if callable(asgi):
        application = asgi()
        if not callable(application):
            raise InvalidServerTargetError(
                "A server target exposing asgi() must return an ASGI callable"
            )
        return ServerTarget(
            kind=ServerTargetKind.APPLICATION,
            application=cast(ASGIApplication, application),
        )

    if callable(target):
        return ServerTarget(
            kind=ServerTargetKind.APPLICATION,
            application=cast(ASGIApplication, target),
        )

    raise InvalidServerTargetError(
        "Server target must be a module:attribute import string, an object exposing asgi(), "
        "or a raw ASGI callable"
    )


def load_application(spec: str) -> ASGIApplication:
    """Import a target and resolve it to an ASGI callable inside the active process."""
    validated = _validate_import_string(spec)
    module_name, attribute = validated.split(":", 1)
    try:
        value = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise InvalidServerTargetError(f'Unable to import server target "{validated}"') from exc

    resolved = resolve_server_target(value)
    if resolved.kind is not ServerTargetKind.APPLICATION or resolved.application is None:
        raise InvalidServerTargetError(
            f'Imported server target "{validated}" did not resolve to an ASGI callable'
        )
    return resolved.application
