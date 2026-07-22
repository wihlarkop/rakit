from .datasource import DataSource


class ResourceAdmin:
    """Declaration-style base class for registering a resource with `Admin`.

    Subclasses set class attributes only -- instances are never constructed.
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
    data_source: "DataSource | None" = None


class ModelAdmin(ResourceAdmin):
    """A `ResourceAdmin` backed by a model claimed by an installed adapter."""

    model: type[object]
