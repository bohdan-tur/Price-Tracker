from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.item import Item
from app.models.notification_event import DeliveryStatus, NotificationEvent
from app.models.price_history import PriceHistory
from app.models.telegram_account import TelegramAccount


@dataclass(frozen=True, slots=True)
class TelegramNotificationPayload:
    event_id: int
    user_id: int
    chat_id: int
    text: str


def build_price_alert_text(
    title: str,
    url: str,
    current_price: Decimal,
    target_price: Decimal | None,
    currency: str,
) -> str:

    target_text = (
        f"{target_price:.2f} {currency}" if target_price is not None else "Not set"
    )

    return (
        "Target price reached!\n\n"
        f"{title}\n"
        f"Current price: {current_price:.2f} {currency}\n"
        f"Target price: {target_text}\n"
        f"URL: {url}"
    )


async def prepare_telegram_notification(
    db: AsyncSession, event_id: int
) -> TelegramNotificationPayload | None:

    event = await db.scalar(
        select(NotificationEvent)
        .where(NotificationEvent.id == event_id)
        .with_for_update()
    )

    if event is None:
        await db.rollback()
        return None

    if event.delivery_status != DeliveryStatus.PENDING:
        await db.rollback()
        return None

    result = await db.execute(
        select(Item, PriceHistory, TelegramAccount)
        .join(PriceHistory, PriceHistory.item_id == Item.id)
        .join(TelegramAccount, TelegramAccount.user_id == Item.user_id)
        .where(
            Item.id == event.item_id,
            PriceHistory.id == event.price_history_id,
            TelegramAccount.is_active.is_(True),
        )
    )

    delivery_data = result.one_or_none()

    if delivery_data is None:
        event.delivery_status = DeliveryStatus.SKIPPED
        event.last_delivery_error = (
            "Active Telegram account or notification data is unavailable"
        )

        await db.commit()
        return None

    item, price_history, telegram_account = delivery_data

    text = build_price_alert_text(
        item.title,
        item.url,
        price_history.price,
        item.target_price,
        price_history.currency,
    )

    event.delivery_status = DeliveryStatus.PROCESSING
    event.delivery_attempts += 1
    event.processing_started_at = datetime.now(timezone.utc)
    event.last_delivery_error = None

    await db.commit()

    return TelegramNotificationPayload(
        event_id=event.id,
        user_id=telegram_account.user_id,
        chat_id=telegram_account.chat_id,
        text=text,
    )


async def mark_notification_sent(
    db: AsyncSession,
    event_id: int,
) -> bool:
    event = await db.scalar(
        select(NotificationEvent)
        .where(NotificationEvent.id == event_id)
        .with_for_update()
    )

    if event is None or event.delivery_status != DeliveryStatus.PROCESSING:
        await db.rollback()
        return False

    event.delivery_status = DeliveryStatus.SENT
    event.delivered_at = datetime.now(timezone.utc)
    event.last_delivery_error = None

    await db.commit()
    return True


async def mark_notification_failed(
    db: AsyncSession,
    event_id: int,
    error: str,
    retryable: bool,
    telegram_account_user_id: int | None = None,
    failed_chat_id: int | None = None,
) -> bool:
    event = await db.scalar(
        select(NotificationEvent)
        .where(NotificationEvent.id == event_id)
        .with_for_update()
    )

    if event is None or event.delivery_status != DeliveryStatus.PROCESSING:
        await db.rollback()
        return False

    event.delivery_status = (
        DeliveryStatus.PENDING if retryable else DeliveryStatus.FAILED
    )
    event.last_delivery_error = error

    if retryable:
        event.processing_started_at = None

    if (
        not retryable
        and telegram_account_user_id is not None
        and failed_chat_id is not None
    ):
        telegram_account = await db.scalar(
            select(TelegramAccount)
            .where(
                TelegramAccount.user_id == telegram_account_user_id,
                TelegramAccount.chat_id == failed_chat_id,
            )
            .with_for_update()
        )

        if telegram_account is not None:
            telegram_account.is_active = False

    await db.commit()

    return True


async def handle_telegram_delivery_error(
    error: TelegramAPIError | TimeoutError,
    payload: TelegramNotificationPayload,
    session_factory: async_sessionmaker[AsyncSession],
    can_retry: bool,
) -> bool:
    retryable = can_retry and isinstance(
        error,
        (
            TelegramRetryAfter,
            TelegramNetworkError,
            TelegramServerError,
            TimeoutError,
        ),
    )

    forbidden = isinstance(error, TelegramForbiddenError)

    async with session_factory() as db:
        await mark_notification_failed(
            db=db,
            event_id=payload.event_id,
            error=str(error),
            retryable=retryable,
            telegram_account_user_id=(payload.user_id if forbidden else None),
            failed_chat_id=(payload.chat_id if forbidden else None),
        )

    return retryable


async def deliver_telegram_notification(
    event_id: int,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    can_retry: bool = True,
) -> bool:
    async with session_factory() as db:
        payload = await prepare_telegram_notification(
            db=db,
            event_id=event_id,
        )

    if payload is None:
        return False

    try:
        await bot.send_message(
            chat_id=payload.chat_id,
            text=payload.text,
        )

    except (TelegramAPIError, TimeoutError) as error:
        retryable = await handle_telegram_delivery_error(
            error=error,
            payload=payload,
            session_factory=session_factory,
            can_retry=can_retry,
        )

        if retryable:
            raise

        return False

    async with session_factory() as db:
        return await mark_notification_sent(
            db=db,
            event_id=payload.event_id,
        )
