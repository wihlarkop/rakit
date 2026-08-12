"""Route-level authentication and authorization enforcement.

Plan 03 round 1 built the auth primitives but wired none of them into
request handling -- every route stayed public. These tests pin the actual
enforcement: a session cookie is resolved into a Principal on every
request, and routes are gated by explicit permission requirements.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from rakit import Admin, ModelAdmin, SecretValue
from rakit_core.auth import Principal, SessionRecord
from rakit_core.crypto import TokenService
from rakit_core.events import EventBus, EventPublisher
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.mutations import MutationHooks
from rakit_core.operations import OperationContext, current_operation_context
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from rakit_web.form_routes import WriteResourceBinding
from rakit_web.resource_routes import build_templates
from rakit_web.security.rate_limit import LoginRateLimiter
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import ASGIApp


class _TestRateLimiter(LoginRateLimiter):
    production_safe = True


class _LifespanDriver:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._startup_complete = asyncio.Event()
        self._shutdown_complete = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "_LifespanDriver":
        async def receive():
            return await self._receive_queue.get()

        async def send(message):
            if message["type"] in ("lifespan.startup.complete", "lifespan.startup.failed"):
                self._startup_complete.set()
            elif message["type"] in ("lifespan.shutdown.complete", "lifespan.shutdown.failed"):
                self._shutdown_complete.set()

        async def run_app() -> None:
            await self._app({"type": "lifespan"}, receive, send)

        self._task = asyncio.create_task(run_app())
        await self._receive_queue.put({"type": "lifespan.startup"})
        await self._startup_complete.wait()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._receive_queue.put({"type": "lifespan.shutdown"})
        await self._shutdown_complete.wait()
        assert self._task is not None
        await self._task


class Base(DeclarativeBase):
    pass


class Widget(Base):
    __tablename__ = "widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)


class WidgetAdmin(ModelAdmin):
    resource_id = "widgets"
    path = "/widgets"
    label = "Widgets"
    singular_label = "Widget"
    model = Widget
    list_fields = ("id", "name")
    detail_fields = ("id", "name")


# --- In-memory auth doubles, parameterized by the permissions granted ----


class _ConfigurableAuthBackend:
    """Grants exactly `permissions` (plus `is_superuser`) to the single
    known user -- so each test can pin precisely which permission is
    present or absent without touching a database."""

    def __init__(
        self, *, permissions: frozenset[str] = frozenset(), is_superuser: bool = False
    ) -> None:
        self._permissions = permissions
        self._is_superuser = is_superuser
        self.active = True

    def _principal(self) -> Principal:
        return Principal(
            subject_id="1",
            authenticated=True,
            permissions=self._permissions,
            is_superuser=self._is_superuser,
        )

    async def authenticate(self, identifier: str, password: str) -> Principal | None:
        if identifier == "admin@example.com" and password == "correct-password":
            return self._principal()
        return None

    async def resolve_principal(self, subject_id: str) -> Principal | None:
        if subject_id != "1" or not self.active:
            return None
        return self._principal()


class _FakeSessionStore:
    production_safe = True

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._tokens: dict[str, str] = {}
        self._next_id = 1

    async def create(self, principal: Principal) -> tuple[str, SessionRecord]:
        assert principal.subject_id is not None
        session_id = str(self._next_id)
        self._next_id += 1
        raw_token = f"token-{session_id}"
        now = datetime.now(UTC)
        record = SessionRecord(
            session_id=session_id,
            subject_id=principal.subject_id,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )
        self._sessions[session_id] = record
        self._tokens[raw_token] = session_id
        return raw_token, record

    async def resolve(self, raw_token: str) -> SessionRecord | None:
        session_id = self._tokens.get(raw_token)
        return self._sessions.get(session_id) if session_id else None

    async def rotate(self, session_id: str) -> tuple[str, SessionRecord]:
        raise NotImplementedError

    async def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._tokens = {t: sid for t, sid in self._tokens.items() if sid != session_id}


class _SafeIdempotencyStore:
    production_safe = True

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        return None

    async def release(self, reservation: IdempotencyReservation) -> None:
        return None

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Widget(id=1, name="Sprocket"))
        await session.commit()
    yield factory
    await engine.dispose()


def _build_admin(session_factory, backend: _ConfigurableAuthBackend) -> Admin:
    from rakit.sqlalchemy import SQLAlchemyPlugin

    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=backend,
        session_store=_FakeSessionStore(),
        login_rate_limiter=_TestRateLimiter(),
    )
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin.register(WidgetAdmin)
    return admin


def _build_write_admin(
    session_factory,
    backend: _ConfigurableAuthBackend,
    *,
    operation_contexts: list[OperationContext] | None = None,
) -> Admin:
    admin = _build_admin(session_factory, backend)
    form_schema = FormSchema(
        fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
    )

    async def capture_context(_plan: object) -> None:
        if operation_contexts is not None:
            context = current_operation_context()
            assert context is not None
            operation_contexts.append(context)

    service = SQLAlchemyMutationService(
        model=Widget,
        session_factory=session_factory,
        form_schema=form_schema,
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="operations"
        ),
        version_field="revision",
        hooks=MutationHooks(pre_event=(capture_context,))
        if operation_contexts is not None
        else None,
    )

    async def allowed(_request: object) -> bool:
        return True

    admin.register_write_resource(
        "widgets",
        WriteResourceBinding(
            path="/widgets",
            label="Widget",
            form_schema=form_schema,
            mutation_service=service,
            templates=build_templates(()),
            authorize=allowed,
            verify_csrf=allowed,
            verify_submission_token=allowed,
            issue_submission_token=lambda _request: "placeholder",
            idempotency_store=_SafeIdempotencyStore(),
        ),
    )
    return admin


async def _client_for(admin: Admin) -> tuple[ASGIApp, httpx.AsyncClient]:
    app = admin.asgi()
    transport = httpx.ASGITransport(app=app)
    return app, httpx.AsyncClient(transport=transport, base_url="http://localhost")


async def _login(client: httpx.AsyncClient, prefix: str = "") -> str:
    """Perform the full browser login flow: fetch the login page for its
    pre-session CSRF token, then submit it with the credentials. Login
    requires that token, so a bare POST is rejected 403 by design."""
    page = await client.get(f"{prefix}/auth/login")
    login_csrf = page.cookies["rakit_login_csrf"]
    client.cookies.set("rakit_login_csrf", login_csrf)
    response = await client.post(
        f"{prefix}/auth/login",
        data={
            "identifier": "admin@example.com",
            "password": "correct-password",
            "login_csrf_token": login_csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.cookies.set("rakit_session", response.cookies["rakit_session"])
    csrf = response.cookies["rakit_csrf"]
    # ASGITransport normalizes localhost cookie domains differently from a
    # browser.  Pin the browser-visible double-submit cookie explicitly.
    client.cookies.set("rakit_csrf", csrf, domain="localhost.local", path="/")
    return csrf


# --- Anonymous access ---------------------------------------------------


async def test_anonymous_resource_list_is_not_served(session_factory) -> None:
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/login"
        assert "Sprocket" not in response.text


async def test_anonymous_resource_detail_is_not_served(session_factory) -> None:
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        response = await client.get("/widgets/1", follow_redirects=False)
        assert response.status_code == 303
        assert "Sprocket" not in response.text


async def test_anonymous_resource_count_is_not_served(session_factory) -> None:
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        response = await client.get("/widgets/_count", follow_redirects=False)
        assert response.status_code == 303


async def test_anonymous_admin_shell_redirects_to_login(session_factory) -> None:
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/login"


# --- Explicitly public routes -------------------------------------------


async def test_login_page_stays_public(session_factory) -> None:
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        assert (await client.get("/auth/login")).status_code == 200


async def test_system_health_and_static_stay_public(session_factory) -> None:
    from rakit_web.assets import static_url

    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        assert (await client.get("/_system/health")).status_code == 200
        assert (await client.get("/_system/ready")).status_code == 200
        # Bundled assets are served under content-hashed names.
        assert (await client.get(static_url("rakit.css"))).status_code == 200


# --- Authenticated + authorized -----------------------------------------


async def test_authenticated_user_with_read_permission_sees_the_list(session_factory) -> None:
    backend = _ConfigurableAuthBackend(
        permissions=frozenset({"operations.access", "operations.resources.widgets.read"})
    )
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        await _login(client)
        response = await client.get("/widgets")
        assert response.status_code == 200
        assert "Sprocket" in response.text


@pytest.mark.anyio
async def test_admin_wires_authenticated_create_update_and_signed_delete(session_factory) -> None:
    """The compiler-visible mutation graph reaches real SQLAlchemy writes."""
    permissions = frozenset(
        {
            "operations.access",
            "operations.resources.widgets.create",
            "operations.resources.widgets.update",
            "operations.resources.widgets.delete",
        }
    )
    app, client = await _client_for(
        _build_write_admin(session_factory, _ConfigurableAuthBackend(permissions=permissions))
    )
    encoded = IdentityCodec().encode(RecordIdentity(values={"id": 1}))

    def hidden_value(page: str, name: str) -> str:
        matched = re.search(rf'name="{name}" value="([^"]+)"', page)
        assert matched is not None
        return matched.group(1)

    async with _LifespanDriver(app), client:
        csrf = await _login(client)

        created_form = await client.get("/widgets/new")
        assert created_form.status_code == 200
        created = await client.post(
            "/widgets/new",
            data={
                "name": "Created",
                "csrf_token": csrf,
                "submission_token": hidden_value(created_form.text, "submission_token"),
            },
            follow_redirects=False,
        )
        assert created.status_code == 303

        edit_form = await client.get(f"/widgets/{encoded}/edit")
        assert edit_form.status_code == 200
        updated = await client.post(
            f"/widgets/{encoded}/edit",
            data={
                "name": "Updated",
                "csrf_token": csrf,
                "submission_token": hidden_value(edit_form.text, "submission_token"),
                "concurrency_token": hidden_value(edit_form.text, "concurrency_token"),
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303

        delete_form = await client.get(f"/widgets/{encoded}/delete")
        assert delete_form.status_code == 200
        deleted = await client.post(
            f"/widgets/{encoded}/delete",
            data={
                "csrf_token": csrf,
                "delete_token": hidden_value(delete_form.text, "delete_token"),
                "submission_token": hidden_value(delete_form.text, "submission_token"),
            },
            follow_redirects=False,
        )
    assert deleted.status_code == 303


@pytest.mark.anyio
async def test_admin_write_uses_an_operation_scoped_event_publisher(session_factory) -> None:
    contexts: list[OperationContext] = []
    permissions = frozenset({"operations.access", "operations.resources.widgets.create"})
    admin = _build_write_admin(
        session_factory,
        _ConfigurableAuthBackend(permissions=permissions),
        operation_contexts=contexts,
    )
    app, client = await _client_for(admin)

    async with _LifespanDriver(app), client:
        csrf = await _login(client)
        form = await client.get("/widgets/new")
        submission = re.search(r'name="submission_token" value="([^"]+)"', form.text)
        assert submission is not None
        response = await client.post(
            "/widgets/new",
            data={
                "name": "Scoped",
                "csrf_token": csrf,
                "submission_token": submission.group(1),
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert len(contexts) == 1
    context = contexts[0]
    assert context.services is not None
    assert context.events is context.services.require(EventPublisher)
    assert context.events.bus is context.services.require(EventBus)


@pytest.mark.anyio
async def test_read_permission_does_not_authorize_mutation_submission(session_factory) -> None:
    permissions = frozenset({"operations.access", "operations.resources.widgets.read"})
    app, client = await _client_for(
        _build_write_admin(session_factory, _ConfigurableAuthBackend(permissions=permissions))
    )
    async with _LifespanDriver(app), client:
        await _login(client)
        response = await client.post("/widgets/new", data={"name": "forged"})
    assert response.status_code == 403


async def test_authenticated_user_without_read_permission_gets_403(session_factory) -> None:
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        await _login(client)
        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 403
        assert "Sprocket" not in response.text


async def test_authenticated_user_without_access_permission_gets_403_on_shell(
    session_factory,
) -> None:
    backend = _ConfigurableAuthBackend(permissions=frozenset())
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        await _login(client)
        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 403


async def test_superuser_bypasses_missing_resource_permission(session_factory) -> None:
    backend = _ConfigurableAuthBackend(permissions=frozenset(), is_superuser=True)
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        await _login(client)
        response = await client.get("/widgets")
        assert response.status_code == 200
        assert "Sprocket" in response.text


async def test_superuser_bypass_can_be_disabled(session_factory) -> None:
    from rakit.sqlalchemy import SQLAlchemyPlugin

    backend = _ConfigurableAuthBackend(permissions=frozenset(), is_superuser=True)
    admin = Admin(
        admin_id="operations",
        title="Operations",
        debug=False,
        secret_key=SecretValue("x" * 32),
        auth_backend=backend,
        session_store=_FakeSessionStore(),
        login_rate_limiter=_TestRateLimiter(),
        superuser_bypass=False,
    )
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin.register(WidgetAdmin)

    app, client = await _client_for(admin)
    async with _LifespanDriver(app), client:
        await _login(client)
        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 403


# --- Session invalidation reflected on subsequent requests --------------


async def test_deactivated_user_is_treated_as_unauthenticated(session_factory) -> None:
    """resolve_principal returning None (user deleted or deactivated since
    login) must make the request anonymous, not merely permission-less."""
    backend = _ConfigurableAuthBackend(
        permissions=frozenset({"operations.access", "operations.resources.widgets.read"})
    )
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        await _login(client)
        assert (await client.get("/widgets")).status_code == 200

        backend.active = False
        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/login"


async def test_revoked_session_is_treated_as_unauthenticated(session_factory) -> None:
    backend = _ConfigurableAuthBackend(
        permissions=frozenset({"operations.access", "operations.resources.widgets.read"})
    )
    admin = _build_admin(session_factory, backend)
    app, client = await _client_for(admin)
    async with _LifespanDriver(app), client:
        page = await client.get("/auth/login")
        login_csrf = page.cookies["rakit_login_csrf"]
        client.cookies.set("rakit_login_csrf", login_csrf)
        login = await client.post(
            "/auth/login",
            data={
                "identifier": "admin@example.com",
                "password": "correct-password",
                "login_csrf_token": login_csrf,
            },
            follow_redirects=False,
        )
        raw_token = login.cookies["rakit_session"]
        csrf_token = login.cookies["rakit_csrf"]
        client.cookies.set("rakit_session", raw_token)
        client.cookies.set("rakit_csrf", csrf_token)

        assert (await client.get("/widgets")).status_code == 200

        logout = await client.post(
            "/auth/logout", data={"csrf_token": csrf_token}, follow_redirects=False
        )
        assert logout.status_code == 303

        client.cookies.set("rakit_session", raw_token)
        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 303


async def test_unknown_session_cookie_is_treated_as_unauthenticated(session_factory) -> None:
    backend = _ConfigurableAuthBackend(
        permissions=frozenset({"operations.access", "operations.resources.widgets.read"})
    )
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        client.cookies.set("rakit_session", "not-a-real-token")
        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 303


# --- No-auth mode remains explicitly public -----------------------------


async def test_no_auth_admin_serves_resources_publicly(session_factory) -> None:
    from rakit.sqlalchemy import SQLAlchemyPlugin

    admin = Admin(admin_id="operations", title="Operations", debug=True)
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin.register(WidgetAdmin)

    app, client = await _client_for(admin)
    async with _LifespanDriver(app), client:
        response = await client.get("/widgets")
        assert response.status_code == 200
        assert "Sprocket" in response.text
        assert (await client.get("/")).status_code == 200


# --- Mounted admin ------------------------------------------------------


async def test_mounted_admin_redirects_anonymous_requests_to_the_mounted_login(
    session_factory,
) -> None:
    backend = _ConfigurableAuthBackend(
        permissions=frozenset({"operations.access", "operations.resources.widgets.read"})
    )
    child_app = _build_admin(session_factory, backend).asgi()
    mounted_app = Starlette(routes=[Mount("/admin", app=child_app)])
    transport = httpx.ASGITransport(app=mounted_app)
    async with (
        _LifespanDriver(child_app),
        httpx.AsyncClient(transport=transport, base_url="http://localhost") as client,
    ):
        response = await client.get("/admin/widgets", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/auth/login"

        await _login(client, prefix="/admin")
        allowed = await client.get("/admin/widgets")
        assert allowed.status_code == 200
        assert "Sprocket" in allowed.text


async def test_login_page_itself_never_redirects_to_itself(session_factory) -> None:
    """A redirect loop would make the admin unusable -- the login route must
    stay public even when unauthenticated, never redirecting to itself."""
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        response = await client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 200


# --- Public-path matching must not be a loose prefix match ---------------


def test_public_path_matching_uses_segment_boundaries_not_bare_prefixes() -> None:
    """A bare `startswith` would treat any path merely *beginning with* a
    public path as public -- so `/auth/loginX`, `/auth/login-and-more`, or a
    future route under `/_systemfoo` would bypass authorization entirely.
    Matching must be exact or at a `/` segment boundary."""
    from rakit_web.security.authentication import is_public_path

    # Genuinely public.
    assert is_public_path("/auth/login")
    assert is_public_path("/auth/logout")
    assert is_public_path("/_system/health")
    assert is_public_path("/_system/static/rakit.css")

    # Must NOT be treated as public.
    assert not is_public_path("/auth/loginX")
    assert not is_public_path("/auth/login-and-more")
    assert not is_public_path("/auth/logoutXYZ")
    assert not is_public_path("/_systemfoo")
    assert not is_public_path("/_system")
    assert not is_public_path("/widgets")
    assert not is_public_path("/")


def test_dot_segment_paths_are_never_treated_as_public() -> None:
    """Even if a client sends an un-normalized path, a `..` traversal that
    starts with a public prefix must not be classified public."""
    from rakit_web.security.authentication import is_public_path

    assert not is_public_path("/auth/login/../widgets")
    assert not is_public_path("/auth/login/..%2fwidgets")
    assert not is_public_path("/_system/../widgets")


def test_nested_resource_paths_resolve_to_the_longest_match() -> None:
    """With nested resource paths, the *most specific* prefix must win.
    Returning whichever matched first would gate `/orders/lines` with
    `/orders`'s permission -- a user holding only `orders.read` would then
    reach a resource they have no permission for."""
    from rakit_web.security.authentication import build_requirement_resolver

    resolve = build_requirement_resolver(
        admin_id="operations",
        resource_paths={"/orders": "orders", "/orders/lines": "order_lines"},
    )

    def permissions_for(path: str) -> tuple[str, ...]:
        requirement = resolve(path)
        assert requirement is not None
        return requirement.permissions

    assert permissions_for("/orders") == ("operations.resources.orders.read",)
    assert permissions_for("/orders/1") == ("operations.resources.orders.read",)
    assert permissions_for("/orders/lines") == ("operations.resources.order_lines.read",)
    assert permissions_for("/orders/lines/7") == ("operations.resources.order_lines.read",)


def test_mutation_routes_require_their_exact_operation_permission() -> None:
    """A read grant must never authorize a write merely because it is under the resource path."""
    from rakit_web.security.authentication import build_requirement_resolver

    resolve = build_requirement_resolver(
        admin_id="operations",
        resource_paths={"/widgets": "widgets"},
        writable_resources=frozenset({"widgets"}),
    )

    def permissions_for(path: str, method: str) -> tuple[str, ...]:
        requirement = resolve(path, method)
        assert requirement is not None
        return requirement.permissions

    assert permissions_for("/widgets/new", "POST") == ("operations.resources.widgets.create",)
    assert permissions_for("/widgets/abc/edit", "POST") == ("operations.resources.widgets.update",)
    assert permissions_for("/widgets/abc/delete", "POST") == (
        "operations.resources.widgets.delete",
    )
    assert permissions_for("/widgets/abc/edit", "GET") == ("operations.resources.widgets.update",)


# --- The /auth namespace is framework-owned ------------------------------


async def test_resource_cannot_claim_a_path_in_the_reserved_auth_namespace(session_factory) -> None:
    """A ResourceAdmin at `/auth/login` would be inserted before the real
    auth routes AND classified public by AuthorizationMiddleware, serving
    its data to anonymous callers with no permission check. The compiler
    must reject it."""
    from rakit.sqlalchemy import SQLAlchemyPlugin
    from rakit_core.errors import RakitError

    for reserved in ("/auth", "/auth/login", "/auth/logout", "/auth/custom"):
        evil = type(
            "EvilAdmin",
            (ModelAdmin,),
            {
                "resource_id": "secrets",
                "path": reserved,
                "label": "Secrets",
                "singular_label": "Secret",
                "model": Widget,
                "list_fields": ("id", "name"),
                "detail_fields": ("id", "name"),
            },
        )
        admin = Admin(admin_id="operations", title="Operations", debug=True)
        admin.install(SQLAlchemyPlugin(session_factory=session_factory))
        admin.register(evil)
        with pytest.raises(RakitError) as caught:
            admin.compile()
        assert caught.value.code == "config.reserved_path", reserved


async def test_auth_namespace_is_reserved_even_when_auth_is_disabled(session_factory) -> None:
    """Reservation is a property of the framework's route namespace, not of
    whether this particular Admin happens to have auth wired up -- otherwise
    a no-auth deployment would silently accept a path that becomes a bypass
    the moment auth is enabled."""
    from rakit.sqlalchemy import SQLAlchemyPlugin
    from rakit_core.errors import RakitError

    evil = type(
        "EvilAdmin",
        (ModelAdmin,),
        {
            "resource_id": "secrets",
            "path": "/auth/login",
            "label": "Secrets",
            "singular_label": "Secret",
            "model": Widget,
            "list_fields": ("id", "name"),
            "detail_fields": ("id", "name"),
        },
    )
    admin = Admin(admin_id="operations", title="Operations", debug=True)  # no auth
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin.register(evil)
    with pytest.raises(RakitError) as caught:
        admin.compile()
    assert caught.value.code == "config.reserved_path"


async def test_auth_routes_appear_in_the_compiled_route_graph(session_factory) -> None:
    """`rakit routes` and the collision checker must reflect runtime
    reality: when auth is enabled, the login/logout routes really exist."""
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    admin = _build_admin(session_factory, backend)
    compiled = admin.compile()
    paths = {(route.path, tuple(sorted(route.methods))) for route in compiled.routes}
    assert ("/auth/login", ("GET",)) in paths
    assert ("/auth/login", ("POST",)) in paths
    assert ("/auth/logout", ("POST",)) in paths


async def test_no_auth_admin_has_no_auth_routes_in_the_graph(session_factory) -> None:
    from rakit.sqlalchemy import SQLAlchemyPlugin

    admin = Admin(admin_id="operations", title="Operations", debug=True)
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin.register(WidgetAdmin)
    compiled = admin.compile()
    assert not any(route.path.startswith("/auth") for route in compiled.routes)


async def test_ordinary_resources_remain_public_in_no_auth_mode(session_factory) -> None:
    """Reserving /auth must not disturb the supported no-auth mode."""
    from rakit.sqlalchemy import SQLAlchemyPlugin

    admin = Admin(admin_id="operations", title="Operations", debug=True)
    admin.install(SQLAlchemyPlugin(session_factory=session_factory))
    admin.register(WidgetAdmin)
    app, client = await _client_for(admin)
    async with _LifespanDriver(app), client:
        response = await client.get("/widgets")
        assert response.status_code == 200
        assert "Sprocket" in response.text


# --- Round 3: an unresolvable subject must end the session --------------


async def test_deactivation_revokes_the_session_so_reactivation_does_not_restore_it(
    session_factory,
) -> None:
    """Treating the request as anonymous is not enough: the session row
    stayed live and the cookie stayed in the browser, so the moment the
    account was re-enabled the *same* pre-deactivation session was
    authenticated again. Disabling an account has to actually end its
    sessions, not pause them.
    """
    backend = _ConfigurableAuthBackend(
        permissions=frozenset({"operations.access", "operations.resources.widgets.read"})
    )
    admin = _build_admin(session_factory, backend)
    store = cast(_FakeSessionStore, admin._session_store)
    app, client = await _client_for(admin)
    async with _LifespanDriver(app), client:
        await _login(client)
        assert (await client.get("/widgets")).status_code == 200
        assert store._sessions

        backend.active = False
        assert (await client.get("/widgets", follow_redirects=False)).status_code == 303
        assert not store._sessions, "the session must be revoked, not merely ignored"

        backend.active = True
        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 303, "reactivation must not restore the old session"


async def test_an_unresolvable_subject_clears_the_browser_session_cookie(
    session_factory,
) -> None:
    """Leaving a now-useless cookie in the browser means every subsequent
    request pays a session lookup and a backend lookup to reach the same
    anonymous answer, and leaves a credential-shaped value sitting in the
    client.
    """
    backend = _ConfigurableAuthBackend(
        permissions=frozenset({"operations.access", "operations.resources.widgets.read"})
    )
    admin = _build_admin(session_factory, backend)
    app, client = await _client_for(admin)
    async with _LifespanDriver(app), client:
        await _login(client)
        backend.active = False
        response = await client.get("/widgets", follow_redirects=False)
        set_cookie = response.headers.get_list("set-cookie")
        assert any("rakit_session=" in value for value in set_cookie), set_cookie
        assert any(
            'rakit_session=""' in value or "rakit_session=;" in value for value in set_cookie
        ), set_cookie


async def test_a_deleted_subject_also_revokes_the_session(session_factory) -> None:
    """Deletion and deactivation reach the middleware identically -- both
    are `resolve_principal` returning None -- and must be handled the same.
    """

    class _DeletingBackend(_ConfigurableAuthBackend):
        deleted = False

        async def resolve_principal(self, subject_id: str) -> Principal | None:
            return None if self.deleted else await super().resolve_principal(subject_id)

    backend = _DeletingBackend(permissions=frozenset({"operations.access"}))
    backend.deleted = False
    admin = _build_admin(session_factory, backend)
    store = cast(_FakeSessionStore, admin._session_store)
    app, client = await _client_for(admin)
    async with _LifespanDriver(app), client:
        await _login(client)
        backend.deleted = True
        assert (await client.get("/widgets", follow_redirects=False)).status_code == 303
        assert not store._sessions


async def test_an_unauthenticated_principal_also_revokes_the_session(session_factory) -> None:
    """A backend returning a Principal with `authenticated=False` is the
    same failure as returning None, and must not leave the session live.
    """

    class _DowngradingBackend(_ConfigurableAuthBackend):
        downgraded = False

        async def resolve_principal(self, subject_id: str) -> Principal | None:
            if self.downgraded:
                return Principal(subject_id=subject_id, authenticated=False)
            return await super().resolve_principal(subject_id)

    backend = _DowngradingBackend(permissions=frozenset({"operations.access"}))
    backend.downgraded = False
    admin = _build_admin(session_factory, backend)
    store = cast(_FakeSessionStore, admin._session_store)
    app, client = await _client_for(admin)
    async with _LifespanDriver(app), client:
        await _login(client)
        backend.downgraded = True
        assert (await client.get("/widgets", follow_redirects=False)).status_code == 303
        assert not store._sessions


async def test_no_cookie_at_all_is_not_treated_as_an_invalidated_session(
    session_factory,
) -> None:
    """An anonymous first-time visitor must not be sent a session-clearing
    Set-Cookie -- there is nothing to clear, and emitting one on every
    anonymous request would be noise on the hot path.
    """
    backend = _ConfigurableAuthBackend(permissions=frozenset({"operations.access"}))
    app, client = await _client_for(_build_admin(session_factory, backend))
    async with _LifespanDriver(app), client:
        response = await client.get("/widgets", follow_redirects=False)
        assert response.status_code == 303
        assert not any(
            "rakit_session=" in value for value in response.headers.get_list("set-cookie")
        )
