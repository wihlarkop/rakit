import html
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, ModelAdmin, PageSizePolicy, ResourcePaginationPolicy, SecretValue
from rakit_core.filters import FilterSelection, LegacyFieldFilter
from rakit_core.query import FilterOperator
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_web.resource_query_ui import serialize_selection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.applications import Starlette
from starlette.routing import Mount


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str]


class UserAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/users"
    label = "Users"
    singular_label = "User"
    list_fields = ("id", "name", "email")
    detail_fields = ("id", "name", "email")
    filter_fields = ("id", "name", "email")
    search_fields = ("name", "email")
    sort_fields = ("id", "name", "email")
    pagination = ResourcePaginationPolicy(size=PageSizePolicy(default=2, allowed=(1, 2, 3)))
    pagination = ResourcePaginationPolicy(size=PageSizePolicy(default=1, allowed=(1, 2, 3)))


async def _seeded_factory(
    *, include_third: bool = False
) -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        users = [
            User(id=1, name="Ada", email="ada@example.com"),
            User(id=2, name="Grace", email="grace@work.test"),
        ]
        if include_third:
            users.append(User(id=3, name="Linus", email="linus@kernel.test"))
        session.add_all(users)
        await session.commit()
    return factory, engine


@asynccontextmanager
async def _client_for(admin: Admin) -> AsyncIterator[httpx.AsyncClient]:
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    async with (
        LifespanDriver(app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client,
    ):
        yield http_client


def _sort_link(document: str, field: str) -> tuple[str, list[tuple[str, str]]]:
    form_match = re.search(
        (
            r'<form id="(rakit-sort-[^"]+)" method="get" action="([^"]+)" '
            r'class="hidden" aria-hidden="true">(.*?)</form>'
        ),
        document,
        flags=re.DOTALL,
    )
    assert form_match is not None
    form_id, action, body = form_match.groups()
    buttons = re.finditer(
        rf'<button\s+type="submit"\s+form="{re.escape(form_id)}"\s+name="sort"\s+value="([^"]+)"[^>]*>(.*?)</button>',
        document,
        flags=re.DOTALL,
    )
    button_value: str | None = None
    for button in buttons:
        candidate_value, candidate_body = button.groups()
        candidate_text = html.unescape(re.sub(r"<[^>]+>", "", candidate_body)).strip()
        if candidate_text == field:
            button_value = candidate_value
            break
    assert button_value is not None
    hidden = re.findall(
        r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"\s*/?>',
        body,
    )
    pairs = [(html.unescape(name), html.unescape(value)) for name, value in hidden]
    pairs.append(("sort", html.unescape(button_value)))
    url = f"{html.unescape(action)}?{urlencode(pairs)}"
    return url, pairs


def _search_form(document: str) -> tuple[str, list[tuple[str, str]]]:
    form_match = re.search(
        r'<form[^>]+data-rakit-search[^>]+action="([^"]+)"[^>]*>(.*?)</form>',
        document,
        flags=re.DOTALL,
    )
    assert form_match is not None
    action, body = form_match.groups()
    hidden = re.findall(
        r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"\s*/?>',
        body,
    )
    return html.unescape(action), [
        (html.unescape(name), html.unescape(value)) for name, value in hidden
    ]


def _table_cell_texts(document: str) -> list[str]:
    return [
        html.unescape(re.sub(r"<[^>]+>", "", cell)).strip()
        for cell in re.findall(r"<td[^>]*>(.*?)</td>", document, flags=re.DOTALL)
    ]


def _pagination_link(document: str, label: str) -> tuple[str, list[tuple[str, str]]] | None:
    match = re.search(rf'<a[^>]+aria-label="{re.escape(label)}"[^>]+href="([^"]+)"', document)
    if match is None:
        return None
    url = html.unescape(match.group(1))
    return url, parse_qsl(urlsplit(url).query, keep_blank_values=True)


def _has_pagination_landmark(document: str) -> bool:
    return re.search(r'<nav[^>]+aria-label="Resource pagination"', document) is not None


def _has_current_page(document: str, page: int) -> bool:
    return (
        re.search(
            rf'aria-current="page"[^>]*>\s*{page}\s*</(?:a|span)>',
            document,
        )
        is not None
    )


def _sorted_header_has_field(document: str, *, aria_sort: str, field: str) -> bool:
    match = re.search(
        rf'<th[^>]*aria-sort="{re.escape(aria_sort)}"[^>]*>(.*?)</th>',
        document,
        flags=re.DOTALL,
    )
    if match is None:
        return False
    text_content = html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    return field in text_content.split()


async def _assert_pagination_controls(
    client: httpx.AsyncClient,
    *,
    prefix: str,
    count_policy: str,
) -> None:
    params: list[tuple[str, str | int | float | None]] = [
        ("filter", "id:gte:1"),
        ("filter", "email:contains:."),
        ("search", "e"),
        ("sort", "-name,email"),
        ("per_page", "1"),
        ("count_policy", count_policy),
    ]

    first = await client.get(f"{prefix}/users", params=params)
    assert first.status_code == 200
    assert _has_pagination_landmark(first.text)
    assert _has_current_page(first.text, 1)
    assert _pagination_link(first.text, "Previous results") is None
    first_next = _pagination_link(first.text, "Next results")
    assert first_next is not None

    middle = await client.get(f"{prefix}/users", params=[*params, ("page", "2")])
    assert middle.status_code == 200
    assert _has_current_page(middle.text, 2)
    previous = _pagination_link(middle.text, "Previous results")
    next_ = _pagination_link(middle.text, "Next results")
    assert previous is not None
    assert next_ is not None

    expected_without_page = params
    for url, pairs, expected_page in (
        (*previous, "1"),
        (*next_, "3"),
    ):
        assert url.startswith(f"{prefix}/users?")
        assert [(key, value) for key, value in pairs if key != "page"] == expected_without_page
        assert [value for key, value in pairs if key == "page"] == [expected_page]
        followed = await client.get(url)
        assert followed.status_code == 200

    last = await client.get(f"{prefix}/users", params=[*params, ("page", "3")])
    assert last.status_code == 200
    assert _has_current_page(last.text, 3)
    assert _pagination_link(last.text, "Previous results") is not None
    assert _pagination_link(last.text, "Next results") is None


async def _assert_controls_preserve_active_query(
    client: httpx.AsyncClient,
    *,
    prefix: str,
) -> None:
    filters = ("name:contains:a", "email:contains:example.com")
    response = await client.get(
        f"{prefix}/users",
        params=[
            ("filter", filters[0]),
            ("filter", filters[1]),
            ("sort", "-name"),
            ("search", "a"),
            ("page", "2"),
            ("per_page", "1"),
            ("count_policy", "disabled"),
        ],
    )

    sort_url, sort_pairs = _sort_link(response.text, "email")
    assert sort_url.startswith(f"{prefix}/users?")
    assert [value for key, value in sort_pairs if key == "filter"] == list(filters)
    assert ("search", "a") in sort_pairs
    assert ("per_page", "1") in sort_pairs
    assert ("count_policy", "disabled") in sort_pairs
    assert not any(key == "page" for key, _value in sort_pairs)

    sorted_response = await client.get(sort_url)
    assert sorted_response.status_code == 200
    assert "Ada" in sorted_response.text
    assert "Grace" not in sorted_response.text

    action, hidden_pairs = _search_form(response.text)
    assert action == f"{prefix}/users"
    assert [value for key, value in hidden_pairs if key == "filter"] == list(filters)
    assert ("sort", "-name") in hidden_pairs
    assert ("per_page", "1") in hidden_pairs
    assert ("count_policy", "disabled") in hidden_pairs
    assert not any(key == "page" for key, _value in hidden_pairs)

    searched_response = await client.get(action, params=[*hidden_pairs, ("search", "Grace")])
    assert searched_response.status_code == 200
    assert "Ada" not in _table_cell_texts(searched_response.text)
    assert "Grace" not in _table_cell_texts(searched_response.text)


async def _assert_multi_column_sort_links(
    client: httpx.AsyncClient,
    *,
    prefix: str,
) -> None:
    response = await client.get(
        f"{prefix}/users",
        params=[
            ("filter", "email:contains:example.com"),
            ("sort", "-name,email"),
            ("search", "a"),
            ("page", "2"),
            ("per_page", "1"),
            ("count_policy", "disabled"),
        ],
    )
    assert response.status_code == 200

    # `id` is the adapter tie-breaker but remains absent from the first two
    # links until the user explicitly clicks that column.
    expected_sorts = {
        "name": "name,email",
        "email": "-name,-email",
        "id": "-name,email,id",
    }
    for field, expected_sort in expected_sorts.items():
        sort_url, pairs = _sort_link(response.text, field)
        assert sort_url.startswith(f"{prefix}/users?")
        assert [value for key, value in pairs if key == "sort"] == [expected_sort]
        assert ("filter", "email:contains:example.com") in pairs
        assert ("search", "a") in pairs
        assert ("per_page", "1") in pairs
        assert ("count_policy", "disabled") in pairs
        assert not any(key == "page" for key, _value in pairs)

        followed = await client.get(sort_url)
        assert followed.status_code == 200


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    factory, engine = await _seeded_factory()
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.install(SQLAlchemyPlugin(session_factory=factory))
    admin.register(UserAdmin)
    async with _client_for(admin) as http_client:
        yield http_client
    await engine.dispose()


async def test_deferred_count_has_separate_fragment(client: httpx.AsyncClient) -> None:
    page = await client.get("/users?count_policy=deferred")
    assert "data-rakit-total-deferred" in page.text
    assert "Calculating" in page.text
    count = await client.get("/users/_count", headers={"HX-Request": "true"})
    assert count.text.strip() == "2"


async def test_exact_count_renders_total_inline(client: httpx.AsyncClient) -> None:
    page = await client.get("/users")
    assert "2 total" in page.text
    assert "Calculating total" not in page.text


async def test_deferred_count_fragment_respects_search(client: httpx.AsyncClient) -> None:
    count = await client.get(
        "/users/_count", params={"search": "work"}, headers={"HX-Request": "true"}
    )
    assert count.text.strip() == "1"
    assert count.headers["cache-control"] == "no-store"


async def test_filter_via_url_param(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"filter": "name:eq:Ada"})
    assert response.status_code == 200
    assert "Ada" in response.text
    assert "Grace" not in response.text


async def test_invalid_typed_filter_returns_safe_client_error(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"filter": "id:gte:not-an-integer"})

    assert response.status_code == 400
    assert response.json() == {
        "code": "validation.failed",
        "message": "Invalid filter value",
        "details": {"field": "id", "operator": "gte"},
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("raw_filter", "visible_names"),
    [
        ("__table__:eq:users", ("Ada", "Grace")),
        ("name:drop:Ada", ("Ada", "Grace")),
        ("name:eq:x' OR 1=1 --", ()),
    ],
)
async def test_filter_whitelist_operator_and_bound_value_injection_resistance(
    client: httpx.AsyncClient,
    raw_filter: str,
    visible_names: tuple[str, ...],
) -> None:
    response = await client.get("/users", params={"filter": raw_filter})

    assert response.status_code == 200
    for name in ("Ada", "Grace"):
        assert (name in response.text) is (name in visible_names)


async def test_search_via_url_param(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"search": "work"})
    assert response.status_code == 200
    assert "Grace" in response.text
    assert "Ada" not in response.text


async def test_per_page_over_max_falls_back_to_default(client: httpx.AsyncClient) -> None:
    # per_page=99999 violates OffsetPagination's le=200 bound; parse_query must
    # not let it through -- it falls back to the default query (both rows fit).
    response = await client.get("/users", params={"per_page": "99999"})
    assert response.status_code == 200
    assert "Ada" in response.text
    assert "Grace" in response.text


async def test_sort_header_control_omits_page(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"page": "1", "sort": "name"})
    sort_url, sort_pairs = _sort_link(response.text, "name")

    assert ("sort", "-name") in sort_pairs
    assert not any(key == "page" for key, _value in sort_pairs)
    assert not any(key == "page" for key, _value in parse_qsl(urlsplit(sort_url).query))


async def test_sort_and_search_controls_preserve_active_query_standalone(
    client: httpx.AsyncClient,
) -> None:
    await _assert_controls_preserve_active_query(client, prefix="")


async def test_sort_and_search_controls_preserve_active_query_when_mounted() -> None:
    factory, engine = await _seeded_factory()
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.install(SQLAlchemyPlugin(session_factory=factory))
    admin.register(UserAdmin)
    child_app = admin.asgi()
    mounted_app = Starlette(routes=[Mount("/admin", app=child_app)])
    transport = httpx.ASGITransport(app=mounted_app)
    async with (
        LifespanDriver(child_app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as mounted_client,
    ):
        await _assert_controls_preserve_active_query(mounted_client, prefix="/admin")
    await engine.dispose()


async def test_multi_column_sort_links_preserve_sequence_standalone(
    client: httpx.AsyncClient,
) -> None:
    await _assert_multi_column_sort_links(client, prefix="")


async def test_multi_column_sort_links_preserve_sequence_when_mounted() -> None:
    factory, engine = await _seeded_factory()
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.install(SQLAlchemyPlugin(session_factory=factory))
    admin.register(UserAdmin)
    child_app = admin.asgi()
    mounted_app = Starlette(routes=[Mount("/admin", app=child_app)])
    transport = httpx.ASGITransport(app=mounted_app)
    async with (
        LifespanDriver(child_app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as mounted_client,
    ):
        await _assert_multi_column_sort_links(mounted_client, prefix="/admin")
    await engine.dispose()


@pytest.mark.parametrize("count_policy", ("exact", "deferred", "disabled"))
async def test_pagination_controls_preserve_validated_query_standalone(
    count_policy: str,
) -> None:
    factory, engine = await _seeded_factory(include_third=True)
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.install(SQLAlchemyPlugin(session_factory=factory))
    admin.register(UserAdmin)
    async with _client_for(admin) as standalone_client:
        await _assert_pagination_controls(standalone_client, prefix="", count_policy=count_policy)
    await engine.dispose()


@pytest.mark.parametrize("count_policy", ("exact", "deferred", "disabled"))
async def test_pagination_controls_preserve_validated_query_when_mounted(
    count_policy: str,
) -> None:
    factory, engine = await _seeded_factory(include_third=True)
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
    )
    admin.install(SQLAlchemyPlugin(session_factory=factory))
    admin.register(UserAdmin)
    child_app = admin.asgi()
    mounted_app = Starlette(routes=[Mount("/admin", app=child_app)])
    transport = httpx.ASGITransport(app=mounted_app)
    async with (
        LifespanDriver(child_app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as mounted_client,
    ):
        await _assert_pagination_controls(
            mounted_client, prefix="/admin", count_policy=count_policy
        )
    await engine.dispose()


async def test_sort_headers_render_only_valid_exact_aria_sort_values(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/users", params={"sort": "-name,email"})

    values = re.findall(r'aria-sort="([^"]+)"', response.text)
    assert set(values) <= {"ascending", "descending", "none", "other"}
    assert _sorted_header_has_field(response.text, aria_sort="descending", field="name")
    assert _sorted_header_has_field(response.text, aria_sort="other", field="email")
    assert _sorted_header_has_field(response.text, aria_sort="none", field="id")

    default_response = await client.get("/users")
    assert set(re.findall(r'aria-sort="([^"]+)"', default_response.text)) == {"none"}


async def test_contradictory_duplicate_sort_is_safe_client_error(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/users", params={"sort": "id,-id"})

    assert response.status_code == 400
    assert response.json() == {
        "code": "validation.failed",
        "message": "Invalid sort query",
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("raw_value", ("1", "yes", "maybe", ""))
async def test_is_null_rejects_non_boolean_vocabulary_without_widening_query(
    client: httpx.AsyncClient,
    raw_value: str,
) -> None:
    response = await client.get("/users", params={"filter": f"name:is_null:{raw_value}"})

    assert response.status_code == 200
    assert "Ada" in response.text
    assert "Grace" in response.text
    assert "data-rakit-active-filters" not in response.text


@pytest.mark.parametrize(("raw_value", "has_records"), (("true", False), ("false", True)))
async def test_is_null_accepts_explicit_true_false(
    client: httpx.AsyncClient,
    raw_value: str,
    has_records: bool,
) -> None:
    response = await client.get("/users", params={"filter": f"name:is_null:{raw_value}"})

    assert response.status_code == 200
    assert ("Ada" in response.text) is has_records


def test_query_control_serialization_rejects_unsafe_semantic_values() -> None:
    definition = LegacyFieldFilter(
        filter_id="name",
        label="Name",
        field="name",
    )
    selection = FilterSelection(
        filter_id="name",
        operator=FilterOperator.EQ,
        value={"unexpected": "mapping"},
    )

    with pytest.raises(ValueError):
        serialize_selection(selection, definition)
