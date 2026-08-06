import asyncio
import logging
from datetime import datetime, timezone

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.item import Item, ItemStatus
from app.models.notification_event import NotificationEvent
from app.models.price_history import PriceHistory
from app.services.scraper import get_current_price

logger = logging.getLogger("root")

_worker_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_worker_session_factory() -> async_sessionmaker[AsyncSession]:
    global _worker_session_factory

    if _worker_session_factory is None:
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG,
            poolclass=NullPool,
        )
        _worker_session_factory = async_sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )

    return _worker_session_factory


celery_app = Celery(
    "price_tracker", broker="redis://redis:6379/0", backend="redis://redis:6379/0"
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)


async def scrape_item_async(
    item_id: int,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    if session_factory is None:
        session_factory = get_worker_session_factory()

    async with session_factory() as session:
        result = await session.execute(select(Item.url).where(Item.id == item_id))

        url = result.scalar_one_or_none()

    if url is None:
        return {"status": "not_found", "item_id": item_id}

    try:
        new_price = await get_current_price(str(url))

        error_message = None if new_price is not None else "Price not found"

    except Exception as exc:
        new_price = None
        error_message = type(exc).__name__

        logger.warning(
            "Price check failed for item_id=%s error=%s",
            item_id,
            error_message,
        )

    async with session_factory() as session:
        result = await session.execute(
            select(Item).where(Item.id == item_id).with_for_update()
        )

        item = result.scalar_one_or_none()

        if not item:
            return {"item_id": item_id, "status": "not_found"}

        item.last_checked_at = datetime.now(timezone.utc)

        if new_price is None:
            item.status = ItemStatus.ERROR
            item.last_error = error_message

            await session.commit()

            return {
                "status": "error",
                "item_id": item_id,
            }

        previous_price = item.current_price
        item.status = ItemStatus.ACTIVE
        item.last_error = None

        if new_price == previous_price:
            await session.commit()

            return {
                "status": "success",
                "item_id": item_id,
                "price_changed": False,
                "target_crossed": False,
            }

        history = PriceHistory(item_id=item.id, price=new_price, currency=item.currency)
        session.add(history)
        await session.flush()

        item.current_price = new_price

        target_crossed = (
            previous_price is not None
            and item.target_price is not None
            and new_price <= item.target_price
            and previous_price > item.target_price
        )

        if target_crossed:
            notification = NotificationEvent(
                item_id=item.id, price_history_id=history.id
            )

            session.add(notification)

        await session.commit()

        return {
            "status": "success",
            "item_id": item_id,
            "price_changed": True,
            "target_crossed": target_crossed,
        }


async def get_trackable_item_ids(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> list[int]:
    if session_factory is None:
        session_factory = get_worker_session_factory()

    async with session_factory() as db:
        result = await db.execute(
            select(Item.id).where(
                Item.status.in_(
                    [
                        ItemStatus.PENDING,
                        ItemStatus.ACTIVE,
                        ItemStatus.ERROR,
                    ]
                )
            )
        )
        return list(result.scalars().all())


@celery_app.task(name="scrape_item")
def scrape_item(item_id: int) -> dict:
    return asyncio.run(scrape_item_async(item_id))


@celery_app.task(name="dispatch_price_checks")
def dispatch_price_checks() -> dict:
    item_ids = asyncio.run(get_trackable_item_ids())

    for item_id in item_ids:
        scrape_item.delay(item_id)

    return {"status": "success", "dispatched_items": len(item_ids)}


celery_app.conf.beat_schedule = {
    "update-prices-daily": {
        "task": "dispatch_price_checks",
        "schedule": crontab(hour=3, minute=0),
    }
}
