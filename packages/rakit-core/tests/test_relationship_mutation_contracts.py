from typing import Any, cast

import pytest
from rakit_core.identity import RecordIdentity
from rakit_core.permissions import PermissionRequirement
from rakit_core.relationship_mutations import (
    AssociationScalarChange,
    CreateRelated,
    DeleteRelated,
    LinkRelated,
    RelationshipCandidate,
    RelationshipChangePlan,
    RelationshipMutationKind,
    RelationshipMutationPlan,
    ReorderRelated,
    UnlinkRelated,
    UpdateRelated,
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
        cast(dict[str, Any], plan.association_changes[0].values)["quantity"] = 3


def test_relationship_mutation_plan_rejects_duplicate_or_unbound_association_targets() -> None:
    base: dict[str, Any] = {
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


def test_relationship_candidate_exposes_only_canonical_identity_and_plain_text_label() -> None:
    candidate = RelationshipCandidate(identity=_identity(2), label="Ada Lovelace")

    assert candidate.identity == _identity(2)
    assert candidate.label == "Ada Lovelace"


def test_graph_relationship_steps_are_typed_immutable_and_fingerprint_safe() -> None:
    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    change = RelationshipChangePlan(
        operation_id="graph:orders:items",
        relationship_id="items",
        authorization_requirement=requirement,
        concurrency_token="relationship-token",
        steps=(
            CreateRelated(values={"name": "new"}),
            UpdateRelated(
                identity=_identity(2), values={"name": "changed"}, concurrency_token="v2"
            ),
            LinkRelated(identity=_identity(3)),
            UnlinkRelated(identity=_identity(4)),
            DeleteRelated(
                identity=_identity(5), concurrency_token="v5", confirmation_token="confirm"
            ),
            ReorderRelated(identities=(_identity(3), _identity(2))),
        ),
    )

    assert change.fingerprint_payload["steps"] == [
        {"kind": "create", "values": {"name": "new"}},
        {
            "kind": "update",
            "identity": {"id": {"type": "int", "value": 2}},
            "values": {"name": "changed"},
        },
        {"kind": "link", "identity": {"id": {"type": "int", "value": 3}}},
        {"kind": "unlink", "identity": {"id": {"type": "int", "value": 4}}},
        {"kind": "delete", "identity": {"id": {"type": "int", "value": 5}}},
        {
            "kind": "reorder",
            "identities": [
                {"id": {"type": "int", "value": 3}},
                {"id": {"type": "int", "value": 2}},
            ],
        },
    ]
    with pytest.raises(TypeError):
        cast(dict[str, Any], cast(CreateRelated, change.steps[0]).values)["name"] = "forged"


def test_graph_relationship_steps_reject_empty_or_duplicate_reorder_input() -> None:
    requirement = PermissionRequirement.all_of("admin.resources.orders.update")
    with pytest.raises(ValueError, match="at least one"):
        RelationshipChangePlan(
            operation_id="graph:orders:items",
            relationship_id="items",
            authorization_requirement=requirement,
            steps=(),
        )
    with pytest.raises(ValueError, match="duplicate"):
        ReorderRelated(identities=(_identity(1), _identity(1)))
