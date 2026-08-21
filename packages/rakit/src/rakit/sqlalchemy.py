from ._install import InstallExtra
from ._optional import OptionalDependency, optional_import

_DEPENDENCY = OptionalDependency(
    extra=InstallExtra.SQLALCHEMY,
    label="SQLAlchemy",
)

with optional_import("rakit_sqlalchemy", dependency=_DEPENDENCY):
    import rakit_sqlalchemy  # noqa: F401

from rakit_sqlalchemy.action_mutations import SQLAlchemyActionUpdateExecutor
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_sqlalchemy.relationship_mutations import SQLAlchemyRelationshipResolver
from rakit_sqlalchemy.relationships import inspect_relationships
from rakit_sqlalchemy.uow import SQLAlchemyUnitOfWork

__all__ = [
    "SQLAlchemyActionUpdateExecutor",
    "SQLAlchemyMutationService",
    "SQLAlchemyPlugin",
    "SQLAlchemyRelationshipResolver",
    "SQLAlchemyUnitOfWork",
    "inspect_relationships",
]
