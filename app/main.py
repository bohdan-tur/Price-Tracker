import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from typing import cast

from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.types import ExceptionHandler

from app.api.routers import auth, health, item, telegram, user
from app.bot.application import run_telegram_polling
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.database.seed import seed_database

setup_logging()
logger = logging.getLogger("root")


@asynccontextmanager
async def lifespan(app: FastAPI):
    polling_task: asyncio.Task[None] | None = None
    logger.info("Application starting...")

    if settings.SEED_DEFAULT_USERS:
        try:
            logger.info("Starting database seeding...")
            await seed_database()
            logger.info("Database seeding completed successfully")
        except Exception:
            logger.exception("Error during database seeding")
            raise
    if settings.TELEGRAM_POLLING_ENABLED:
        polling_task = asyncio.create_task(run_telegram_polling())
        logger.info("Telegram polling started")

    logger.info("Application started successfully")

    try:
        yield
    finally:
        if polling_task is not None:
            polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await polling_task
        logger.info("Application is shutting down")


app = FastAPI(title="Price Tracker", description="Price Tracker API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    cast(ExceptionHandler, _rate_limit_exceeded_handler),
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}"

    logger.info(
        f"Method: {request.method} | "
        f"Path: {request.url.path} | "
        f"Status: {response.status_code} | "
        f"Time: {process_time:.4f}s"
    )
    return response


app.include_router(auth.router)
app.include_router(user.router)
app.include_router(item.router)
app.include_router(telegram.router)
app.include_router(health.router)

Instrumentator(
    excluded_handlers=[
        r"^/metrics$",
        r"^/health/live$",
        r"^/health/ready$",
    ],
).instrument(app).expose(app, include_in_schema=False)
