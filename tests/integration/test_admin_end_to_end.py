"""Plan 07 release-level happy path across the official packages.

This suite intentionally complements the narrower package tests. It drives a real
SQLAlchemy-authenticated Admin, the real relationship/action HTTP integration
fixture, and the real private LocalStorage backend in one release journey.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from rakit import Admin, SecretValue
from rakit_auth_sqlalchemy.models import Base as AuthBase
from rakit_auth_sqlalchemy.models import User
from rakit_auth_sqlalchemy.passwords import Argon2PasswordHasher
from rakit_auth_sqlalchemy.plugin import SQLAlchemyAuthPlugin
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_storage import TemporaryUpload
from rakit_storage_local import LocalStorage
from rakit_web.security.rate_limit import LoginRateLimiter
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.types import ASGIApp

from .rakit_integration import (
    IntegrationApp,
    client_for,
    encode_form,
    fetch_order_relationship,
    fetch_orders,
    parsed_form,
    relationship_prefix,
    replace_control,
)


class _ReleaseRateLimiter(LoginRateLimiter):
    production_safe = True


class _LifespanDriver:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.receive_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "_LifespanDriver":
        async def receive() -> dict[str, str]:
            return await self.receive_queue.get()

        async def send(message: dict[str, Any]) -> None:
            if message["type"].startswith("lifespan.startup"):
                self.started.set()
            elif message["type"].startswith("lifespan.shutdown"):
                self.stopped.set()

        async def run() -> None:
            await self.app({"type": "lifespan"}, receive, send)

        self.task = asyncio.create_task(run())
        await self.receive_queue.put({"type": "lifespan.startup"})
        await self.started.wait()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.receive_queue.put({"type": "lifespan.shutdown"})
        await self.stopped.wait()
        assert self.task is not None
        await self.task


async def _authenticated_admin(tmp_path: Any) -> tuple[ASGIApp, Any]:
    database = tmp_path / "release-auth.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(AuthBase.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    password_hash = await Argon2PasswordHasher().hash("release-password")
    async with factory() as session:
        session.add(
            User(
                email="admin@example.com",
                password_hash=password_hash,
                is_superuser=True,
            )
        )
        await session.commit()

    auth = SQLAlchemyAuthPlugin(factory)
    admin = Admin(
        admin_id="release",
        title="Release Admin",
        debug=True,
        secret_key=SecretValue("r" * 32),
        auth_backend=auth.auth_backend,
        session_store=auth.session_store,
        login_rate_limiter=_ReleaseRateLimiter(),
    )
    return admin.asgi(), engine


async def _login(client: httpx.AsyncClient) -> None:
    page = await client.get("/auth/login")
    token = page.cookies["rakit_login_csrf"]
    client.cookies.set("rakit_login_csrf", token)
    response = await client.post(
        "/auth/login",
        data={
            "identifier": "admin@example.com",
            "password": "release-password",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.cookies.set("rakit_session", response.cookies["rakit_session"])


def _action_tokens(html: str) -> dict[str, str]:
    return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', html))


@pytest.mark.anyio
async def test_release_journey_auth_crud_relationship_action_and_private_file(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
    codec: IdentityCodec,
    tmp_path: Any,
) -> None:
    # Real SQLAlchemy auth backend/session store through the real Admin login routes.
    auth_app, auth_engine = await _authenticated_admin(tmp_path)
    try:
        async with (
            _LifespanDriver(auth_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=auth_app),
                base_url="http://localhost",
            ) as auth_client,
        ):
            anonymous = await auth_client.get("/", follow_redirects=False)
            assert anonymous.status_code == 303
            await _login(auth_client)
            assert (await auth_client.get("/")).status_code == 200
    finally:
        await auth_engine.dispose()

    # Real SQLAlchemy graph mutation: update a scalar and link a relationship.
    app, identities = integration
    tag_two = codec.encode(cast(RecordIdentity, identities["tag_two"]))
    prefix = relationship_prefix("tags")
    async with client_for(app) as client:
        edit = await client.get(f"/orders/{parent}/edit")
        payload = replace_control(parsed_form(edit.text), "status", "review")
        payload.append((f"{prefix}link__{tag_two}", tag_two))
        updated = await client.post(
            f"/orders/{parent}/edit",
            content=encode_form(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert updated.status_code == 303
        assert (await fetch_orders(app.session_factory)) == [("review", 2)]
        assert (await fetch_order_relationship(app.session_factory))[1] == (1, 2)

        # Real record action with fresh availability/concurrency evaluation.
        action_page = await client.get(f"/orders/{parent}/_actions/approve")
        tokens = _action_tokens(action_page.text)
        approved = await client.post(
            f"/orders/{parent}/_actions/approve",
            data={
                "csrf_token": "csrf",
                "submission_token": tokens["submission_token"],
                "concurrency_token": tokens["concurrency_token"],
            },
            follow_redirects=False,
        )
        assert approved.status_code == 303
        assert (await fetch_orders(app.session_factory))[0][0] == "approved"

    # Real secure LocalStorage: generated key, private access, streaming read and delete.
    storage = LocalStorage(
        storage_id="release-files",
        root=tmp_path / "private-files",
        allowed_extensions=(".txt",),
    )

    async def stream() -> AsyncIterator[bytes]:
        yield b"private release artifact"

    stored = await storage.save(
        TemporaryUpload(
            original_name="report.txt",
            content_type="text/plain",
            stream=stream,
            declared_size=len(b"private release artifact"),
        ),
        prefix="reports",
    )
    assert stored.original_name == "report.txt"
    assert "report.txt" not in stored.key
    assert (await storage.resolve_access(stored)).public is False
    assert b"".join([chunk async for chunk in storage.open(stored)]) == b"private release artifact"
    await storage.delete(stored)
    assert not (storage.root / stored.key).exists()
