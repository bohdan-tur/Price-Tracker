import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.routers import auth, health, item, user
from app.core.config import settings
from app.core.logging import setup_logging
from app.database.seed import seed_database

setup_logging()
logger = logging.getLogger("root")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting...")

    if settings.SEED_DEFAULT_USERS:
        try:
            logger.info("Starting database seeding...")
            await seed_database()
            logger.info("Database seeding completed successfully")
        except Exception:
            logger.exception("Error during database seeding")
            raise

    logger.info("Application started successfully")

    try:
        yield
    finally:
        logger.info("Application is shutting down")


app = FastAPI(title="Price Tracker", description="Price Tracker API", lifespan=lifespan)


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
app.include_router(health.router)
