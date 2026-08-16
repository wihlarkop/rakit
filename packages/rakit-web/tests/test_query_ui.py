import html
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import pytest
from conftest import LifespanDriver
from rakit import Admin, ModelAdmin, SecretValue
from rakit_core.errors import RakitError
from rakit_core.query import Filter, FilterOperator
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_web.resource_routes import _serialize_filter
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
    button = re.search(
        rf'<button\s+type="submit"\s+form="{re.escape(form_id)}"\s+name="sort"\s+value="([^"]+)"[^>]*>\s*{re.escape(field)}\s*</button>',
        document,
        flags=re.DOTALL,
    )
    assert button is not None
    hidden = re.findall(
        r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"\s*/?>',
        body,
    )
    pairs = [(html.unescape(name), html.unescape(value)) for name, value in hidden]
    pairs.append(("sort", html.unescape(button.group(1))))
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
    assert 'nav aria-label="Resource pagination"' in first.text
    assert ">Page 1<" in first.text
    assert _pagination_link(first.text, "Previous page") is None
    first_next = _pagination_link(first.text, "Next page")
    assert first_next is not None

    middle = await client.get(f"{prefix}/users", params=[*params, ("page", "2")])
    assert middle.status_code == 200
    assert ">Page 2<" in middle.text
    previous = _pagination_link(middle.text, "Previous page")
    next_ = _pagination_link(middle.text, "Next page")
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
    assert ">Page 3<" in last.text
    assert _pagination_link(last.text, "Previous page") is not None
    assert _pagination_link(last.text, "Next page") is None


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
    assert "Calculating total" in page.text
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


async def test_sort_header_link_omits_page(client: httpx.AsyncClient) -> None:
    response = await client.get("/users", params={"page": "1", "sort": "name"})
    # Sort-toggle links reset pagination: they never carry a page param forward.
    assert "sort=-name" in response.text
    hrefs = [html.unescape(value) for value in re.findall(r'href="([^"]+)"', response.text)]
    assert all(
        not any(key == "page" for key, _value in parse_qsl(urlsplit(href).query)) for href in hrefs
    )


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
    assert re.search(r'aria-sort="descending"[^>]*>\s*<a[^>]*>name</a>', response.text)
    assert re.search(r'aria-sort="other"[^>]*>\s*<a[^>]*>email</a>', response.text)
    assert re.search(r'aria-sort="none"[^>]*>\s*<a[^>]*>id</a>', response.text)

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
async def test_is_null_rejects_non_boolean_vocabulary_before_query_execution(
    client: httpx.AsyncClient,
    raw_value: str,
) -> None:
    response = await client.get("/users", params={"filter": f"name:is_null:{raw_value}"})

    assert response.status_code == 400
    assert response.json() == {
        "code": "validation.failed",
        "message": "Invalid filter value",
        "details": {"field": "name", "operator": "is_null"},
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("raw_value", "has_records"), (("true", False), ("false", True)))
async def test_is_null_accepts_explicit_true_false(
    client: httpx.AsyncClient,
    raw_value: str,
    has_records: bool,
) -> None:
    response = await client.get("/users", params={"filter": f"name:is_null:{raw_value}"})

    assert response.status_code == 200
    assert ("Ada" in response.text) is has_records


def test_query_control_serialization_rejects_unsafe_filter_shapes() -> None:
    filter_ = Filter(
        field="name",
        operator=FilterOperator.EQ,
        value={"unexpected": "mapping"},
    )

    with pytest.raises(RakitError) as exc_info:
        _serialize_filter(filter_)

    assert exc_info.value.to_public_dict() == {
        "code": "validation.failed",
        "message": "Cannot safely render query controls",
    }
