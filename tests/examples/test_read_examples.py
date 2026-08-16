import html
import importlib
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import pytest
from rakit import Admin
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.relationship_mutations import DeleteRelated
from rakit_web.relationship_routes import relationship_prefix
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

repository = Path(__file__).resolve().parents[2]


def _venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _venv_site_packages(python: Path) -> Path:
    result = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


class _RenderedFormParser(HTMLParser):
    """Collect successful controls from the rendered parent form like a browser."""

    def __init__(self) -> None:
        super().__init__()
        self.controls: list[tuple[str, str]] = []
        self._form_depth = 0
        self._select: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._form_depth += 1
        if self._form_depth != 1:
            return
        if tag == "input":
            name = attributes.get("name")
            if not isinstance(name, str):
                return
            input_type = attributes.get("type", "text")
            if input_type in {"checkbox", "radio"} and "checked" not in attributes:
                return
            self.controls.append((name, attributes.get("value") or ""))
        elif tag == "select" and isinstance(attributes.get("name"), str):
            self._select = {
                "name": attributes["name"],
                "first": None,
                "selected": None,
            }
        elif tag == "option" and self._select is not None:
            value = attributes.get("value") or ""
            if self._select["first"] is None:
                self._select["first"] = value
            if "selected" in attributes:
                self._select["selected"] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self._select is not None:
            value = self._select["selected"] or self._select["first"] or ""
            self.controls.append((str(self._select["name"]), str(value)))
            self._select = None
        elif tag == "form":
            self._form_depth -= 1


def _replace_control(
    controls: list[tuple[str, str]], name: str, value: str
) -> list[tuple[str, str]]:
    return [
        (control_name, value if control_name == name else control_value)
        for control_name, control_value in controls
    ]


def _append_control(
    controls: list[tuple[str, str]], *additional: tuple[str, str]
) -> list[tuple[str, str]]:
    return [*controls, *additional]


def _example_environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    entries = [str(repository)]
    if existing:
        entries.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    return environment


@pytest.fixture(autouse=True)
def _private_example_import_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(repository))


def test_minimal_example_compiles_without_optional_integrations() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import examples.minimal.main as example; "
                "assert example.admin.compile().resources; "
                "assert 'fastapi' not in sys.modules; "
                "assert 'sqlalchemy' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_example_environment(),
    )

    assert result.returncode == 0, result.stderr


def test_readme_primary_example_executes_and_compiles_without_io() -> None:
    readme = (repository / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Example direction", 1)[1]
    match = re.search(r"```python\s+(.*?)```", section, flags=re.DOTALL)
    assert match is not None

    class DocumentationBase(DeclarativeBase):
        pass

    class DocumentationUser(DocumentationBase):
        __tablename__ = "documentation_users"

        id: Mapped[int] = mapped_column(primary_key=True)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    namespace: dict[str, Any] = {"engine": engine, "User": DocumentationUser}

    exec(compile(match.group(1), "README.md", "exec"), namespace)

    admin = cast(Admin, namespace["admin"])
    compiled = admin.compile()
    assert [resource.resource_id for resource in compiled.resources] == ["users"]
    assert namespace["app"] is not None


def test_fastapi_example_has_mounted_admin_and_compiles() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.main")

    assert module.app is not None
    assert module.admin.compile().resources
    assert any(getattr(route, "path", None) == "/admin" for route in module.app.routes)


@pytest.mark.anyio
async def test_relationship_review_create_renders_required_parent_scalar_and_submits() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        form = await client.get("/orders/new")
        created = await client.post(
            "/orders/new",
            data={
                "status": "ready",
                "csrf_token": "csrf",
                "submission_token": "demo-submission-token",
                f"{relationship_prefix('items')}create__new-line__sku": "SKU-001",
                f"{relationship_prefix('items')}create__new-line__quantity": "1",
            },
            follow_redirects=False,
        )
        invalid = await client.post(
            "/orders/new",
            data={
                "csrf_token": "csrf",
                "submission_token": "demo-submission-token",
            },
        )

    assert 'name="status"' in form.text
    assert created.status_code == 303
    assert invalid.status_code == 422
    assert 'for="rakit--orders-status"' in invalid.text
    assert 'aria-invalid="true"' in invalid.text


@pytest.mark.anyio
async def test_rendered_delete_preview_form_can_be_saved_without_invalid_form() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    child = "eyJpZCI6MjF9"
    prefix = relationship_prefix("items")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        preview_payload = [
            *parser.controls,
            (f"{prefix}delete_preview", child),
        ]
        preview = await client.post(
            f"/orders/{parent}/_relationships/items/preview",
            content=urlencode(preview_payload),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "HX-Request": "true",
            },
        )
        confirmation = re.search(r'data-rakit-confirmation="([^"]+)"', preview.text)
        impact = re.search(r'data-rakit-impact="([^"]*)"', preview.text)
        assert preview.status_code == 200
        assert confirmation is not None
        final_payload = [
            *parser.controls,
            (f"{prefix}delete_intent__{child}", "true"),
            (f"{prefix}delete__{child}", html.unescape(confirmation.group(1))),
            (f"{prefix}delete_impact__{child}", html.unescape(impact.group(1)) if impact else ""),
        ]
        saved = await client.post(
            f"/orders/{parent}/edit",
            content=urlencode(final_payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303
    assert "Invalid form" not in saved.text


@pytest.mark.anyio
async def test_each_rendered_relationship_operation_reaches_final_parent_save() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    codec = IdentityCodec()
    customer_prefix = relationship_prefix("customer")
    tags_prefix = relationship_prefix("tags")
    items_prefix = relationship_prefix("items")
    courses_prefix = relationship_prefix("courses")
    customer_two = codec.encode(RecordIdentity(values={"id": 2}))
    tag_one = codec.encode(RecordIdentity(values={"id": 1}))
    tag_eleven = codec.encode(RecordIdentity(values={"id": 11}))
    item_twenty_one = codec.encode(RecordIdentity(values={"id": 21}))
    item_twenty_two = codec.encode(RecordIdentity(values={"id": 22}))
    item_twenty_three = codec.encode(RecordIdentity(values={"id": 23}))
    course_fifty_one = codec.encode(RecordIdentity(values={"id": 51}))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        base = parser.controls

        async def save(payload: list[tuple[str, str]]) -> None:
            response = await client.post(
                f"/orders/{parent}/edit",
                content=urlencode(payload),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
            assert response.status_code == 303, response.text

        async def preview(
            payload: list[tuple[str, str]], relationship_id: str, name: str, value: str
        ) -> tuple[str, str, str]:
            response = await client.post(
                f"/orders/{parent}/_relationships/{relationship_id}/preview",
                content=urlencode(
                    payload
                    if any(control_name == name for control_name, _ in payload)
                    else [*payload, (name, value)]
                ),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "HX-Request": "true",
                },
            )
            assert response.status_code == 200
            confirmation = re.search(r'data-rakit-confirmation="([^"]+)"', response.text)
            intent = re.search(r'data-rakit-confirmation-intent="([^"]*)"', response.text)
            impact = re.search(r'data-rakit-impact="([^"]*)"', response.text)
            assert confirmation is not None
            return (
                html.unescape(confirmation.group(1)),
                html.unescape(intent.group(1)) if intent else "",
                html.unescape(impact.group(1)) if impact else "",
            )

        async def save_confirmed(
            payload: list[tuple[str, str]], prefix: str, confirmation: tuple[str, str, str]
        ) -> None:
            token, intent, impact = confirmation
            await save(
                _append_control(
                    payload,
                    (f"{prefix}destructive_confirmation", token),
                    (f"{prefix}confirmation_intent", intent),
                    (f"{prefix}confirmation_impact", impact),
                )
            )

        await save(base)  # scalar-only

        customer_set = _replace_control(base, f"{customer_prefix}set", customer_two)
        await save_confirmed(
            customer_set,
            customer_prefix,
            await preview(customer_set, "customer", f"{customer_prefix}set", customer_two),
        )

        customer_clear = _append_control(
            _replace_control(base, f"{customer_prefix}set", ""),
            (f"{customer_prefix}clear", "true"),
        )
        await save_confirmed(
            customer_clear,
            customer_prefix,
            await preview(customer_clear, "customer", f"{customer_prefix}clear", "true"),
        )

        await save(_append_control(base, (f"{tags_prefix}link__{tag_one}", tag_one)))

        tag_unlink = _append_control(base, (f"{tags_prefix}unlink__{tag_eleven}", tag_eleven))
        await save_confirmed(
            tag_unlink,
            tags_prefix,
            await preview(tag_unlink, "tags", f"{tags_prefix}unlink_preview", tag_eleven),
        )

        await save(
            _replace_control(
                base,
                f"{items_prefix}update__{item_twenty_one}__sku",
                "SKU-UPDATED",
            )
        )

        order_controls = [
            (name, value) for name, value in base if name.startswith(f"{items_prefix}order__")
        ]
        first_order = order_controls[0][1]
        second_order = order_controls[1][1]
        order_index = 0
        reorder = []
        for name, value in base:
            if name.startswith(f"{items_prefix}order__"):
                value = (
                    second_order if order_index == 0 else first_order if order_index == 1 else value
                )
                order_index += 1
            reorder.append((name, value))
        await save(reorder)

        item_unlink = _append_control(
            base, (f"{items_prefix}unlink__{item_twenty_two}", item_twenty_two)
        )
        await save_confirmed(
            item_unlink,
            items_prefix,
            await preview(item_unlink, "items", f"{items_prefix}unlink_preview", item_twenty_two),
        )

        item_delete = _append_control(
            base,
            (f"{items_prefix}delete_intent__{item_twenty_three}", "true"),
        )
        delete_confirmation = await preview(
            base, "items", f"{items_prefix}delete_preview", item_twenty_three
        )
        await save(
            _append_control(
                item_delete,
                (f"{items_prefix}delete__{item_twenty_three}", delete_confirmation[0]),
                (f"{items_prefix}delete_impact__{item_twenty_three}", delete_confirmation[2]),
            )
        )

        await save(
            _append_control(
                base,
                (f"{items_prefix}create__new-browser__sku", "SKU-CREATED"),
                (f"{items_prefix}create__new-browser__quantity", "2"),
            )
        )
        await save(
            _replace_control(
                base,
                f"{courses_prefix}association__{course_fifty_one}__grade",
                "A",
            )
        )


@pytest.mark.anyio
async def test_rendered_mixed_relationship_state_uses_one_graph_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    codec = IdentityCodec()
    customer_prefix = relationship_prefix("customer")
    tags_prefix = relationship_prefix("tags")
    items_prefix = relationship_prefix("items")
    courses_prefix = relationship_prefix("courses")
    tag_one = codec.encode(RecordIdentity(values={"id": 1}))
    tag_eleven = codec.encode(RecordIdentity(values={"id": 11}))
    item_twenty_one = codec.encode(RecordIdentity(values={"id": 21}))
    item_twenty_two = codec.encode(RecordIdentity(values={"id": 22}))
    item_twenty_three = codec.encode(RecordIdentity(values={"id": 23}))
    course_fifty_one = codec.encode(RecordIdentity(values={"id": 51}))
    service = cast(Any, module.binding.mutation_service)
    calls: list[dict[str, object]] = []
    original_update_graph = service.update_graph

    async def tracked_update_graph(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return await original_update_graph(*args, **kwargs)

    monkeypatch.setattr(service, "update_graph", tracked_update_graph)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        base = parser.controls
        order_controls = [
            (name, value) for name, value in base if name.startswith(f"{items_prefix}order__")
        ]
        order_index = 0
        mixed: list[tuple[str, str]] = []
        for name, value in base:
            if name.startswith(f"{items_prefix}order__"):
                value = (
                    order_controls[1][1]
                    if order_index == 0
                    else order_controls[0][1]
                    if order_index == 1
                    else value
                )
                order_index += 1
            mixed.append((name, value))
        mixed = _replace_control(mixed, f"{customer_prefix}set", "")
        mixed = _replace_control(
            mixed,
            f"{items_prefix}update__{item_twenty_one}__sku",
            "SKU-MIXED",
        )
        mixed = _replace_control(
            mixed,
            f"{courses_prefix}association__{course_fifty_one}__grade",
            "A",
        )
        mixed = _append_control(
            mixed,
            (f"{customer_prefix}clear", "true"),
            (f"{customer_prefix}destructive_confirmation", "clear-confirm"),
            (f"{tags_prefix}link__{tag_one}", tag_one),
            (f"{tags_prefix}unlink__{tag_eleven}", tag_eleven),
            (f"{tags_prefix}destructive_confirmation", "tags-confirm"),
            (f"{items_prefix}create__new-mixed__sku", "SKU-CREATED"),
            (f"{items_prefix}create__new-mixed__quantity", "2"),
            (f"{items_prefix}unlink__{item_twenty_two}", item_twenty_two),
            (f"{items_prefix}delete_intent__{item_twenty_three}", "true"),
            (f"{items_prefix}delete__{item_twenty_three}", "delete-confirm"),
            (f"{items_prefix}delete_impact__{item_twenty_three}", "1"),
            (f"{items_prefix}destructive_confirmation", "items-confirm"),
        )
        saved = await client.post(
            f"/orders/{parent}/edit",
            content=urlencode(mixed),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303
    assert len(calls) == 1
    assert len(cast(Any, calls[0]["relationship_changes"])) == 4


@pytest.mark.anyio
async def test_delete_undo_delete_repeat_keeps_valid_intent() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    codec = IdentityCodec()
    child = codec.encode(RecordIdentity(values={"id": 21}))
    prefix = relationship_prefix("items")

    def parsed_form(text: str) -> list[tuple[str, str]]:
        form_parser = _RenderedFormParser()
        form_parser.feed(text)
        return form_parser.controls

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        base = parser.controls

        async def preview(payload: list[tuple[str, str]]):
            return await client.post(
                f"/orders/{parent}/_relationships/items/preview",
                content=urlencode(payload),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        async def confirm(payload: list[tuple[str, str]]):
            return await client.post(
                f"/orders/{parent}/_relationships/items/preview/confirm",
                content=urlencode(payload),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        first_preview = await preview([*base, (f"{prefix}delete_preview", child)])
        assert first_preview.status_code == 200
        assert "<!doctype html>" in first_preview.text
        assert "data-rakit-preview-dialog" not in first_preview.text

        first_confirm = await confirm(parsed_form(first_preview.text))
        assert first_confirm.status_code == 200
        pending = dict(parsed_form(first_confirm.text))
        assert f"{prefix}delete_intent__{child}" in pending
        assert f"{prefix}delete__{child}" in pending

        # Undo: the stable intent control is unchecked and its confirmation dropped.
        undo_names = {
            f"{prefix}delete_intent__{child}",
            f"{prefix}delete__{child}",
            f"{prefix}delete_impact__{child}",
        }
        undone = [
            (name, value)
            for name, value in parsed_form(first_confirm.text)
            if name not in undo_names
        ]

        # Delete the same row again: a fresh preview is required again.
        second_preview = await preview([*undone, (f"{prefix}delete_preview", child)])
        assert second_preview.status_code == 200
        second_confirm = await confirm(parsed_form(second_preview.text))
        final = dict(parsed_form(second_confirm.text))
        assert f"{prefix}delete_intent__{child}" in final
        assert f"{prefix}delete__{child}" in final

        saved = await client.post(
            f"/orders/{parent}/edit",
            content=urlencode(parsed_form(second_confirm.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303
    assert "Invalid form" not in saved.text


@pytest.mark.anyio
async def test_destructive_unlink_preview_survives_undo() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    codec = IdentityCodec()
    tag = codec.encode(RecordIdentity(values={"id": 11}))
    prefix = relationship_prefix("tags")

    def parsed_form(text: str) -> list[tuple[str, str]]:
        form_parser = _RenderedFormParser()
        form_parser.feed(text)
        return form_parser.controls

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        base = parser.controls

        first_preview = await client.post(
            f"/orders/{parent}/_relationships/tags/preview",
            content=urlencode([*base, (f"{prefix}unlink_preview", tag)]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert first_preview.status_code == 200
        assert "<!doctype html>" in first_preview.text
        assert "Confirm removal" in first_preview.text

        first_confirm = await client.post(
            f"/orders/{parent}/_relationships/tags/preview/confirm",
            content=urlencode(parsed_form(first_preview.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert first_confirm.status_code == 200
        pending = dict(parsed_form(first_confirm.text))
        assert f"{prefix}unlink__{tag}" in pending
        assert f"{prefix}destructive_confirmation" in pending

        undo_names = {
            f"{prefix}unlink__{tag}",
            f"{prefix}destructive_confirmation",
            f"{prefix}confirmation_intent",
            f"{prefix}confirmation_impact",
        }
        undone = [
            (name, value)
            for name, value in parsed_form(first_confirm.text)
            if name not in undo_names
        ]

        # Removing again requires a fresh preview; no pending unlink can appear
        # without going through the confirmation page.
        second_preview = await client.post(
            f"/orders/{parent}/_relationships/tags/preview",
            content=urlencode([*undone, (f"{prefix}unlink_preview", tag)]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert second_preview.status_code == 200
        assert "Confirm removal" in second_preview.text
        second_confirm = await client.post(
            f"/orders/{parent}/_relationships/tags/preview/confirm",
            content=urlencode(parsed_form(second_preview.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        final = dict(parsed_form(second_confirm.text))
        assert f"{prefix}unlink__{tag}" in final
        assert f"{prefix}destructive_confirmation" in final

        saved = await client.post(
            f"/orders/{parent}/edit",
            content=urlencode(parsed_form(second_confirm.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303


@pytest.mark.anyio
async def test_non_htmx_destructive_clear_confirm_creates_pending_clear() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    prefix = relationship_prefix("customer")

    def parsed_form(text: str) -> list[tuple[str, str]]:
        form_parser = _RenderedFormParser()
        form_parser.feed(text)
        return form_parser.controls

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        base = parser.controls
        assert any(name == f"{prefix}set" for name, _ in base)

        preview = await client.post(
            f"/orders/{parent}/_relationships/customer/preview",
            content=urlencode([*base, (f"{prefix}clear", "true")]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert preview.status_code == 200
        assert "<!doctype html>" in preview.text
        assert "Clear Customer?" in preview.text

        confirmed = await client.post(
            f"/orders/{parent}/_relationships/customer/preview/confirm",
            content=urlencode(parsed_form(preview.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert confirmed.status_code == 200
        final = dict(parsed_form(confirmed.text))
        assert f"{prefix}clear" in final
        assert final.get(f"{prefix}set") == ""
        assert f"{prefix}destructive_confirmation" in final

        saved = await client.post(
            f"/orders/{parent}/edit",
            content=urlencode(parsed_form(confirmed.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303


@pytest.mark.anyio
async def test_delete_cancel_restores_state_and_preserves_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    codec = IdentityCodec()
    child_a = codec.encode(RecordIdentity(values={"id": 21}))
    child_b = codec.encode(RecordIdentity(values={"id": 22}))
    prefix = relationship_prefix("items")
    service = cast(Any, module.binding.mutation_service)
    calls: list[dict[str, object]] = []
    original_update_graph = service.update_graph

    async def tracked_update_graph(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return await original_update_graph(*args, **kwargs)

    monkeypatch.setattr(service, "update_graph", tracked_update_graph)

    def parsed_form(text: str) -> list[tuple[str, str]]:
        form_parser = _RenderedFormParser()
        form_parser.feed(text)
        return form_parser.controls

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        # Unrelated pre-preview FormState: delete B is already pending.
        state = [
            *parser.controls,
            (f"{prefix}delete_intent__{child_b}", "true"),
            (f"{prefix}delete__{child_b}", "signed-b"),
        ]
        preview = await client.post(
            f"/orders/{parent}/_relationships/items/preview",
            content=urlencode([*state, (f"{prefix}delete_preview", child_a)]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert preview.status_code == 200
        cancel_payload = [*parsed_form(preview.text), ("cancel", "cancel")]
        cancelled = await client.post(
            f"/orders/{parent}/_relationships/items/preview/confirm",
            content=urlencode(cancel_payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert cancelled.status_code == 200
        after = dict(parsed_form(cancelled.text))
        assert f"{prefix}delete_intent__{child_a}" not in after
        assert f"{prefix}delete__{child_a}" not in after
        assert f"{prefix}delete_intent__{child_b}" in after
        assert f"{prefix}delete__{child_b}" in after

        saved = await client.post(
            f"/orders/{parent}/edit",
            content=urlencode(parsed_form(cancelled.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303
    assert calls
    assert not any(
        isinstance(step, DeleteRelated) and step.identity.values == {"id": 21}
        for change in cast(Any, calls[0]["relationship_changes"])
        for step in change.steps
    )


@pytest.mark.anyio
async def test_unlink_cancel_restores_state_and_preserves_unrelated() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    codec = IdentityCodec()
    tag = codec.encode(RecordIdentity(values={"id": 11}))
    child_b = codec.encode(RecordIdentity(values={"id": 22}))
    tags_prefix = relationship_prefix("tags")
    items_prefix = relationship_prefix("items")

    def parsed_form(text: str) -> list[tuple[str, str]]:
        form_parser = _RenderedFormParser()
        form_parser.feed(text)
        return form_parser.controls

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        # Unrelated pre-preview FormState: delete B is already pending.
        state = [
            *parser.controls,
            (f"{items_prefix}delete_intent__{child_b}", "true"),
            (f"{items_prefix}delete__{child_b}", "signed-b"),
        ]
        preview = await client.post(
            f"/orders/{parent}/_relationships/tags/preview",
            content=urlencode([*state, (f"{tags_prefix}unlink_preview", tag)]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert preview.status_code == 200
        cancel_payload = [*parsed_form(preview.text), ("cancel", "cancel")]
        cancelled = await client.post(
            f"/orders/{parent}/_relationships/tags/preview/confirm",
            content=urlencode(cancel_payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert cancelled.status_code == 200
        after = dict(parsed_form(cancelled.text))
        assert f"{tags_prefix}unlink__{tag}" not in after
        assert f"{tags_prefix}destructive_confirmation" not in after
        assert f"{items_prefix}delete_intent__{child_b}" in after
        assert f"{items_prefix}delete__{child_b}" in after

        saved = await client.post(
            f"/orders/{parent}/edit",
            content=urlencode(parsed_form(cancelled.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303


@pytest.mark.anyio
async def test_clear_cancel_keeps_customer_selected() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.relationship_review")
    parent = "eyJpZCI6MTB9"
    prefix = relationship_prefix("customer")

    def parsed_form(text: str) -> list[tuple[str, str]]:
        form_parser = _RenderedFormParser()
        form_parser.feed(text)
        return form_parser.controls

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=module.app), base_url="http://test"
    ) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        parser = _RenderedFormParser()
        parser.feed(edit.text)
        base = parser.controls
        assert any(name == f"{prefix}set" and value for name, value in base)

        preview = await client.post(
            f"/orders/{parent}/_relationships/customer/preview",
            content=urlencode([*base, (f"{prefix}clear", "true")]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert preview.status_code == 200
        cancel_payload = [*parsed_form(preview.text), ("cancel", "cancel")]
        cancelled = await client.post(
            f"/orders/{parent}/_relationships/customer/preview/confirm",
            content=urlencode(cancel_payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert cancelled.status_code == 200
        after = dict(parsed_form(cancelled.text))
        assert after.get(f"{prefix}set") != ""
        assert f"{prefix}clear" not in after
        assert f"{prefix}destructive_confirmation" not in after

        saved = await client.post(
            f"/orders/{parent}/edit",
            content=urlencode(parsed_form(cancelled.text)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert saved.status_code == 303


def test_example_dependencies_are_declared_as_optional() -> None:
    repository = Path(__file__).resolve().parents[2]
    configuration = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = configuration["project"]["optional-dependencies"]["examples"]

    assert any(dependency.startswith("fastapi") for dependency in dependencies)
    assert any(dependency.startswith("aiosqlite") for dependency in dependencies)
    assert any(dependency.startswith("uvicorn") for dependency in dependencies)


def test_fastapi_example_is_type_checkable_in_the_locked_development_environment() -> None:
    configuration = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))
    development_dependencies = configuration["dependency-groups"]["dev"]

    assert any(dependency.startswith("fastapi") for dependency in development_dependencies)


def test_fastapi_is_not_an_official_package_runtime_dependency() -> None:
    for package_configuration in (repository / "packages").glob("*/pyproject.toml"):
        configuration = tomllib.loads(package_configuration.read_text(encoding="utf-8"))
        runtime_dependencies = configuration["project"].get("dependencies", [])

        assert not any(dependency.startswith("fastapi") for dependency in runtime_dependencies)


@asynccontextmanager
async def _started_client(app, *, base_url: str = "http://localhost"):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            yield client


async def test_minimal_example_serves_read_routes_and_actual_query_contract() -> None:
    module = importlib.import_module("examples.minimal.main")
    transport = httpx.ASGITransport(app=module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        full = await client.get(
            "/products",
            params={
                "filter": "name:contains:Clamp",
                "sort": "-name",
                "page": "1",
                "per_page": "1",
                "count_policy": "exact",
            },
        )
        fragment = await client.get(
            "/products",
            params={"sort": "name", "count_policy": "disabled"},
            headers={"HX-Request": "true"},
        )
        deferred = await client.get(
            "/products",
            params={"filter": "name:contains:Clamp", "count_policy": "deferred"},
        )
        count = await client.get(
            "/products/_count",
            params={"filter": "name:contains:Clamp"},
            headers={"HX-Request": "true"},
        )

        detail_path = re.search(r'href="(/products/[^"]+)"', full.text)
        assert detail_path is not None
        detail = await client.get(detail_path.group(1))

    assert full.status_code == 200
    assert "Bench Clamp" in full.text
    assert "Soldering Iron" not in full.text
    assert "<html" in full.text
    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert "Total unknown" in fragment.text
    assert "Calculating total" in deferred.text
    assert count.text.strip() == "1"
    assert detail.status_code == 200
    assert "Bench Clamp" in detail.text


async def test_fastapi_sqlalchemy_example_mount_serves_full_and_htmx_reads() -> None:
    module = importlib.import_module("examples.fastapi_sqlalchemy.main")

    async with _started_client(module.app) as client:
        full = await client.get(
            "/admin/users",
            params={
                "filter": "name:contains:a",
                "sort": "-name",
                "page": "1",
                "per_page": "1",
                "count_policy": "exact",
            },
        )
        fragment = await client.get(
            "/admin/users",
            params={"search": "example.com", "count_policy": "disabled"},
            headers={"HX-Request": "true"},
        )
        deferred = await client.get(
            "/admin/users",
            params={"search": "work.test", "count_policy": "deferred"},
        )
        count = await client.get(
            "/admin/users/_count",
            params={"search": "work.test"},
            headers={"HX-Request": "true"},
        )

        asset_paths = re.findall(r'(?:href|src)="(/admin/_system/static/[^"]+)"', full.text)
        asset_responses = [await client.get(path) for path in asset_paths]

        search_action_match = re.search(
            r'<form[^>]+data-rakit-search[^>]+action="([^"]+)"', full.text
        )
        assert search_action_match is not None
        search_action = html.unescape(search_action_match.group(1))
        search_response = await client.get(search_action, params={"search": "Ada"})

        sort_href_match = re.search(r'<th[^>]*>\s*<a href="([^"]+)"', full.text)
        assert sort_href_match is not None
        sort_href = html.unescape(sort_href_match.group(1))
        sort_response = await client.get(sort_href)

        detail_path = re.search(r'href="(/admin/users/[^"]+)"', full.text)
        assert detail_path is not None
        detail = await client.get(detail_path.group(1))

    assert full.status_code == 200
    assert "<html" in full.text
    assert "Grace" in full.text
    asset_names = {path.rsplit("/", 1)[-1] for path in asset_paths}

    assert len(asset_paths) == len(set(asset_paths))
    assert any(name.startswith("rakit.") and name.endswith(".css") for name in asset_names)
    assert any(name.startswith("htmx.min.") and name.endswith(".js") for name in asset_names)
    assert any(name.startswith("rakit-ui.") and name.endswith(".js") for name in asset_names)
    assert all(response.status_code == 200 for response in asset_responses)
    assert search_action == "/admin/users"
    assert search_response.status_code == 200
    assert sort_href.startswith("/admin/users?")
    assert sort_response.status_code == 200
    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert "Total unknown" in fragment.text
    assert "Calculating total" in deferred.text
    assert count.text.strip() == "1"
    assert detail.status_code == 200
    assert "Grace" in detail.text


def test_cli_check_and_routes_accept_both_examples() -> None:
    for target in (
        "examples.minimal.main:admin",
        "examples.fastapi_sqlalchemy.main:admin",
    ):
        checked = subprocess.run(
            ["rakit", "check", target],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
            env=_example_environment(),
        )
        routes = subprocess.run(
            ["rakit", "routes", target],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
            env=_example_environment(),
        )

        assert checked.returncode == 0, checked.stderr
        assert "Rakit configuration is valid." in checked.stdout
        assert routes.returncode == 0, routes.stderr
        assert ":list" in routes.stdout
        assert ":detail" in routes.stdout


def test_all_packages_builds_exactly_the_nine_official_distributions(
    tmp_path: Path,
) -> None:
    output = tmp_path / "all-distributions"
    subprocess.run(
        ["uv", "build", "--all-packages", "--out-dir", str(output)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )

    expected = {
        "rakit",
        "rakit_auth_sqlalchemy",
        "rakit_core",
        "rakit_server",
        "rakit_server_uvicorn",
        "rakit_sqlalchemy",
        "rakit_storage",
        "rakit_storage_local",
        "rakit_web",
    }
    wheels = {path.name.split("-", 1)[0] for path in output.glob("*.whl")}
    sdists = {path.name.split("-", 1)[0] for path in output.glob("*.tar.gz")}

    assert wheels == expected
    assert sdists == expected
    assert not any(path.name.startswith("rakit_workspace-") for path in output.iterdir())

    rakit_wheel = next(output.glob("rakit-*.whl"))
    with zipfile.ZipFile(rakit_wheel) as archive:
        assert "rakit/py.typed" in archive.namelist()

    auth_sqlalchemy_wheel = next(output.glob("rakit_auth_sqlalchemy-*.whl"))
    with zipfile.ZipFile(auth_sqlalchemy_wheel) as archive:
        names = archive.namelist()
        # The Alembic migration files must ship inside the installed wheel,
        # not only the sdist -- a `pip install rakit-auth-sqlalchemy` from a
        # wheel (the common case) must be able to run its own migrations.
        assert "rakit_auth_sqlalchemy/alembic.ini" in names
        assert "rakit_auth_sqlalchemy/alembic/env.py" in names
        assert "rakit_auth_sqlalchemy/alembic/versions/0001_initial_auth.py" in names

    installed = tmp_path / "installed-rakit"
    subprocess.run(
        ["uv", "venv", str(installed), "--python", sys.executable],
        check=True,
        capture_output=True,
        text=True,
    )
    installed_python = _venv_python(installed)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(installed_python),
            "--find-links",
            str(output),
            str(rakit_wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    isolated_environment = os.environ.copy()
    isolated_environment.pop("PYTHONPATH", None)
    imported = subprocess.run(
        [
            str(installed_python),
            "-c",
            (
                "import sys; "
                "from rakit.core import (CountPolicy, DataSource, DataSourceCapabilities, Filter, "
                "FilterOperator, IdentityCodec, NullPlacement, OffsetPagination, PageResult, "
                "RecordIdentity, ResourceQuery, ResourceService, Sort, SortDirection); "
                "assert 'rakit_sqlalchemy' not in sys.modules"
            ),
        ],
        cwd=installed,
        env=isolated_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr


def test_auth_migration_history_coexists_with_a_host_alembic_version_table(
    tmp_path: Path,
) -> None:
    """Rakit's own Alembic revision history must never share a version
    table with a host application's own Alembic history -- sharing
    "alembic_version" would make an upgrade for either history fail
    trying to locate a revision ID that belongs to the other's history
    entirely. Runs the migration from a real installed wheel, not the
    source tree, since that's what a deployment actually does."""
    import sqlite3

    output = tmp_path / "auth-migration-distributions"
    subprocess.run(
        ["uv", "build", "--all-packages", "--out-dir", str(output)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )

    installed = tmp_path / "installed-auth-sqlalchemy"
    subprocess.run(
        ["uv", "venv", str(installed), "--python", sys.executable],
        check=True,
        capture_output=True,
        text=True,
    )
    installed_python = _venv_python(installed)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(installed_python),
            "--find-links",
            str(output),
            "rakit-auth-sqlalchemy",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    ini_path = _venv_site_packages(installed_python) / "rakit_auth_sqlalchemy" / "alembic.ini"
    assert ini_path.exists()

    # 1. Seed a host alembic_version table with an unrelated revision --
    # simulating a host application that already runs its own Alembic
    # migrations against this same database.
    db_path = tmp_path / "host-coexist.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version (version_num) VALUES ('host_0001')")
    conn.commit()
    conn.close()

    isolated_environment = os.environ.copy()
    isolated_environment.pop("PYTHONPATH", None)
    isolated_environment["RAKIT_AUTH_SQLALCHEMY_URL"] = f"sqlite:///{db_path.as_posix()}"

    # 2. Run the Rakit auth upgrade from the installed wheel.
    upgrade = subprocess.run(
        [
            str(installed_python),
            "-m",
            "alembic",
            "-c",
            str(ini_path),
            "upgrade",
            "head",
        ],
        env=isolated_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert upgrade.returncode == 0, upgrade.stderr

    conn = sqlite3.connect(db_path)
    table_names = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    # 3. rakit_auth_alembic_version reaches the current Rakit auth head.
    assert "rakit_auth_alembic_version" in table_names
    assert conn.execute("SELECT version_num FROM rakit_auth_alembic_version").fetchall() == [
        ("0003",)
    ]
    assert "rakit_auth_idempotency" in table_names

    # 4. The host's own version table is unchanged.
    assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("host_0001",)]
    conn.execute(
        "INSERT INTO rakit_auth_users "
        "(id, email, password_hash, is_active, is_superuser, created_at, updated_at) "
        "VALUES (1, 'ada@example.com', 'hash', 1, 0, '2026-01-01', '2026-01-01')"
    )
    conn.execute("INSERT INTO rakit_auth_roles (id, name) VALUES (1, 'admin')")
    conn.execute(
        'INSERT INTO rakit_auth_permissions (id, key, label, "group", orphaned) '
        "VALUES (1, 'users.read', 'Read users', 'users', 0)"
    )
    conn.execute("INSERT INTO rakit_auth_user_roles (user_id, role_id) VALUES (1, 1)")
    conn.execute("INSERT INTO rakit_auth_role_permissions (role_id, permission_id) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO rakit_auth_sessions "
        "(id, token_hash, user_id, created_at, last_seen_at, idle_expires_at, "
        "absolute_expires_at) VALUES "
        "(1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 1, "
        "'2026-01-01', '2026-01-01', '2026-01-02', '2026-01-08')"
    )
    conn.commit()
    conn.close()

    # 5. Rerunning the upgrade succeeds (idempotent no-op at head).
    rerun = subprocess.run(
        [
            str(installed_python),
            "-m",
            "alembic",
            "-c",
            str(ini_path),
            "upgrade",
            "head",
        ],
        env=isolated_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert rerun.returncode == 0, rerun.stderr

    # 6. Downgrade is explicitly refused by the migration shipped in the
    # wheel, and Alembic leaves the revision, tables, and seeded data intact.
    downgrade = subprocess.run(
        [
            str(installed_python),
            "-m",
            "alembic",
            "-c",
            str(ini_path),
            "downgrade",
            "base",
        ],
        env=isolated_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert downgrade.returncode != 0
    assert "forward-only" in (downgrade.stdout + downgrade.stderr)

    # 7. Only Rakit-owned tables were affected: every expected auth table
    # exists, and the host's alembic_version table/row are byte-identical
    # to what was seeded.
    conn = sqlite3.connect(db_path)
    final_tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected_rakit_tables = {
        "rakit_auth_alembic_version",
        "rakit_auth_users",
        "rakit_auth_roles",
        "rakit_auth_permissions",
        "rakit_auth_user_roles",
        "rakit_auth_role_permissions",
        "rakit_auth_sessions",
        "rakit_auth_idempotency",
    }
    assert expected_rakit_tables <= final_tables
    assert conn.execute("SELECT version_num FROM rakit_auth_alembic_version").fetchall() == [
        ("0003",)
    ]
    assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("host_0001",)]
    for table_name in expected_rakit_tables - {
        "rakit_auth_alembic_version",
        "rakit_auth_idempotency",
    }:
        assert conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone() == (1,)
    assert conn.execute("SELECT COUNT(*) FROM rakit_auth_idempotency").fetchone() == (0,)
    conn.close()
