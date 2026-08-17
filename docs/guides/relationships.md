# Relationships

Relationships are declared on the source `ResourceAdmin` with portable `RelationshipDefinition`
objects. Rakit's core does not depend on SQLAlchemy relationship objects; an adapter validates the
declaration against its own metadata.

Supported alpha relationship kinds are:

- `MANY_TO_ONE`
- `ONE_TO_ONE`
- `ONE_TO_MANY`
- `MANY_TO_MANY`
- `ASSOCIATION_OBJECT`

A declaration separates structure from editing policy. `cardinality`, `nullable`, `ordered`,
`edit_mode`, `writable`, permissions, and destructive policy are explicit. Mapper cascade settings
do not silently grant destructive UI behavior.

Association objects declare both the association resource and its target resource plus the scalar
association fields that may be exposed. Ordered relationships require an explicit position field.

For the portable declaration surface see `examples/relationships`. The repository integration
suite demonstrates the writable SQLAlchemy forms for link/unlink, inline child edits, ordering,
association scalar updates, and confirmed destructive operations.
