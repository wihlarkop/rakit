from typing import TYPE_CHECKING

from .datasource import DataSource

if TYPE_CHECKING:
    from .actions import ActionDefinition
    from .relationships import RelationshipDefinition


class ResourceAdmin:
    """Declaration-style base class for registering a resource with `Admin`.

    Subclasses set class attributes only -- instances are never constructed.
    Relationships and resource-owned actions declared here are copied into the
    canonical core definitions during ``Admin.register``; the compiler remains
    the single authority for ownership, permissions, routes, and collisions.
    """

    resource_id: str
    path: str
    label: str
    singular_label: str
    list_fields: tuple[str, ...]
    detail_fields: tuple[str, ...]
    filter_fields: tuple[str, ...] = ()
    search_fields: tuple[str, ...] = ()
    sort_fields: tuple[str, ...] = ()
    relationships: tuple["RelationshipDefinition", ...] = ()
    actions: tuple["ActionDefinition", ...] = ()
    data_source: "DataSource | None" = None


class ModelAdmin(ResourceAdmin):
    """A `ResourceAdmin` backed by a model claimed by an installed adapter."""

    model: type[object]
