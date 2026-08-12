"""Small immutable form state over Pydantic field validation."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import TypeAdapter

from rakit_core.fields import FieldDefinition, infer_field_security


@dataclass(frozen=True)
class FieldLayout:
    field_id: str


@dataclass(frozen=True)
class RelationshipPanel:
    layout_id: str
    relationship_id: str


@dataclass(frozen=True)
class CustomBlock:
    layout_id: str
    block_id: str


@dataclass(frozen=True)
class Column:
    children: tuple["LayoutNode", ...]


@dataclass(frozen=True)
class Row:
    children: tuple[Column, ...]


@dataclass(frozen=True)
class Section:
    layout_id: str
    title: str
    children: tuple["LayoutNode", ...]


@dataclass(frozen=True)
class CollapsibleGroup:
    layout_id: str
    label: str
    children: tuple["LayoutNode", ...]


@dataclass(frozen=True)
class Tab:
    layout_id: str
    label: str
    children: tuple["LayoutNode", ...]


@dataclass(frozen=True)
class Tabs:
    layout_id: str
    tabs: tuple[Tab, ...]


type LayoutNode = (
    FieldLayout | RelationshipPanel | CustomBlock | Column | Row | Section | CollapsibleGroup | Tabs
)


@dataclass(frozen=True)
class FormLayout:
    children: tuple[LayoutNode, ...]


def _frozen_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class FormIssue:
    field_id: str | None
    message: str


@dataclass(frozen=True)
class FormState(Mapping[str, Any]):
    initial: Mapping[str, Any]
    submitted: Mapping[str, Any]
    normalized: Mapping[str, Any]
    issues: tuple[FormIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    def __getitem__(self, key: str) -> Any:
        return self.normalized[key]

    def __iter__(self):
        return iter(self.normalized)

    def __len__(self) -> int:
        return len(self.normalized)


class FormValidationError(ValueError):
    def __init__(self, state: FormState) -> None:
        super().__init__("Form validation failed")
        self.state = state


@dataclass(frozen=True)
class FormSchema:
    fields: tuple[FieldDefinition, ...]
    layout: FormLayout | None = None
    update_layout: FormLayout | None = None

    def __post_init__(self) -> None:
        secured = tuple(infer_field_security(field) for field in self.fields)
        field_ids = tuple(field.field_id for field in secured)
        if len(set(field_ids)) != len(field_ids):
            raise ValueError("Form field ids must be unique")
        object.__setattr__(self, "fields", secured)
        for layout in (self.layout, self.update_layout):
            if layout is not None:
                _validate_layout(layout, frozenset(field_ids))

    def parse(
        self,
        submitted: Mapping[str, Any] | FormState,
        *,
        initial: Mapping[str, Any] | None = None,
    ) -> FormState:
        # Routes parse before deriving the canonical idempotency fingerprint.
        # The mutation executor consumes this immutable state directly so a
        # custom transport parser is never asked to parse its own output.
        if isinstance(submitted, FormState):
            return submitted
        known = {field.field_id: field for field in self.fields}
        unknown = set(submitted).difference(known)
        if unknown:
            raise ValueError("Unknown form field")

        values: dict[str, Any] = {}
        issues: list[FormIssue] = []
        for field in self.fields:
            if not field.writable and field.field_id in submitted:
                issues.append(FormIssue(field.field_id, "This field is read-only."))
                continue
            raw = submitted.get(field.field_id)
            if raw is None or raw == "":
                if field.required and not field.nullable:
                    issues.append(FormIssue(field.field_id, "This field is required."))
                elif field.nullable:
                    values[field.field_id] = None
                continue
            try:
                parsed = field.parser(raw) if field.parser is not None else raw
                values[field.field_id] = TypeAdapter(field.python_type).validate_python(parsed)
            except Exception:
                issues.append(FormIssue(field.field_id, "Invalid value."))

        state = FormState(
            initial=_frozen_mapping(initial or {}),
            submitted=_frozen_mapping(submitted),
            normalized=_frozen_mapping(values),
            issues=tuple(issues),
        )
        if state.issues:
            raise FormValidationError(state)
        return state

    def format_value(self, field_id: str, value: object) -> object:
        field = next(
            (candidate for candidate in self.fields if candidate.field_id == field_id), None
        )
        if field is None:
            raise ValueError("Unknown form field")
        if not field.readable or field.sensitive:
            return ""
        return field.formatter(value) if field.formatter is not None else value

    def resolved_layout(self, *, operation: str = "create") -> FormLayout:
        configured = self.update_layout if operation == "update" else None
        if configured is None:
            configured = self.layout
        if configured is not None:
            return configured
        return FormLayout(
            children=tuple(FieldLayout(field.field_id) for field in self.fields if field.writable)
        )


def _validate_layout(layout: FormLayout, field_ids: frozenset[str]) -> None:
    placed_fields: set[str] = set()
    layout_ids: set[str] = set()

    def visit(node: LayoutNode) -> None:
        if isinstance(node, FieldLayout):
            if node.field_id not in field_ids:
                raise ValueError("Layout references an unknown field")
            if node.field_id in placed_fields:
                raise ValueError("Layout places a field more than once")
            placed_fields.add(node.field_id)
            return
        if isinstance(node, RelationshipPanel | CustomBlock | Section | CollapsibleGroup | Tabs):
            if not node.layout_id or node.layout_id in layout_ids:
                raise ValueError("Layout ids must be unique and non-empty")
            layout_ids.add(node.layout_id)
        if isinstance(node, Column | Section | CollapsibleGroup):
            for child in node.children:
                visit(child)
        elif isinstance(node, Row):
            if not node.children:
                raise ValueError("Layout rows require at least one column")
            for column in node.children:
                visit(column)
        elif isinstance(node, Tabs):
            if not node.tabs:
                raise ValueError("Layout tabs require at least one tab")
            for tab in node.tabs:
                if not tab.layout_id or tab.layout_id in layout_ids:
                    raise ValueError("Layout ids must be unique and non-empty")
                layout_ids.add(tab.layout_id)
                for child in tab.children:
                    visit(child)

    for child in layout.children:
        visit(child)
