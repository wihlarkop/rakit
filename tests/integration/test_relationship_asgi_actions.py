"""Real SQLAlchemy-backed record action through real HTTP."""

import re
from urllib.parse import urlencode

import pytest
from sqlalchemy import update

from .rakit_integration import (
    CommitRecorder,
    IntegrationApp,
    Order,
    client_for,
)


def _tokens(page_text: str) -> dict[str, str]:
    return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', page_text))


@pytest.mark.anyio
async def test_record_action_persists_through_real_mutation_service(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        page = await client.get(f"/orders/{parent}/_actions/approve")
        assert page.status_code == 200
        assert "Approve order" in page.text
        tokens = _tokens(page.text)
        assert "submission_token" in tokens
        assert "concurrency_token" in tokens

        recorder = CommitRecorder(app.engine)
        approved = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        recorder.close(app.engine)

    assert approved.status_code == 303
    assert recorder.commits == 1
    async with app.session_factory() as session:
        order = await session.get(Order, 10)
        assert order is not None
        assert order.status == "approved"
        assert order.version == 2


@pytest.mark.anyio
async def test_record_action_availability_rechecked_against_fresh_state(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        page = await client.get(f"/orders/{parent}/_actions/approve")
        tokens = _tokens(page.text)
        async with app.session_factory() as session:
            await session.execute(
                update(Order)
                .where(Order.id == 10)
                .values(status="cancelled", version=Order.version + 1)
            )
            await session.commit()
        recorder = CommitRecorder(app.engine)
        rejected = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        recorder.close(app.engine)

    assert rejected.status_code == 409
    assert "no longer available" in rejected.text
    assert recorder.commits == 0
    async with app.session_factory() as session:
        order = await session.get(Order, 10)
        assert order is not None
        assert order.status == "cancelled"
        assert order.version == 2


@pytest.mark.anyio
async def test_record_action_stale_concurrency_never_persists(
    integration: tuple[IntegrationApp, dict[str, object]],
    parent: str,
) -> None:
    app, _ = integration
    async with client_for(app) as client:
        page = await client.get(f"/orders/{parent}/_actions/approve")
        tokens = _tokens(page.text)
        async with app.session_factory() as session:
            await session.execute(
                update(Order).where(Order.id == 10).values(version=Order.version + 1)
            )
            await session.commit()
        recorder = CommitRecorder(app.engine)
        rejected = await client.post(
            f"/orders/{parent}/_actions/approve",
            content=urlencode(
                [
                    ("csrf_token", "csrf"),
                    ("submission_token", tokens["submission_token"]),
                    ("concurrency_token", tokens["concurrency_token"]),
                ]
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        recorder.close(app.engine)

    assert rejected.status_code == 409
    assert recorder.commits == 0
    async with app.session_factory() as session:
        order = await session.get(Order, 10)
        assert order is not None
        assert order.status == "draft"
        assert order.version == 2
