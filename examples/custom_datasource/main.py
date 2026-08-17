"""Official custom DataSource example."""

from __future__ import annotations

from dataclasses import dataclass

from rakit import Admin, ResourceAdmin
from rakit.core import (
    CountPolicy,
    DataSourceCapabilities,
    PageResult,
    RecordIdentity,
    ResourceQuery,
)


@dataclass(frozen=True)
class Ticket:
    id: int
    title: str
    state: str


TICKETS = (
    Ticket(1, "Rotate signing keys", "open"),
    Ticket(2, "Review audit export", "closed"),
    Ticket(3, "Upgrade worker pool", "open"),
)


class TicketDataSource:
    """Read-only adapter with an explicit capability declaration."""

    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "title", "state")
    identity_fields = ("id",)

    def identity_for(self, record: Ticket) -> RecordIdentity:
        return RecordIdentity(values={"id": record.id})

    async def list(self, query: ResourceQuery) -> PageResult[Ticket]:
        visible = list(TICKETS)
        if query.search:
            needle = query.search.casefold()
            visible = [ticket for ticket in visible if needle in ticket.title.casefold()]
        for filter_ in query.filters:
            if filter_.operator.value == "eq":
                visible = [
                    ticket
                    for ticket in visible
                    if str(getattr(ticket, filter_.field)) == str(filter_.value)
                ]
        for sort in reversed(query.sorting):
            visible.sort(
                key=lambda ticket: getattr(ticket, sort.field),
                reverse=sort.direction.value == "desc",
            )

        start = query.pagination.offset
        items = tuple(visible[start : start + query.pagination.per_page])
        total = len(visible) if query.count_policy is CountPolicy.EXACT else None
        return PageResult(
            items=items,
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=query.pagination.page > 1,
            has_next=start + len(items) < len(visible),
            total_count=total,
        )

    async def count(self, query: ResourceQuery) -> int:
        # Keep this method semantically aligned with list() for deferred counts.
        visible = list(TICKETS)
        if query.search:
            needle = query.search.casefold()
            visible = [ticket for ticket in visible if needle in ticket.title.casefold()]
        for filter_ in query.filters:
            if filter_.operator.value == "eq":
                visible = [
                    ticket
                    for ticket in visible
                    if str(getattr(ticket, filter_.field)) == str(filter_.value)
                ]
        return len(visible)

    async def detail(self, identity: RecordIdentity) -> Ticket | None:
        wanted = int(identity.values["id"])
        return next((ticket for ticket in TICKETS if ticket.id == wanted), None)


class TicketAdmin(ResourceAdmin):
    resource_id = "tickets"
    path = "/tickets"
    label = "Tickets"
    singular_label = "Ticket"
    data_source = TicketDataSource()
    list_fields = ("id", "title", "state")
    detail_fields = ("id", "title", "state")
    filter_fields = ("state",)
    search_fields = ("title",)
    sort_fields = ("id", "title", "state")


admin = Admin(title="Custom DataSource demo", debug=True)
admin.register(TicketAdmin)
app = admin.asgi()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
