import os
import subprocess
import sys
import textwrap


def test_reference_app_compiles_bootstraps_and_reaches_readiness(tmp_path) -> None:
    script = textwrap.dedent(
        """
        import asyncio

        from rakit.auth.sqlalchemy import User
        from sqlalchemy import func, select

        from examples.reference_app.app import admin, app
        from examples.reference_app.database import session_factory
        from examples.reference_app.models import Order, Product


        async def main() -> None:
            compiled = admin.compile()
            assert app is not None
            assert {resource.resource_id for resource in compiled.resources} == {
                "customers",
                "products",
                "orders",
                "order_items",
            }
            assert set(admin._write_resource_bindings) == {"products", "orders"}
            assert {action.action_id for action in compiled.actions} == {
                "mark_paid",
                "mark_processing",
            }
            assert {page.page_id for page in compiled.pages} == {"operations"}
            assert {api.resource_id for api in compiled.compiled_resource_apis} == {
                "customers",
                "products",
                "orders",
            }

            await admin.lifecycle.run_startup()
            assert await admin.lifecycle.check_ready() is True
            async with session_factory() as session:
                assert await session.scalar(select(func.count(User.id))) == 2
                assert await session.scalar(select(func.count(Product.id))) == 3
                assert await session.scalar(select(func.count(Order.id))) == 2
            await admin.lifecycle.run_shutdown()
            print("reference-app-smoke: OK")


        asyncio.run(main())
        """
    )
    env = os.environ.copy()
    env["RAKIT_REFERENCE_ROOT"] = str(tmp_path / "reference")

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "reference-app-smoke: OK" in result.stdout
