import asyncio

from fastapi import APIRouter, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.dependencies import db_dependency
from app.core.config import settings
from app.schemas.health import HealthCheckComponent, LivenessResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["Health"])
READINESS_TIMEOUT_SECONDS = 2.0


async def check_redis_connection() -> None:
    redis_client = Redis.from_url(settings.RATE_LIMIT_STORAGE_URI)

    try:
        await asyncio.wait_for(
            redis_client.ping(),
            timeout=READINESS_TIMEOUT_SECONDS,
        )
    finally:
        await redis_client.aclose()


@router.get("/live", summary="Liveness Probe", response_model=LivenessResponse)
async def liveness_check(response: Response) -> LivenessResponse:

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return LivenessResponse(status="pass")


@router.get("/ready", summary="Readiness Probe", response_model=ReadinessResponse)
async def readiness_check(response: Response, db: db_dependency) -> ReadinessResponse:

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

    components: dict[str, HealthCheckComponent] = {}
    is_ready = True

    try:
        await asyncio.wait_for(
            db.execute(text("SELECT 1")),
            timeout=READINESS_TIMEOUT_SECONDS,
        )
        components["database"] = HealthCheckComponent(status="pass")
    except Exception as exc:
        components["database"] = HealthCheckComponent(
            status="fail",
            detail=str(exc),
        )
        is_ready = False

    try:
        await check_redis_connection()
        components["redis"] = HealthCheckComponent(status="pass")
    except Exception as exc:
        components["redis"] = HealthCheckComponent(
            status="fail",
            detail=str(exc),
        )
        is_ready = False

    payload = ReadinessResponse(
        status="pass" if is_ready else "fail",
        checks=components,
    )

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return payload
