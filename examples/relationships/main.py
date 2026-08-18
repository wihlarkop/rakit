"""Official relationship declarations example using public Rakit contracts only."""

from __future__ import annotations

from dataclasses import dataclass

from rakit import (
    Admin,
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipKind,
    ResourceAdmin,
)
from rakit.core import (
    DataSourceCapabilities,
    PagePagination,
    PageResult,
    RecordIdentity,
    ResourceQuery,
)


@dataclass(frozen=True)
class DemoRecord:
    id: int
    name: str


class DemoDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    def __init__(self, *records: DemoRecord) -> None:
        self.records = records

    def identity_for(self, record: DemoRecord) -> RecordIdentity:
        return RecordIdentity(values={"id": record.id})

    async def list(self, query: ResourceQuery) -> PageResult[DemoRecord]:
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("DemoDataSource supports page-number pagination only")
        start = pagination.offset
        items = self.records[start : start + pagination.per_page]
        return PageResult(
            items=items,
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=pagination.page > 1,
            has_next=start + len(items) < len(self.records),
            total_count=len(self.records),
        )

    async def count(self, query: ResourceQuery) -> int:
        return len(self.records)

    async def detail(self, identity: RecordIdentity) -> DemoRecord | None:
        wanted = int(identity.values["id"])
        return next((record for record in self.records if record.id == wanted), None)

    def validate_relationship(
        self,
        definition: RelationshipDefinition,
        target_data_source: object,
        association_target_data_source: object | None,
    ) -> None:
        # A custom adapter may validate richer mapper metadata here. This demo
        # deliberately accepts the explicit portable declarations below.
        del definition, target_data_source, association_target_data_source


CUSTOMERS = DemoDataSource(DemoRecord(1, "Ada"), DemoRecord(2, "Grace"))
TAGS = DemoDataSource(DemoRecord(1, "Priority"), DemoRecord(2, "International"))
LINE_ITEMS = DemoDataSource(DemoRecord(1, "Keyboard"), DemoRecord(2, "Display"))
ENROLLMENTS = DemoDataSource(DemoRecord(1, "Ada / Python"))
COURSES = DemoDataSource(DemoRecord(1, "Python"), DemoRecord(2, "Databases"))
ORDERS = DemoDataSource(DemoRecord(1, "Order 1001"), DemoRecord(2, "Order 1002"))


class CustomersAdmin(ResourceAdmin):
    resource_id = "customers"
    path = "/customers"
    label = "Customers"
    singular_label = "Customer"
    data_source = CUSTOMERS
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


class TagsAdmin(ResourceAdmin):
    resource_id = "tags"
    path = "/tags"
    label = "Tags"
    singular_label = "Tag"
    data_source = TAGS
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


class LineItemsAdmin(ResourceAdmin):
    resource_id = "line_items"
    path = "/line-items"
    label = "Line items"
    singular_label = "Line item"
    data_source = LINE_ITEMS
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


class EnrollmentsAdmin(ResourceAdmin):
    resource_id = "enrollments"
    path = "/enrollments"
    label = "Enrollments"
    singular_label = "Enrollment"
    data_source = ENROLLMENTS
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


class CoursesAdmin(ResourceAdmin):
    resource_id = "courses"
    path = "/courses"
    label = "Courses"
    singular_label = "Course"
    data_source = COURSES
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


class OrdersAdmin(ResourceAdmin):
    resource_id = "orders"
    path = "/orders"
    label = "Orders"
    singular_label = "Order"
    data_source = ORDERS
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    relationships = (
        RelationshipDefinition(
            relationship_id="customer",
            label="Customer",
            target_resource="customers",
            cardinality=RelationshipCardinality.TO_ONE,
            kind=RelationshipKind.DIRECT,
        ),
        RelationshipDefinition(
            relationship_id="tags",
            label="Tags",
            target_resource="tags",
            cardinality=RelationshipCardinality.TO_MANY,
            kind=RelationshipKind.DIRECT,
        ),
        RelationshipDefinition(
            relationship_id="line_items",
            label="Line items",
            target_resource="line_items",
            cardinality=RelationshipCardinality.TO_MANY,
            kind=RelationshipKind.DIRECT,
        ),
    )


class CustomersWithCoursesAdmin(ResourceAdmin):
    resource_id = "customers_with_courses"
    path = "/customers-with-courses"
    label = "Customers with courses"
    singular_label = "Customer with courses"
    data_source = CUSTOMERS
    list_fields = ("id", "name")
    detail_fields = ("id", "name")
    relationships = (
        RelationshipDefinition(
            relationship_id="courses",
            label="Courses",
            target_resource="courses",
            association_resource="enrollments",
            cardinality=RelationshipCardinality.TO_MANY,
            kind=RelationshipKind.ASSOCIATION,
        ),
    )


admin = Admin(title="Relationships demo", debug=True)
admin.register(CustomersAdmin)
admin.register(TagsAdmin)
admin.register(LineItemsAdmin)
admin.register(EnrollmentsAdmin)
admin.register(CoursesAdmin)
admin.register(OrdersAdmin)
admin.register(CustomersWithCoursesAdmin)
app = admin.asgi()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)