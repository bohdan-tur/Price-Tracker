import asyncio
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


async def test_liveness_probe(async_client: AsyncClient):
    response = await async_client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "pass"}
    assert (
        response.headers.get("cache-control") == "no-cache, no-store, must-revalidate"
    )


async def test_readiness_probe_success(async_client: AsyncClient):
    response = await async_client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "pass"
    assert "database" in data["checks"]
    assert data["checks"]["database"]["status"] == "pass"
    assert data["checks"]["redis"]["status"] == "pass"
    assert (
        response.headers.get("cache-control") == "no-cache, no-store, must-revalidate"
    )


async def test_readiness_probe_db_failure(async_client: AsyncClient):
    with patch("sqlalchemy.ext.asyncio.AsyncSession.execute") as mock_execute:
        mock_execute.side_effect = Exception("Connection refused")

        response = await async_client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()

        assert data["status"] == "fail"
        assert data["checks"]["database"]["status"] == "fail"
        assert "Connection refused" in data["checks"]["database"]["detail"]


async def test_readiness_probe_db_timeout(async_client: AsyncClient):
    with patch("sqlalchemy.ext.asyncio.AsyncSession.execute") as mock_execute:
        mock_execute.side_effect = asyncio.TimeoutError("Query timed out")

        response = await async_client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()

        assert data["status"] == "fail"
        assert data["checks"]["database"]["status"] == "fail"
        assert "Query timed out" in data["checks"]["database"]["detail"]


async def test_readiness_probe_redis_failure(async_client: AsyncClient):
    with patch(
        "app.api.routers.health.check_redis_connection",
        new=AsyncMock(side_effect=ConnectionError("Redis unavailable")),
    ):
        response = await async_client.get("/health/ready")

    assert response.status_code == 503
    data = response.json()

    assert data["status"] == "fail"
    assert data["checks"]["database"]["status"] == "pass"
    assert data["checks"]["redis"]["status"] == "fail"
    assert "Redis unavailable" in data["checks"]["redis"]["detail"]
