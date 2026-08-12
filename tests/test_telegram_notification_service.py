from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.item import Item, ItemStatus
from app.models.notification_event import DeliveryStatus, NotificationEvent
from app.models.price_history import PriceHistory
from app.models.telegram_account import TelegramAccount
from app.services.telegram_notification_service import (
    deliver_telegram_notification,
    handle_telegram_delivery_error,
    prepare_telegram_notification,
)


def make_session_factory(
    db_session: AsyncSession,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def create_notification(
    db_session: AsyncSession,
    create_test_user,
    *,
    with_account: bool = True,
):
    user = await create_test_user()
    item = Item(
        title="Tracked phone",
        url="https://rozetka.com.ua/ua/tracked_phone/",
        current_price=Decimal("900.00"),
        target_price=Decimal("1000.00"),
        currency="UAH",
        status=ItemStatus.ACTIVE,
        user_id=user.id,
    )
    db_session.add(item)
    await db_session.flush()

    history = PriceHistory(
        item_id=item.id,
        price=Decimal("900.00"),
        currency="UAH",
    )
    db_session.add(history)
    await db_session.flush()

    event = NotificationEvent(
        item_id=item.id,
        price_history_id=history.id,
    )
    db_session.add(event)

    account = None
    if with_account:
        telegram_id = 1_000_000 + user.id
        account = TelegramAccount(
            user_id=user.id,
            telegram_user_id=telegram_id,
            chat_id=telegram_id,
            username="notification_user",
            is_active=True,
        )
        db_session.add(account)

    await db_session.commit()
    await db_session.refresh(event)
    return event, account


async def test_delivery_sends_message_and_marks_event_sent(
    db_session,
    create_test_user,
):
    event, account = await create_notification(db_session, create_test_user)
    bot = SimpleNamespace(send_message=AsyncMock())

    delivered = await deliver_telegram_notification(
        event_id=event.id,
        bot=bot,
        session_factory=make_session_factory(db_session),
    )

    await db_session.refresh(event)

    assert delivered is True
    assert event.delivery_status is DeliveryStatus.SENT
    assert event.delivery_attempts == 1
    assert event.processing_started_at is not None
    assert event.delivered_at is not None
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == account.chat_id
    assert "Current price: 900.00 UAH" in bot.send_message.await_args.kwargs["text"]


async def test_prepare_skips_event_without_active_telegram_account(
    db_session,
    create_test_user,
):
    event, _ = await create_notification(
        db_session,
        create_test_user,
        with_account=False,
    )

    payload = await prepare_telegram_notification(db_session, event.id)
    await db_session.refresh(event)

    assert payload is None
    assert event.delivery_status is DeliveryStatus.SKIPPED
    assert event.last_delivery_error is not None


@pytest.mark.parametrize(
    ("can_retry", "expected_retryable", "expected_status"),
    [
        (True, True, DeliveryStatus.PENDING),
        (False, False, DeliveryStatus.FAILED),
    ],
)
async def test_timeout_respects_remaining_retry_budget(
    db_session,
    create_test_user,
    can_retry,
    expected_retryable,
    expected_status,
):
    event, _ = await create_notification(db_session, create_test_user)
    session_factory = make_session_factory(db_session)

    async with session_factory() as db:
        payload = await prepare_telegram_notification(db, event.id)

    retryable = await handle_telegram_delivery_error(
        error=TimeoutError("Telegram timed out"),
        payload=payload,
        session_factory=session_factory,
        can_retry=can_retry,
    )

    await db_session.refresh(event)

    assert retryable is expected_retryable
    assert event.delivery_status is expected_status


async def test_forbidden_error_fails_event_and_deactivates_exact_account(
    db_session,
    create_test_user,
):
    event, account = await create_notification(db_session, create_test_user)
    session_factory = make_session_factory(db_session)

    async with session_factory() as db:
        payload = await prepare_telegram_notification(db, event.id)

    error = TelegramForbiddenError(
        method=SendMessage(chat_id=payload.chat_id, text=payload.text),
        message="Forbidden: bot was blocked by the user",
    )
    retryable = await handle_telegram_delivery_error(
        error=error,
        payload=payload,
        session_factory=session_factory,
        can_retry=True,
    )

    await db_session.refresh(event)
    await db_session.refresh(account)

    assert retryable is False
    assert event.delivery_status is DeliveryStatus.FAILED
    assert account.is_active is False
