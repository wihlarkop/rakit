import subprocess
import sys

import pytest

from rakit._optional import RakitOptionalDependencyError


def test_granian_facade_reexports_real_class() -> None:
    from rakit.server.granian import GranianServer
    from rakit_server_granian.server import GranianServer as RealGranianServer

    assert GranianServer is RealGranianServer


def test_granian_facade_raises_friendly_error_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "rakit_server_granian", None)
    sys.modules.pop("rakit.server.granian", None)

    with pytest.raises(RakitOptionalDependencyError) as caught:
        import rakit.server.granian  # noqa: F401

    assert 'uv add "rakit[granian]"' in str(caught.value)


def test_storage_facade_reexports_neutral_contracts() -> None:
    from rakit.storage import DeleteBehavior, FileAccess, FileStorage, StoredFile, TemporaryUpload
    from rakit_storage import DeleteBehavior as RealDeleteBehavior
    from rakit_storage import FileAccess as RealFileAccess
    from rakit_storage import FileStorage as RealFileStorage
    from rakit_storage import StoredFile as RealStoredFile
    from rakit_storage import TemporaryUpload as RealTemporaryUpload

    assert DeleteBehavior is RealDeleteBehavior
    assert FileAccess is RealFileAccess
    assert FileStorage is RealFileStorage
    assert StoredFile is RealStoredFile
    assert TemporaryUpload is RealTemporaryUpload


def test_local_storage_facade_reexports_real_classes() -> None:
    from rakit.storage.local import LocalStorage, LocalStoragePlugin
    from rakit_storage_local import LocalStorage as RealLocalStorage
    from rakit_storage_local import LocalStoragePlugin as RealLocalStoragePlugin

    assert LocalStorage is RealLocalStorage
    assert LocalStoragePlugin is RealLocalStoragePlugin


def test_local_storage_facade_raises_friendly_error_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "rakit_storage_local", None)
    sys.modules.pop("rakit.storage.local", None)

    with pytest.raises(RakitOptionalDependencyError) as caught:
        import rakit.storage.local  # noqa: F401

    assert 'uv add "rakit[storage-local]"' in str(caught.value)


def test_importing_rakit_does_not_eagerly_import_optional_b2_adapters() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import rakit; import sys; "
            "assert 'rakit_server_granian' not in sys.modules; "
            "assert 'rakit_storage_local' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
