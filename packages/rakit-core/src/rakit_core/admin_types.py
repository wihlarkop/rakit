from typing import TYPE_CHECKING

from .datasource import DataSource
from .filters import ResourceFilter
from .generated_api import ResourceApiDefinition

if TYPE_CHECKING:
    from .actions import ActionDefinition
    from .relationships import RelationshipDefinition


class ResourceAdmin:
    """Declaration-style base class for registering a resource with `Admin`.

    Subclasses set class attributes only -- instances are never constructed.
    Relationships, actions, generated API policy, and query configuration
    declared here are copied into canonical core definitions during
    ``Admin.register``; the compiler remains the single authority for
    ownership, permissions, compatibility, and collisions.
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
    relationships: tuple["RelationshipDefinition", ...] = ()
    actions: tuple["ActionDefinition", ...] = ()
    api: ResourceApiDefinition = ResourceApiDefinition()
    data_source: "DataSource | None" = None


class ModelAdmin(ResourceAdmin):
    """A `ResourceAdmin` backed by a model claimed by an installed adapter."""

    model: type[object]
