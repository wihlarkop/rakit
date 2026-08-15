"""Unified, backend-neutral action definitions and execution for Plan 05 Task 4.

An action is a named, permission-bound, typed operation attached to one
``ActionScope``.  Availability answers "should this action be presented and
enabled for the current state"; authorization answers "may this principal
execute it".  The two are deliberately independent, and POST execution always
re-evaluates both against freshly loaded state.

This module is framework-neutral: no Starlette, SQLAlchemy, or web types appear
here.  The web layer translates ``ActionDefinition`` and ``ActionResult`` into
HTTP/HTML/HTMX behavior.
"""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from rakit_core.auth import Principal
from rakit_core.bulk import BulkPolicy
from rakit_core.config import MachineId
from rakit_core.forms import FormIssue, FormSchema, FormState
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import OperationAuthorization
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import TransactionPolicy


class ActionScope(StrEnum):
    PAGE = "page"
    RESOURCE = "resource"
    RECORD = "record"
    BULK = "bulk"


class ActionAvailability(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    HIDDEN = "hidden"


class ActionResponseKind(StrEnum):
    """Explicit non-JSON response categories; adapters own concrete responses."""

    FILE = "file"
    STREAM = "stream"
    ADVANCED = "advanced"


@dataclass(frozen=True)
class ActionSuccess[TActionPayload]:
    payload: TActionPayload | None = None
    message: str | None = None


@dataclass(frozen=True)
class ActionRejected:
    """An expected validation or business-policy rejection, not an exception."""

    errors: Mapping[str, str]
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.errors and self.message is None:
            raise ValueError("A rejected action result requires errors or a message")


@dataclass(frozen=True)
class ActionRedirect:
    location: str
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.location.startswith("/"):
            raise ValueError("Action redirect locations must be absolute application paths")


@dataclass(frozen=True)
class ActionRefresh:
    target: str
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("Action refresh target must not be empty")


@dataclass(frozen=True)
class ActionRendered[TActionPayload]:
    """A named semantic fragment; core intentionally has no template engine."""

    fragment: str
    payload: TActionPayload | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.fragment:
            raise ValueError("Action rendered fragment must not be empty")


@dataclass(frozen=True)
class ActionAdvancedResponse:
    """An explicit opt-in escape hatch, never a framework response object."""

    kind: ActionResponseKind
    payload: Any


@dataclass(frozen=True)
class ActionValidation:
    """Normalized field-local validation failure for typed action input."""

    issues: tuple[FormIssue, ...] = ()


type ActionResult[TActionPayload] = (
    ActionSuccess[TActionPayload]
    | ActionRejected
    | ActionRedirect
    | ActionRefresh
    | ActionRendered[TActionPayload]
    | ActionAdvancedResponse
    | ActionValidation
)


@dataclass(frozen=True)
class ActionAvailabilityDecision:
    """Typed availability answer with an optional safe human-facing reason."""

    availability: ActionAvailability
    reason: str | None = None

    @classmethod
    def available(cls) -> "ActionAvailabilityDecision":
        return cls(ActionAvailability.AVAILABLE)

    @classmethod
    def disabled(cls, reason: str) -> "ActionAvailabilityDecision":
        return cls(ActionAvailability.DISABLED, reason)

    @classmethod
    def hidden(cls) -> "ActionAvailabilityDecision":
        return cls(ActionAvailability.HIDDEN)


@dataclass(frozen=True)
class ActionPreview:
    """Authoritative, non-persisting preview content for confirmation flows."""

    title: str
    description: str
    impact: str | None = None


@dataclass(frozen=True)
class ActionContext:
    """Everything an availability resolver, preview, or executor may need.

    ``record`` is an opaque object loaded through the resource's canonical
    scoped query by the execution layer; actions never load records
    themselves and never trust GET-time state.
    """

    definition: "ActionDefinition"
    scope: ActionScope
    identity: RecordIdentity | None = None
    record: object | None = None
    submitted: Mapping[str, object] = field(default_factory=dict)
    values: FormState | None = None
    authorization: OperationAuthorization | None = None
    availability: ActionAvailabilityDecision = field(
        default_factory=ActionAvailabilityDecision.available
    )
    principal: Principal | None = None
    concurrency_token: str | None = None
    confirmation_token: str | None = None


@runtime_checkable
class ActionAvailabilityResolver(Protocol):
    """Resolves availability; may be synchronous or asynchronous."""

    def __call__(
        self, context: ActionContext
    ) -> ActionAvailabilityDecision | Awaitable[ActionAvailabilityDecision]: ...


@runtime_checkable
class ActionPreviewResolver(Protocol):
    """Resolves authoritative preview content; sync or async."""

    def __call__(self, context: ActionContext) -> ActionPreview | Awaitable[ActionPreview]: ...


@runtime_checkable
class ActionExecutor(Protocol):
    """Executes an action and returns a structured result."""

    async def execute(self, context: ActionContext) -> ActionResult[Any]: ...


class ActionDefinition(BaseModel):
    """One immutable, typed, permission-bound action declaration.

    This is the single canonical action contract shared by the compiler,
    the permission catalogue, the public API, and the web runtime.  It is
    framework-neutral: no Starlette, SQLAlchemy, or web types appear here.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    action_id: MachineId
    label: str
    scope: ActionScope
    permission: PermissionRequirement | None = None
    description: str | None = None
    resource_id: MachineId | None = None
    page_id: MachineId | None = None
    input_schema: FormSchema | None = None
    availability: ActionAvailabilityResolver | None = None
    preview: ActionPreviewResolver | None = None
    executor: ActionExecutor | None = None
    needs_form: bool = False
    needs_preview: bool = False
    needs_confirmation: bool = False
    requires_concurrency: bool = False
    mutating: bool = False
    transaction_policy: TransactionPolicy = TransactionPolicy.READ_ONLY
    bulk_policy: BulkPolicy | None = None

    @model_validator(mode="after")
    def _validate_action_contract(self) -> "ActionDefinition":
        if not self.label.strip():
            raise ValueError("Action label must not be empty")
        _validate_operation_transaction_policy(self.mutating, self.transaction_policy)
        if self.scope is ActionScope.PAGE:
            if self.page_id is None:
                raise ValueError("PAGE actions require page_id")
            if self.resource_id is not None:
                raise ValueError("PAGE actions cannot also declare resource_id")
        else:
            if self.resource_id is None:
                raise ValueError("Resource, record, and bulk actions require resource_id")
            if self.page_id is not None:
                raise ValueError("Only PAGE actions may declare page_id")
        if self.scope is ActionScope.BULK and self.bulk_policy is None:
            object.__setattr__(self, "bulk_policy", BulkPolicy())
        if self.scope is not ActionScope.BULK and self.bulk_policy is not None:
            raise ValueError("Only BULK actions may declare bulk_policy")
        if self.requires_concurrency and self.scope is not ActionScope.RECORD:
            raise ValueError(
                f"Action {self.action_id!r} concurrency is only valid for RECORD scope "
                "(Task 5 owns bulk concurrency snapshots)"
            )
        if self.executor is None:
            raise ValueError(f"Action {self.action_id!r} requires an executor")
        if self.needs_form and self.input_schema is None:
            raise ValueError(f"Action {self.action_id!r} needs a form but has no input schema")
        if self.needs_preview and self.preview is None:
            raise ValueError(f"Action {self.action_id!r} needs a preview resolver")
        if self.needs_confirmation and not self.needs_preview:
            raise ValueError(f"Action {self.action_id!r} confirmation requires a preview step")
        if self.needs_confirmation and self.input_schema is not None:
            raise ValueError(f"Action {self.action_id!r} confirmation flows do not take form input")
        return self


def _validate_operation_transaction_policy(
    mutating: bool, transaction_policy: TransactionPolicy
) -> None:
    if mutating and transaction_policy is TransactionPolicy.READ_ONLY:
        raise ValueError("Mutating operations cannot use a read-only transaction policy")
    if not mutating and transaction_policy is TransactionPolicy.AUTO:
        raise ValueError("Read-only operations cannot use an automatic write transaction")


@dataclass(frozen=True)
class ActionSet:
    """Immutable registration of one owner's actions with unique ids."""

    actions: tuple[ActionDefinition, ...]

    def __post_init__(self) -> None:
        ids = tuple(action.action_id for action in self.actions)
        if len(ids) != len(set(ids)):
            duplicates = sorted({action_id for action_id in ids if ids.count(action_id) > 1})
            raise ValueError("Duplicate action ids in one action set: " + ", ".join(duplicates))

    def get(self, action_id: str) -> ActionDefinition | None:
        for action in self.actions:
            if action.action_id == action_id:
                return action
        return None


class DomainActionExecutor:
    """Execute a typed domain/application callable within the operation context.

    The callable may be synchronous or asynchronous; it receives the full
    ``ActionContext`` (scoped record, parsed values, authorization) and must
    return an ``ActionResult``.  Transaction ownership remains with the
    execution layer/UoW the callable participates in.
    """

    def __init__(
        self,
        handler: Callable[[ActionContext], ActionResult[Any] | Awaitable[ActionResult[Any]]],
    ) -> None:
        if not callable(handler):
            raise TypeError("Domain action handler must be callable")
        self._handler = handler

    async def execute(self, context: ActionContext) -> ActionResult[Any]:
        result = self._handler(context)
        if inspect.isawaitable(result):
            result = await result
        return cast(ActionResult[Any], result)


class PreparedMutationExecutor:
    """Reuse the existing mutation foundation without coupling to adapters.

    ``prepare`` derives an opaque mutation plan from the action context;
    ``commit`` applies that plan through the adapter's existing mutation
    service inside its own operation-scoped unit of work.  This lets a record
    action (e.g. "Approve Order") reuse the normal update pipeline instead of
    writing ORM objects directly.
    """

    def __init__(
        self,
        prepare: Callable[[ActionContext], object | Awaitable[object]],
        commit: Callable[[object, ActionContext], ActionResult[Any] | Awaitable[ActionResult[Any]]],
    ) -> None:
        if not callable(prepare) or not callable(commit):
            raise TypeError("Mutation plan prepare and commit must be callable")
        self._prepare = prepare
        self._commit = commit

    async def execute(self, context: ActionContext) -> ActionResult[Any]:
        plan = self._prepare(context)
        if inspect.isawaitable(plan):
            plan = await plan
        result = self._commit(plan, context)
        if inspect.isawaitable(result):
            result = await result
        return cast(ActionResult[Any], result)


def action_permission_requirement(
    action_id: str, *, admin_id: str = "admin"
) -> PermissionRequirement:
    """The approved compiled action permission key scheme."""
    return PermissionRequirement.all_of(f"{admin_id}.actions.{action_id}.execute")


async def resolve_availability(
    definition: ActionDefinition, context: ActionContext
) -> ActionAvailabilityDecision:
    """Resolve availability with a safe default of AVAILABLE."""
    resolver = definition.availability
    if resolver is None:
        return ActionAvailabilityDecision.available()
    decision = resolver(context)
    if inspect.isawaitable(decision):
        decision = await decision
    return cast(ActionAvailabilityDecision, decision)


async def resolve_preview(
    definition: ActionDefinition, context: ActionContext
) -> ActionPreview | None:
    if definition.preview is None:
        return None
    preview = definition.preview(context)
    if inspect.isawaitable(preview):
        preview = await preview
    return cast(ActionPreview | None, preview)


__all__ = [
    "ActionAdvancedResponse",
    "ActionAvailability",
    "ActionAvailabilityDecision",
    "ActionAvailabilityResolver",
    "ActionContext",
    "ActionDefinition",
    "ActionExecutor",
    "ActionPreview",
    "ActionPreviewResolver",
    "ActionRedirect",
    "ActionRefresh",
    "ActionRejected",
    "ActionRendered",
    "ActionResponseKind",
    "ActionResult",
    "ActionScope",
    "ActionSet",
    "ActionSuccess",
    "ActionValidation",
    "DomainActionExecutor",
    "PreparedMutationExecutor",
    "action_permission_requirement",
    "resolve_availability",
    "resolve_preview",
]
