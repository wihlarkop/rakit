from rakit import (
    ActionDefinition,
    ActionScope,
    ActionSuccess,
    BulkExecutionPolicy,
    BulkPolicy,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
)
from rakit.core import BulkActionOutcome, BulkItemOutcome, BulkItemStatus, BulkSelection, BulkTarget
from rakit_core.actions import DomainActionExecutor
from rakit_core.identity import RecordIdentity


def test_public_facade_exposes_resource_composition_and_bulk_contracts() -> None:
    relationship = RelationshipDefinition(
        relationship_id="customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
    )
    action = ActionDefinition(
        action_id="archive",
        label="Archive",
        scope=ActionScope.BULK,
        resource_id="orders",
        executor=DomainActionExecutor(lambda _context: ActionSuccess()),
        bulk_policy=BulkPolicy(
            execution=BulkExecutionPolicy.BEST_EFFORT,
            require_concurrency_snapshot=False,
        ),
    )
    target = BulkTarget(RecordIdentity(values={"id": 1}), {"id": 1})
    selection = BulkSelection((target,))
    outcome = BulkActionOutcome(
        execution=BulkExecutionPolicy.BEST_EFFORT,
        items=(BulkItemOutcome(target.identity, BulkItemStatus.SUCCEEDED),),
    )

    assert relationship.effective_writable is True
    assert action.bulk_policy is not None
    assert selection.identities == (target.identity,)
    assert outcome.all_succeeded is True
