import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.bot.application import create_bot
from app.core.config import settings
from app.models.item import Item, ItemStatus
from app.models.notification_event import DeliveryStatus, NotificationEvent
from app.models.price_history import PriceHistory
from app.services.scraper import TransientScraperError, get_current_price
from app.services.telegram_notification_service import (
    deliver_telegram_notification as deliver_telegram_notification_service,
)
from app.worker.celery_app import celery_app

logger = logging.getLogger("root")


class PriceCheckError(RuntimeError):
    """Raised when an item price check finishes unsuccessfully."""


_worker_session_factory: async_sessionmaker[AsyncSession] | None = None
PRICE_CHECK_MAX_RETRIES = 3
PRICE_CHECK_RETRY_BASE_SECONDS = 30
PRICE_CHECK_RETRY_MAX_SECONDS = 300
TELEGRAM_DELIVERY_MAX_RETRIES = 5
TELEGRAM_DISPATCH_BATCH_SIZE = 100
TELEGRAM_PROCESSING_TIMEOUT = timedelta(minutes=15)


def get_worker_session_factory() -> async_sessionmaker[AsyncSession]:
    global _worker_session_factory

    if _worker_session_factory is None:
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.APP_DEBUG,
            poolclass=NullPool,
        )
        _worker_session_factory = async_sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )

    return _worker_session_factory


async def deliver_telegram_notification_async(
    event_id: int,
    can_retry: bool,
) -> bool:
    bot = create_bot()

    try:
        return await deliver_telegram_notification_service(
            event_id=event_id,
            bot=bot,
            session_factory=get_worker_session_factory(),
            can_retry=can_retry,
        )
    finally:
        await bot.session.close()


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

    retryable = False

    try:
        new_price = await get_current_price(str(url))

        error_message = None if new_price is not None else "Price not found"

    except Exception as exc:
        new_price = None
        retryable = isinstance(exc, TransientScraperError)
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

        checked_at = datetime.now(timezone.utc)
        item.last_checked_at = checked_at

        if new_price is None:
            item.status = ItemStatus.ERROR
            item.last_error = error_message

            await session.commit()

            return {
                "status": "error",
                "item_id": item_id,
                "retryable": retryable,
            }

        item.last_successful_check_at = checked_at
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

        notification_event_id: int | None = None

        if target_crossed:
            notification = NotificationEvent(
                item_id=item.id, price_history_id=history.id
            )

            session.add(notification)
            await session.flush()
            notification_event_id = notification.id

        await session.commit()

        if notification_event_id is not None:
            deliver_telegram_notification_task.delay(notification_event_id)

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


async def get_pending_notification_event_ids(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> list[int]:
    if session_factory is None:
        session_factory = get_worker_session_factory()

    async with session_factory() as db:
        stale_before = datetime.now(timezone.utc) - TELEGRAM_PROCESSING_TIMEOUT
        await db.execute(
            update(NotificationEvent)
            .where(
                NotificationEvent.delivery_status == DeliveryStatus.PROCESSING,
                NotificationEvent.processing_started_at <= stale_before,
            )
            .values(
                delivery_status=DeliveryStatus.PENDING,
                processing_started_at=None,
                last_delivery_error=(
                    "Delivery processing timed out and was queued again"
                ),
            )
        )

        result = await db.scalars(
            select(NotificationEvent.id)
            .where(NotificationEvent.delivery_status == DeliveryStatus.PENDING)
            .order_by(
                NotificationEvent.created_at,
                NotificationEvent.id,
            )
            .limit(TELEGRAM_DISPATCH_BATCH_SIZE)
        )

        event_ids = list(result.all())
        await db.commit()
        return event_ids


@celery_app.task(
    bind=True,
    name="scrape_item",
    max_retries=PRICE_CHECK_MAX_RETRIES,
)
def scrape_item(self, item_id: int) -> dict:
    result = asyncio.run(scrape_item_async(item_id))

    if result["status"] != "error":
        return result

    error = PriceCheckError(f"Price check failed for item_id={item_id}")

    if result.get("retryable", False) and self.request.retries < self.max_retries:
        retry_countdown = min(
            PRICE_CHECK_RETRY_BASE_SECONDS * (2**self.request.retries),
            PRICE_CHECK_RETRY_MAX_SECONDS,
        )

        raise self.retry(
            exc=error,
            countdown=retry_countdown,
        ) from error

    raise error


@celery_app.task(name="dispatch_price_checks")
def dispatch_price_checks() -> dict:
    item_ids = asyncio.run(get_trackable_item_ids())

    for item_id in item_ids:
        scrape_item.delay(item_id)

    return {"status": "success", "dispatched_items": len(item_ids)}


@celery_app.task(
    bind=True,
    name="deliver_telegram_notification",
    max_retries=TELEGRAM_DELIVERY_MAX_RETRIES,
)
def deliver_telegram_notification_task(self, event_id: int) -> dict:

    can_retry = self.request.retries < self.max_retries

    try:
        delivered = asyncio.run(
            deliver_telegram_notification_async(
                event_id=event_id,
                can_retry=can_retry,
            )
        )

    except TelegramRetryAfter as error:
        raise self.retry(
            exc=error,
            countdown=error.retry_after,
        ) from error

    except (
        TelegramNetworkError,
        TelegramServerError,
        TimeoutError,
    ) as error:
        retry_countdown = min(
            30 * (2**self.request.retries),
            600,
        )

        raise self.retry(
            exc=error,
            countdown=retry_countdown,
        ) from error

    return {
        "status": "sent" if delivered else "not_sent",
        "event_id": event_id,
    }


@celery_app.task(name="dispatch_pending_telegram_notifications")
def dispatch_pending_telegram_notifications() -> dict:
    event_ids = asyncio.run(get_pending_notification_event_ids())

    for event_id in event_ids:
        deliver_telegram_notification_task.delay(event_id)

    return {
        "status": "success",
        "dispatched_events": len(event_ids),
    }
