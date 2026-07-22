from dataclasses import dataclass

from sqlalchemy import inspect


@dataclass(frozen=True)
class ModelMetadata:
    identity_field: str
    fields: tuple[str, ...]


def inspect_model(model: type[object]) -> ModelMetadata:
    mapper = inspect(model)
    # `inspect()` raises on failure by default (raiseerr=True), but its return
    # type is `Any | None` regardless of the input; assert to narrow it for
    # the type checker rather than silencing the whole function.
    assert mapper is not None
    primary_keys = tuple(column.key for column in mapper.primary_key)
    if len(primary_keys) != 1:
        raise ValueError("SQLAlchemy v0.1 requires one primary-key column")
    return ModelMetadata(
        identity_field=primary_keys[0],
        fields=tuple(column.key for column in mapper.columns),
    )
