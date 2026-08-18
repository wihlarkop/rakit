from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from rakit import (
    Admin,
    ChoiceFilter,
    FilterChoice,
    FilterGroupPresentation,
    FilterPanelPresentation,
    ResourceAdmin,
    ResourceWebPresentation,
)
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.pagination import PagePagination, PageResult
from rakit_web.resource_presentation import resource_web_presentation


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "status")
    identity_fields = ("id",)

    async def list(self, query):
        pagination = query.pagination
        assert isinstance(pagination, PagePagination)
        return PageResult(
            items=({"id": 1, "status": "paid"},),
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=1,
        )

    async def count(self, query) -> int:
        del query
        return 1

    async def detail(self, identity: RecordIdentity):
        del identity
        return {"id": 1, "status": "paid"}


class _OrdersAdmin(ResourceAdmin):
    resource_id = "orders"
    path = "/orders"
    label = "Orders"
    singular_label = "Order"
    data_source = _DataSource()
    list_fields = ("id", "status")
    detail_fields = ("id", "status")
    filters = (
        ChoiceFilter(
            filter_id="status",
            label="Status",
            field="status",
            choices=(
                FilterChoice(value="paid", label="Paid"),
                FilterChoice(value="pending", label="Pending review"),
            ),
        ),
    )


def test_filter_panel_presentation_defaults_and_group_overrides_are_immutable() -> None:
    group = FilterGroupPresentation(
        expanded_by_default=False,
        choice_preview_count=10,
    )
    policy = FilterPanelPresentation(groups={"status": group})

    assert policy.visible_by_default is True
    assert policy.collapse_after == 4
    assert policy.choice_collapse_after == 8
    assert policy.choice_preview_count == 6
    assert policy.groups["status"] is group

    mutable_view = cast(Any, policy.groups)
    with pytest.raises(TypeError):
        mutable_view["other"] = group


def test_filter_panel_presentation_rejects_invalid_thresholds_and_group_ids() -> None:
    with pytest.raises(ValueError, match="collapse_after"):
        FilterPanelPresentation(collapse_after=-1)
    with pytest.raises(ValueError, match="collapse threshold"):
        FilterPanelPresentation(choice_collapse_after=0)
    with pytest.raises(ValueError, match="preview count"):
        FilterPanelPresentation(choice_preview_count=0)
    with pytest.raises(ValueError, match="cannot exceed"):
        FilterPanelPresentation(choice_collapse_after=4, choice_preview_count=5)
    with pytest.raises(ValueError, match="group ids"):
        FilterPanelPresentation(groups={"": FilterGroupPresentation()})
    invalid_groups = cast(Any, {"status": object()})
    with pytest.raises(TypeError, match="FilterGroupPresentation"):
        FilterPanelPresentation(groups=invalid_groups)


def test_public_admin_register_binds_web_presentation_without_changing_resource_definition() -> (
    None
):
    presentation = ResourceWebPresentation(
        filters=FilterPanelPresentation(
            groups={"status": FilterGroupPresentation(expanded_by_default=False)}
        )
    )
    admin = Admin(title="Presentation test", debug=True)
    admin.register(_OrdersAdmin, web=presentation)

    definition = admin._resource_definitions["orders"]
    assert resource_web_presentation(definition) is presentation
    assert definition.filters == _OrdersAdmin.filters


def test_public_admin_register_rejects_unknown_web_filter_presentation() -> None:
    admin = Admin(title="Presentation test", debug=True)
    presentation = ResourceWebPresentation(
        filters=FilterPanelPresentation(
            groups={"secret": FilterGroupPresentation(expanded_by_default=True)}
        )
    )

    with pytest.raises(RakitError) as exc_info:
        admin.register(_OrdersAdmin, web=presentation)

    error = exc_info.value
    assert error.code == ErrorCode.CONFIG_INVALID_RESOURCE_POLICY
    assert error.details["reason"] == "unknown_web_filter_presentation"
    assert error.details["filter_ids"] == ["secret"]


@pytest.mark.anyio
async def test_default_resource_filter_ui_renders_rail_mobile_fallback_and_shared_groups() -> None:
    admin = Admin(title="Presentation test", debug=True)
    admin.register(_OrdersAdmin)
    app = admin.asgi()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/orders", params={"filter": "status:eq:paid"})

    assert response.status_code == 200
    assert 'data-rakit-filter-ui="orders"' in response.text
    assert "data-rakit-filter-rail" in response.text
    assert "data-rakit-filter-mobile-fallback" in response.text
    assert "data-rakit-filter-drawer" in response.text
    assert 'data-rakit-filter-group="status"' in response.text
    assert "data-rakit-active-filters" in response.text
    assert "Status: Paid" in response.text
    assert "Clear all filters" in response.text
    assert "divide-y divide-rakit-border" in response.text
    assert "data-rakit-filter-panel" not in response.text
