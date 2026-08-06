from decimal import Decimal
from unittest.mock import AsyncMock, call, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.item import Item, ItemStatus
from app.models.notification_event import NotificationEvent
from app.models.price_history import PriceHistory
from app.worker.worker import dispatch_price_checks, scrape_item_async


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

    with patch(
        "app.worker.worker.get_current_price",
        new=AsyncMock(return_value=Decimal("900.00")),
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

    with patch(
        "app.worker.worker.get_current_price",
        new=AsyncMock(return_value=Decimal("900.00")),
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
