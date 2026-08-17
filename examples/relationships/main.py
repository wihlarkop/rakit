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
from rakit.core import DataSourceCapabilities, PageResult, RecordIdentity, ResourceQuery


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
        start = query.pagination.offset
        items = self.records[start : start + query.pagination.per_page]
        return PageResult(
            items=items,
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=query.pagination.page > 1,
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


class CoursesAdmin(ResourceAdmin):
    resource_id = "courses"
    path = "/courses"
    label = "Courses"
    singular_label = "Course"
    data_source = COURSES
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
            target_resource_id="customers",
            label="Customer",
            kind=RelationshipKind.MANY_TO_ONE,
            cardinality=RelationshipCardinality.TO_ONE,
            nullable=True,
            record_label_field="name",
        ),
        RelationshipDefinition(
            relationship_id="tags",
            target_resource_id="tags",
            label="Tags",
            kind=RelationshipKind.MANY_TO_MANY,
            cardinality=RelationshipCardinality.TO_MANY,
            record_label_field="name",
        ),
        RelationshipDefinition(
            relationship_id="line_items",
            target_resource_id="line_items",
            label="Line items",
            kind=RelationshipKind.ONE_TO_MANY,
            cardinality=RelationshipCardinality.TO_MANY,
            record_label_field="name",
        ),
        RelationshipDefinition(
            relationship_id="enrollments",
            target_resource_id="enrollments",
            association_target_resource_id="courses",
            association_fields=("grade",),
            label="Course enrollments",
            kind=RelationshipKind.ASSOCIATION_OBJECT,
            cardinality=RelationshipCardinality.TO_MANY,
            record_label_field="name",
        ),
    )


admin = Admin(title="Relationships demo", debug=True)
for resource in (
    CustomersAdmin,
    TagsAdmin,
    LineItemsAdmin,
    CoursesAdmin,
    EnrollmentsAdmin,
    OrdersAdmin,
):
    admin.register(resource)

app = admin.asgi()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
