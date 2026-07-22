from collections.abc import Mapping
from typing import Any, Never, cast


class _FrozenDict(dict[Any, Any]):
    """A serialization-friendly dict copy that rejects every mutation API."""

    def _immutable(self, *_args: object, **_kwargs: object) -> Never:
        raise TypeError("Frozen mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def freeze_mapping[K, V](value: Mapping[K, V]) -> dict[K, V]:
    """Copy a mapping into an immutable dict subclass Pydantic can serialize."""

    return cast(dict[K, V], _FrozenDict(value))


def deep_freeze(value: object) -> object:
    """Copy recursively mutable containers into serialization-friendly immutable values."""

    if isinstance(value, Mapping):
        return freeze_mapping({key: deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(deep_freeze(item) for item in value)
    return value
