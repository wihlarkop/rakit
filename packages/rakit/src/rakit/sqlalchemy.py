from ._optional import optional_import

with optional_import("rakit_sqlalchemy", extra="sqlalchemy"):
    import rakit_sqlalchemy  # noqa: F401

from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_sqlalchemy.relationship_mutations import SQLAlchemyRelationshipResolver
from rakit_sqlalchemy.relationships import inspect_relationships
from rakit_sqlalchemy.uow import SQLAlchemyUnitOfWork

__all__ = [
    "SQLAlchemyMutationService",
    "SQLAlchemyPlugin",
    "SQLAlchemyRelationshipResolver",
    "SQLAlchemyUnitOfWork",
    "inspect_relationships",
]
