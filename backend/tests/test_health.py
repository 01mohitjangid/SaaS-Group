from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_liveness_needs_no_dependencies(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "peblo-tv-api"
    assert body["version"]


async def test_readiness_reports_each_dependency(client: httpx.AsyncClient) -> None:
    """Whether or not a database is reachable here, the answer must say which one is down."""
    response = await client.get("/readyz")
    body = response.json()
    checks = body["checks"]
    assert set(checks) == {"database", "storage"}
    assert all(isinstance(check["ok"], bool) for check in checks.values())

    healthy = all(check["ok"] for check in checks.values())
    assert response.status_code == (200 if healthy else 503)
    assert body["status"] == ("ok" if healthy else "degraded")
    # A failing check must name the reason, otherwise the probe is useless on call.
    assert all(check["ok"] or check["detail"] for check in checks.values())


async def test_storage_is_reachable_even_without_a_database(client: httpx.AsyncClient) -> None:
    checks = (await client.get("/readyz")).json()["checks"]
    assert checks["storage"]["ok"] is True


async def test_local_artwork_is_served_so_public_media_urls_resolve(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """`url_for()` promises a fetchable URL; with the local backend the API keeps it."""
    await app.state.storage.put("artwork/demo/poster.jpg", b"not-really-a-jpeg", "image/jpeg")

    response = await client.get("/media/artwork/demo/poster.jpg")
    assert response.status_code == 200
    assert response.content == b"not-really-a-jpeg"

    assert (await client.get("/media/artwork/demo/missing.jpg")).status_code == 404


async def test_only_artwork_is_exposed_not_the_whole_storage_root(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Published catalogues and the validation report live in the same root and are not public."""
    await app.state.storage.put("reports/seed-latest.json", b'{"secret":1}', "application/json")

    assert (await client.get("/media/reports/seed-latest.json")).status_code == 404
    assert (await client.get("/media/../reports/seed-latest.json")).status_code == 404
