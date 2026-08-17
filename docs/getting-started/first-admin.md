# First Admin

The smallest useful Rakit application is an `Admin` plus one `ResourceAdmin` backed by a data
source. The data source is structural: it does not need to inherit from a Rakit base class.

```python runnable
from rakit import Admin, ResourceAdmin
from rakit.core import DataSourceCapabilities, PageResult, RecordIdentity


class Products:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query):
        return PageResult(
            items=({"id": 1, "name": "Clamp"},),
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=1,
        )

    async def count(self, query):
        return 1

    async def detail(self, identity: RecordIdentity):
        return {"id": 1, "name": "Clamp"} if identity.values["id"] in (1, "1") else None


class ProductAdmin(ResourceAdmin):
    resource_id = "products"
    path = "/products"
    label = "Products"
    singular_label = "Product"
    data_source = Products()
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


admin = Admin(title="Workshop", debug=True)
admin.register(ProductAdmin)
assert admin.compile().admin_id == "admin"
```

Save the application as `myapp.py`, then run:

```bash
rakit check myapp:admin
rakit run myapp:admin
```

The built-in HTML is server-rendered. HTMX enhances supported interactions but is not required for
the core page flow.
