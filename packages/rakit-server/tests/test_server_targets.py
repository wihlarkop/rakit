import pytest

from rakit_server import ServerTargetKind, resolve_server_target
from rakit_server.errors import InvalidServerTargetError


async def raw_asgi(scope: object, receive: object, send: object) -> None:
    del scope, receive, send


class AdminLike:
    def __init__(self) -> None:
        self.calls = 0

    def asgi(self):
        self.calls += 1
        return raw_asgi


def test_import_string_target_is_preserved_for_process_capable_adapters() -> None:
    target = resolve_server_target("myapp:admin")

    assert target.kind is ServerTargetKind.IMPORT_STRING
    assert target.import_string == "myapp:admin"
    assert target.application is None


def test_admin_like_target_resolves_to_its_asgi_application_once() -> None:
    admin = AdminLike()

    target = resolve_server_target(admin)

    assert target.kind is ServerTargetKind.APPLICATION
    assert target.application is raw_asgi
    assert target.import_string is None
    assert admin.calls == 1


def test_raw_asgi_callable_is_preserved() -> None:
    target = resolve_server_target(raw_asgi)

    assert target.kind is ServerTargetKind.APPLICATION
    assert target.application is raw_asgi


def test_invalid_target_fails_closed() -> None:
    with pytest.raises(InvalidServerTargetError, match="module:attribute"):
        resolve_server_target("not-an-import-string")

    with pytest.raises(InvalidServerTargetError, match="ASGI callable"):
        resolve_server_target(object())


class BrokenAdminLike:
    def asgi(self):
        return object()


def test_admin_like_target_requires_asgi_to_return_callable() -> None:
    with pytest.raises(InvalidServerTargetError, match="asgi\(\)"):
        resolve_server_target(BrokenAdminLike())
