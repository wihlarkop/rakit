from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from importlib.resources import files

import httpx
import pytest
from rakit_core.fields import FieldDefinition, FileField
from rakit_core.forms import FormSchema
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_web.field_presentation import (
    Checkbox,
    Choice,
    Currency,
    DatePicker,
    DateRangePicker,
    DateTimePicker,
    FileUpload,
    ImageUpload,
    NumberInput,
    Percentage,
    SearchableSelect,
    SegmentedControl,
    Switch,
    TimePicker,
)
from rakit_web.form_routes import WriteResourceBinding, build_write_routes
from rakit_web.resource_routes import build_templates
from starlette.applications import Starlette


class _CaptureCreateService:
    def __init__(self) -> None:
        self.submitted: Mapping[str, object] | None = None

    async def create(
        self,
        submitted: Mapping[str, object],
        *,
        authorization: MutationAuthorization | None = None,
    ) -> object:
        del authorization
        self.submitted = submitted
        return submitted


async def _allow(_request: object) -> bool:
    return True


async def _authorize(
    _request: object,
    operation: MutationOperation,
    _identity: object | None,
) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="admin",
        resource_id="widgets",
        operation=operation,
        principal_id="tester",
        permissions=(f"admin.resources.widgets.{operation}",),
    )


def _binding(fields: tuple[FieldDefinition, ...], service: _CaptureCreateService) -> WriteResourceBinding:
    return WriteResourceBinding(
        path="/widgets",
        label="Widget",
        form_schema=FormSchema(fields=fields),
        mutation_service=service,
        templates=build_templates(()),
        authorize=_allow,
        verify_csrf=_allow,
        verify_submission_token=_allow,
        issue_submission_token=lambda _request: "submission-token",
        mutation_authorizer=_authorize,
    )


@pytest.mark.anyio
async def test_scalar_presentations_keep_native_semantic_fallbacks_and_form_names() -> None:
    service = _CaptureCreateService()
    fields = (
        FieldDefinition(
            field_id="status",
            python_type=str,
            label="Status",
            presentation=SearchableSelect(
                choices=(Choice("draft", "Draft"), Choice("live", "Live"))
            ),
        ),
        FieldDefinition(
            field_id="on_date",
            python_type=date,
            presentation=DatePicker(),
        ),
        FieldDefinition(
            field_id="at_time",
            python_type=time,
            presentation=TimePicker(step_seconds=60),
        ),
        FieldDefinition(
            field_id="scheduled_at",
            python_type=datetime,
            presentation=DateTimePicker(timezone="Asia/Jakarta"),
        ),
        FieldDefinition(
            field_id="range_value",
            python_type=str,
            presentation=DateRangePicker(),
        ),
        FieldDefinition(
            field_id="quantity",
            python_type=int,
            presentation=NumberInput(min_value=0, step=1),
        ),
        FieldDefinition(
            field_id="budget",
            python_type=Decimal,
            presentation=Currency(currency="IDR", locale="id-ID", step=1000),
        ),
        FieldDefinition(
            field_id="progress",
            python_type=Decimal,
            presentation=Percentage(scale="whole", min_value=0, max_value=100),
        ),
        FieldDefinition(
            field_id="enabled",
            python_type=bool,
            presentation=Switch(on_label="Enabled", off_label="Disabled"),
        ),
        FieldDefinition(
            field_id="confirmed",
            python_type=bool,
            presentation=Checkbox(),
        ),
        FieldDefinition(
            field_id="priority",
            python_type=str,
            presentation=SegmentedControl(
                choices=(Choice("normal", "Normal"), Choice("urgent", "Urgent"))
            ),
        ),
        FileField(
            field_id="attachment",
            presentation=FileUpload(drag_drop=True, preview=True),
        ),
        FileField(
            field_id="image",
            allowed_mime_types=("image/png",),
            presentation=ImageUpload(),
        ),
    )
    app = Starlette(routes=build_write_routes(_binding(fields, service)))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/widgets/new")

    assert response.status_code == 200
    html = response.text
    assert 'data-rakit-widget="searchable_select"' in html
    assert '<select class="rakit-select"' in html
    assert 'name="status"' in html
    assert 'type="date"' in html and 'name="on_date"' in html
    assert 'type="time"' in html and 'name="at_time"' in html
    assert 'type="datetime-local"' in html and 'name="scheduled_at"' in html
    assert 'data-rakit-widget="date_range"' in html and 'name="range_value"' in html
    assert 'data-rakit-widget="currency"' in html and 'data-rakit-currency="IDR"' in html
    assert 'data-rakit-widget="percentage"' in html
    assert 'data-rakit-widget="switch"' in html
    assert 'name="enabled" value="false"' in html
    assert 'name="enabled" type="checkbox" value="true"' in html
    assert 'data-rakit-widget="segmented"' in html
    assert 'data-rakit-widget="file_upload"' in html
    assert 'data-rakit-widget="image_upload"' in html
    assert 'name="csrf_token"' in html
    assert 'name="submission_token" value="submission-token"' in html


@pytest.mark.anyio
async def test_boolean_hidden_fallback_accepts_exact_false_true_pair_without_relaxing_transport() -> None:
    service = _CaptureCreateService()
    binding = _binding(
        (
            FieldDefinition(
                field_id="enabled",
                python_type=bool,
                required=True,
                presentation=Switch(on_label="Enabled", off_label="Disabled"),
            ),
        ),
        service,
    )
    app = Starlette(routes=build_write_routes(binding))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/widgets/new",
            content="csrf_token=x&submission_token=y&enabled=false&enabled=true",
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert service.submitted is not None
    assert service.submitted["enabled"] is True


@pytest.mark.anyio
async def test_boolean_duplicate_guard_still_rejects_unexpected_duplicate_values() -> None:
    service = _CaptureCreateService()
    binding = _binding(
        (FieldDefinition(field_id="enabled", python_type=bool, presentation=Checkbox()),),
        service,
    )
    app = Starlette(routes=build_write_routes(binding))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/widgets/new",
            content="csrf_token=x&submission_token=y&enabled=true&enabled=true",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 400
    assert service.submitted is None


def test_shared_widget_runtime_locks_keyboard_aria_and_race_safety_contracts() -> None:
    script = files("rakit_web").joinpath("static", "rakit-widgets.js").read_text(encoding="utf-8")

    for marker in (
        "AbortController",
        "requestSequence",
        'event.key === "ArrowDown"',
        'event.key === "ArrowUp"',
        'event.key === "Enter"',
        'event.key === "Escape"',
        'event.key === "Backspace"',
        'input.setAttribute("aria-expanded", "true")',
        'input.setAttribute("aria-activedescendant"',
        'option.setAttribute("role", "option")',
        "data-rakit-option",
        "Remove ${label}",
        "Could not load candidates. Try again.",
    ):
        assert marker in script


def test_advanced_widget_styles_use_shared_semantic_components() -> None:
    css = files("rakit_web").joinpath("static", "rakit.css").read_text(encoding="utf-8")
    for marker in (
        ".rakit-switch-track",
        ".rakit-segmented",
        ".rakit-upload-control",
        ".rakit-choice-chip",
        ".rakit-autocomplete-listbox",
        ".rakit-autocomplete-option",
    ):
        assert marker in css
