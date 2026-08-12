from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, call, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.item import Item, ItemStatus
from app.models.notification_event import DeliveryStatus, NotificationEvent
from app.models.price_history import PriceHistory
from app.worker.worker import (
    dispatch_pending_telegram_notifications,
    dispatch_price_checks,
    get_pending_notification_event_ids,
    scrape_item_async,
)


def make_session_factory(
    db_session: AsyncSession,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def test_scrape_item_stores_first_price_without_notification(
    create_test_user,
    db_session,
):
    user = await create_test_user()
    item = Item(
        title="First price",
        url="https://rozetka.com.ua/ua/test_item/",
        target_price=Decimal("1000.00"),
        user_id=user.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    with (
        patch(
            "app.worker.worker.get_current_price",
            new=AsyncMock(return_value=Decimal("900.00")),
        ),
        patch(
            "app.worker.worker.deliver_telegram_notification_task.delay"
        ) as enqueue_notification,
    ):
        result = await scrape_item_async(item.id, make_session_factory(db_session))

    await db_session.refresh(item)
    history_count = await db_session.scalar(
        select(func.count())
        .select_from(PriceHistory)
        .where(PriceHistory.item_id == item.id)
    )
    notification_count = await db_session.scalar(
        select(func.count())
        .select_from(NotificationEvent)
        .where(NotificationEvent.item_id == item.id)
    )

    assert result == {
        "status": "success",
        "item_id": item.id,
        "price_changed": True,
        "target_crossed": False,
    }
    assert item.current_price == Decimal("900.00")
    assert item.status is ItemStatus.ACTIVE
    assert item.last_checked_at is not None
    assert item.last_error is None
    assert history_count == 1
    assert notification_count == 0
    enqueue_notification.assert_not_called()


async def test_scrape_item_does_not_duplicate_unchanged_price(
    create_test_user,
    db_session,
):
    user = await create_test_user()
    item = Item(
        title="Unchanged price",
        url="https://rozetka.com.ua/ua/test_item/",
        current_price=Decimal("1200.00"),
        target_price=Decimal("1000.00"),
        status=ItemStatus.ACTIVE,
        user_id=user.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    with patch(
        "app.worker.worker.get_current_price",
        new=AsyncMock(return_value=Decimal("1200.00")),
    ):
        result = await scrape_item_async(item.id, make_session_factory(db_session))

    history_count = await db_session.scalar(
        select(func.count())
        .select_from(PriceHistory)
        .where(PriceHistory.item_id == item.id)
    )

    assert result["price_changed"] is False
    assert result["target_crossed"] is False
    assert history_count == 0


async def test_scrape_item_creates_notification_when_target_is_crossed(
    create_test_user,
    db_session,
):
    user = await create_test_user()
    item = Item(
        title="Target crossing",
        url="https://rozetka.com.ua/ua/test_item/",
        current_price=Decimal("1200.00"),
        target_price=Decimal("1000.00"),
        status=ItemStatus.ACTIVE,
        user_id=user.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    with (
        patch(
            "app.worker.worker.get_current_price",
            new=AsyncMock(return_value=Decimal("900.00")),
        ),
        patch(
            "app.worker.worker.deliver_telegram_notification_task.delay"
        ) as enqueue_notification,
    ):
        result = await scrape_item_async(item.id, make_session_factory(db_session))

    history = await db_session.scalar(
        select(PriceHistory).where(PriceHistory.item_id == item.id)
    )
    notification = await db_session.scalar(
        select(NotificationEvent).where(NotificationEvent.item_id == item.id)
    )

    assert result["target_crossed"] is True
    assert history is not None
    assert history.price == Decimal("900.00")
    assert notification is not None
    assert notification.price_history_id == history.id
    enqueue_notification.assert_called_once_with(notification.id)


async def test_scrape_item_marks_item_as_error_without_leaking_message(
    create_test_user,
    db_session,
):
    user = await create_test_user()
    item = Item(
        title="Failed scrape",
        url="https://rozetka.com.ua/ua/test_item/",
        target_price=Decimal("1000.00"),
        user_id=user.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    with patch(
        "app.worker.worker.get_current_price",
        new=AsyncMock(side_effect=RuntimeError("sensitive upstream response")),
    ):
        result = await scrape_item_async(item.id, make_session_factory(db_session))

    await db_session.refresh(item)

    assert result == {"status": "error", "item_id": item.id}
    assert item.status is ItemStatus.ERROR
    assert item.last_error == "RuntimeError"
    assert item.last_checked_at is not None
    assert item.current_price is None


async def test_scrape_item_returns_not_found_before_network_call(db_session):
    get_price = AsyncMock()

    with patch("app.worker.worker.get_current_price", new=get_price):
        result = await scrape_item_async(999_999, make_session_factory(db_session))

    assert result == {"status": "not_found", "item_id": 999_999}
    get_price.assert_not_awaited()


def test_dispatch_price_checks_enqueues_one_task_per_item():
    with (
        patch(
            "app.worker.worker.get_trackable_item_ids",
            new=AsyncMock(return_value=[10, 20, 30]),
        ),
        patch("app.worker.worker.scrape_item.delay") as enqueue_scrape,
    ):
        result = dispatch_price_checks()

    assert result == {"status": "success", "dispatched_items": 3}
    assert enqueue_scrape.call_args_list == [call(10), call(20), call(30)]


async def test_pending_notification_query_returns_only_pending_events(
    create_test_user,
    db_session,
):
    user = await create_test_user()
    item = Item(
        title="Pending notifications",
        url="https://rozetka.com.ua/ua/pending_notifications/",
        current_price=Decimal("900.00"),
        target_price=Decimal("1000.00"),
        status=ItemStatus.ACTIVE,
        user_id=user.id,
    )
    db_session.add(item)
    await db_session.flush()

    pending_history = PriceHistory(item_id=item.id, price=Decimal("900.00"))
    sent_history = PriceHistory(item_id=item.id, price=Decimal("800.00"))
    db_session.add_all([pending_history, sent_history])
    await db_session.flush()

    pending_event = NotificationEvent(
        item_id=item.id,
        price_history_id=pending_history.id,
    )
    sent_event = NotificationEvent(
        item_id=item.id,
        price_history_id=sent_history.id,
        delivery_status=DeliveryStatus.SENT,
    )
    db_session.add_all([pending_event, sent_event])
    await db_session.commit()

    event_ids = await get_pending_notification_event_ids(
        make_session_factory(db_session)
    )

    assert pending_event.id in event_ids
    assert sent_event.id not in event_ids


async def test_pending_notification_query_recovers_stale_processing_event(
    create_test_user,
    db_session,
):
    user = await create_test_user()
    item = Item(
        title="Stale notification",
        url="https://rozetka.com.ua/ua/stale_notification/",
        current_price=Decimal("900.00"),
        target_price=Decimal("1000.00"),
        status=ItemStatus.ACTIVE,
        user_id=user.id,
    )
    db_session.add(item)
    await db_session.flush()

    history = PriceHistory(item_id=item.id, price=Decimal("900.00"))
    db_session.add(history)
    await db_session.flush()

    event = NotificationEvent(
        item_id=item.id,
        price_history_id=history.id,
        delivery_status=DeliveryStatus.PROCESSING,
        processing_started_at=datetime.now(timezone.utc) - timedelta(minutes=16),
    )
    db_session.add(event)
    await db_session.commit()

    event_ids = await get_pending_notification_event_ids(
        make_session_factory(db_session)
    )
    await db_session.refresh(event)

    assert event.id in event_ids
    assert event.delivery_status is DeliveryStatus.PENDING
    assert event.processing_started_at is None
    assert event.last_delivery_error == (
        "Delivery processing timed out and was queued again"
    )


def test_pending_notification_dispatcher_enqueues_each_event():
    with (
        patch(
            "app.worker.worker.get_pending_notification_event_ids",
            new=AsyncMock(return_value=[11, 22]),
        ),
        patch(
            "app.worker.worker.deliver_telegram_notification_task.delay"
        ) as enqueue_notification,
    ):
        result = dispatch_pending_telegram_notifications()

    assert result == {"status": "success", "dispatched_events": 2}
    assert enqueue_notification.call_args_list == [call(11), call(22)]
