import pytest
from rakit_core.identity import RecordIdentity
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import (
    AssociationScalarChange,
    RelationshipMutationKind,
    RelationshipMutationPlan,
)


def _identity(value: int) -> RecordIdentity:
    return RecordIdentity(values={"id": value})


def test_relationship_mutation_plan_is_immutable_canonical_and_fingerprint_stable() -> None:
    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    plan = RelationshipMutationPlan(
        operation_id="relationship:orders:items:replace",
        parent_resource_id="orders",
        parent_identity=_identity(1),
        relationship_id="items",
        kind=RelationshipMutationKind.REPLACE,
        target_identities=(_identity(3), _identity(2)),
        association_changes=(
            AssociationScalarChange(target_identity=_identity(2), values={"quantity": 2}),
        ),
        authorization_requirement=requirement,
        concurrency_token="concurrency-token",
        idempotency_token="submission-token",
    )

    equivalent = plan.model_copy(
        update={
            "target_identities": (_identity(2), _identity(3)),
            "association_changes": (
                AssociationScalarChange(target_identity=_identity(2), values={"quantity": 2}),
            ),
        }
    )

    assert plan.target_identities == (_identity(2), _identity(3))
    assert plan.association_changes[0].values == {"quantity": 2}
    assert plan.fingerprint == equivalent.fingerprint
    with pytest.raises(TypeError):
        plan.association_changes[0].values["quantity"] = 3  # type: ignore[index]


def test_relationship_mutation_plan_rejects_duplicate_or_unbound_association_targets() -> None:
    base = {
        "operation_id": "relationship:orders:items:add",
        "parent_resource_id": "orders",
        "parent_identity": _identity(1),
        "relationship_id": "items",
        "kind": RelationshipMutationKind.ADD,
        "authorization_requirement": PermissionRequirement.all_of("orders.update"),
    }

    with pytest.raises(ValueError, match="duplicate"):
        RelationshipMutationPlan(target_identities=(_identity(2), _identity(2)), **base)
    with pytest.raises(ValueError, match="target"):
        RelationshipMutationPlan(
            target_identities=(_identity(2),),
            association_changes=(
                AssociationScalarChange(target_identity=_identity(3), values={"quantity": 2}),
            ),
            **base,
        )
