import pytest
from pydantic import ValidationError

from rakit_core.dashboard import (
    DashboardDefinition,
    ListWidgetItem,
    ListWidgetResult,
    StatWidgetResult,
    TableWidgetResult,
    WidgetLayout,
    WidgetLoadingMode,
)


def test_dashboard_and_widget_ids_are_stable() -> None:
    dashboard = DashboardDefinition(
        dashboard_id="main", title="Operations", widgets=("pending_orders",)
    )
    result = StatWidgetResult(
        value=128,
        label="Pending orders",
        layout=WidgetLayout(size="small"),
        loading=WidgetLoadingMode.LAZY,
    )

    assert dashboard.dashboard_id == "main"
    assert dashboard.widgets == ("pending_orders",)
    assert result.value == 128
    assert result.layout.size == "small"


def test_dashboard_contracts_are_immutable_and_semantic() -> None:
    result = ListWidgetResult(
        label="Queues",
        items=(ListWidgetItem(label="Exports", value="3", href="/exports"),),
        layout=WidgetLayout(size="large", priority=10, min_height=160),
    )

    assert result.layout.size == "large"
    assert "tailwind" not in result.model_dump_json().lower()
    with pytest.raises(ValidationError):
        result.layout.priority = 20


def test_table_rows_match_declared_columns() -> None:
    with pytest.raises(ValidationError):
        TableWidgetResult(
            label="Recent orders",
            columns=("Order", "Status"),
            rows=(("#1001",),),
        )


def test_dashboard_rejects_duplicate_widget_ids() -> None:
    with pytest.raises(ValidationError):
        DashboardDefinition(
            dashboard_id="main",
            title="Operations",
            widgets=("pending_orders", "pending_orders"),
        )
