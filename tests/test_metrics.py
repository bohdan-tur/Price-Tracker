from httpx import AsyncClient


async def test_metrics_endpoint_exposes_prometheus_metrics(
    async_client: AsyncClient,
):
    await async_client.get("/items/")

    response = await async_client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert "process_cpu_seconds_total" in response.text
