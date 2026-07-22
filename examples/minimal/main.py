"""Minimal read-only Rakit application using an in-memory data source."""

from dataclasses import dataclass
from typing import Any

from rakit import Admin, ResourceAdmin, SecretValue

_PRODUCTS: tuple[dict[str, object], ...] = (
    {"id": 1, "name": "Bench Clamp", "category": "Workshop"},
    {"id": 2, "name": "Soldering Iron", "category": "Electronics"},
    {"id": 3, "name": "Wire Cutter", "category": "Electronics"},
)


@dataclass(frozen=True)
class _Page:
    items: tuple[dict[str, object], ...]
    page: int
    per_page: int
    has_previous: bool
    has_next: bool
    total_count: int | None


def _matches(item: dict[str, object], filter_: Any) -> bool:
    actual = item.get(filter_.field)
    operator = filter_.operator.value
    expected = filter_.value
    if operator == "eq":
        return str(actual) == str(expected)
    if operator == "neq":
        return str(actual) != str(expected)
    if operator == "contains":
        return str(expected).casefold() in str(actual).casefold()
    if operator == "in":
        return str(actual) in {str(value) for value in expected}
    if operator == "is_null":
        return (actual is None) is bool(expected)
    return False


class ProductDataSource:
    """Small read-only data source demonstrating the public structural contract."""

    capabilities = type("Capabilities", (), {"read": True})()
    fields = ("id", "name", "category")
    identity_fields = ("id",)

    async def list(self, query: Any) -> _Page:
        items = list(_PRODUCTS)
        for filter_ in query.filters:
            items = [item for item in items if _matches(item, filter_)]
        if query.search:
            needle = query.search.casefold()
            items = [
                item
                for item in items
                if any(needle in str(value).casefold() for value in item.values())
            ]
        for sort in reversed(query.sorting):
            items.sort(
                key=lambda item: item.get(sort.field),
                reverse=sort.direction.value == "desc",
            )

        start = query.pagination.offset
        end = start + query.pagination.per_page
        page_items = tuple(items[start:end])
        total_count = len(items) if query.count_policy.value == "exact" else None
        return _Page(
            items=page_items,
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=query.pagination.page > 1,
            has_next=end < len(items),
            total_count=total_count,
        )

    async def count(self, query: Any) -> int:
        items = list(_PRODUCTS)
        for filter_ in query.filters:
            items = [item for item in items if _matches(item, filter_)]
        if query.search:
            needle = query.search.casefold()
            items = [
                item
                for item in items
                if any(needle in str(value).casefold() for value in item.values())
            ]
        return len(items)

    async def detail(self, identity: Any) -> dict[str, object] | None:
        wanted = identity.values["id"]
        return next((item for item in _PRODUCTS if item["id"] == wanted), None)


class ProductAdmin(ResourceAdmin):
    resource_id = "products"
    path = "/products"
    label = "Products"
    singular_label = "Product"
    data_source = ProductDataSource()
    list_fields = ("id", "name", "category")
    detail_fields = ("id", "name", "category")
    filter_fields = ("id", "name", "category")
    search_fields = ("name",)
    sort_fields = ("id", "name", "category")


admin = Admin(
    admin_id="catalog",
    title="Product catalogue",
    debug=False,
    secret_key=SecretValue("example-only-change-me-000000000"),
)
admin.register(ProductAdmin)
app = admin.asgi()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
