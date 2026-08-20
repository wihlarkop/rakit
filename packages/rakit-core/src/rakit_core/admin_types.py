from dataclasses import dataclass
from typing import TYPE_CHECKING

from .datasource import DataSource
from .filters import ResourceFilter
from .forms import FormSchema
from .generated_api import ResourceApiDefinition
from .pagination import ResourcePaginationPolicy

if TYPE_CHECKING:
    from .actions import ActionDefinition
    from .relationships import RelationshipDefinition


@dataclass(frozen=True, slots=True)
class ResourceWriteDefinition:
    """Explicit ordinary-CRUD policy for one registered resource.

    The declaration is intentionally narrower than an ORM model: the form
    schema and writable allowlist stay application-owned, while the selected
    adapter decides whether it can materialize a concrete mutation service.
    """

    form_schema: FormSchema
    writable_fields: tuple[str, ...]
    version_field: str | None = None
    success_message: str | None = None
    htmx_refresh_targets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.form_schema, FormSchema):
            raise TypeError("form_schema must be a FormSchema")
        if (
            not isinstance(self.writable_fields, tuple)
            or not self.writable_fields
            or any(
                not isinstance(field_id, str) or not field_id or field_id != field_id.strip()
                for field_id in self.writable_fields
            )
        ):
            raise ValueError("writable_fields must be a non-empty tuple of non-empty strings")
        if len(set(self.writable_fields)) != len(self.writable_fields):
            raise ValueError("writable_fields must be unique")

        fields = {field.field_id: field for field in self.form_schema.fields}
        unknown = tuple(field_id for field_id in self.writable_fields if field_id not in fields)
        if unknown:
            raise ValueError(
                "writable_fields references unknown form fields: " + ", ".join(unknown)
            )
        non_writable = tuple(
            field_id for field_id in self.writable_fields if not fields[field_id].writable
        )
        if non_writable:
            raise ValueError(
                "writable_fields references non-writable form fields: "
                + ", ".join(non_writable)
            )

        if self.version_field is not None and (
            not isinstance(self.version_field, str)
            or not self.version_field
            or self.version_field != self.version_field.strip()
        ):
            raise ValueError("version_field must be None or a non-empty string")
        if self.success_message is not None and (
            not isinstance(self.success_message, str) or not self.success_message.strip()
        ):
            raise ValueError("success_message must be None or a non-empty string")
        if (
            not isinstance(self.htmx_refresh_targets, tuple)
            or any(
                not isinstance(target, str) or not target or target != target.strip()
                for target in self.htmx_refresh_targets
            )
            or len(set(self.htmx_refresh_targets)) != len(self.htmx_refresh_targets)
        ):
            raise ValueError("htmx_refresh_targets must contain unique non-empty strings")


class ResourceAdmin:
    """Declaration-style base class for registering a resource with `Admin`.

    Subclasses set class attributes only -- instances are never constructed.
    Relationships, actions, generated API policy, query configuration, and
    optional explicit write policy declared here are copied into canonical
    runtime definitions during ``Admin.register``; the compiler remains the
    authority for ownership, permissions, compatibility, and collisions.
    """

    resource_id: str
    path: str
    label: str
    singular_label: str
    list_fields: tuple[str, ...]
    detail_fields: tuple[str, ...]
    filter_fields: tuple[str, ...] = ()
    filters: tuple[ResourceFilter, ...] = ()
    search_fields: tuple[str, ...] = ()
    sort_fields: tuple[str, ...] = ()
    pagination: ResourcePaginationPolicy = ResourcePaginationPolicy()
    relationships: tuple["RelationshipDefinition", ...] = ()
    actions: tuple["ActionDefinition", ...] = ()
    api: ResourceApiDefinition = ResourceApiDefinition()
    data_source: "DataSource | None" = None
    write: ResourceWriteDefinition | None = None


class ModelAdmin(ResourceAdmin):
    """A `ResourceAdmin` backed by a model claimed by an installed adapter."""

    model: type[object]
