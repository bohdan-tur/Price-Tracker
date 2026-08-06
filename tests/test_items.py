from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select

from app.api.dependencies import get_current_user
from app.main import app
from app.models.item import Item, ItemStatus
from app.models.price_history import PriceHistory
from app.services.scraper import UnsafeScraperURLError


async def test_get_items(async_client: AsyncClient, create_test_user):
    user = await create_test_user()

    app.dependency_overrides[get_current_user] = lambda: user

    response = await async_client.get("/items/")

    assert response.status_code == 200
    assert len(response.json()) == 0

    app.dependency_overrides.pop(get_current_user)


async def test_delete_item(async_client: AsyncClient, create_test_user, db_session):

    user = await create_test_user()

    app.dependency_overrides[get_current_user] = lambda: user

    item = Item(
        title="Test title",
        url="https://fake-site-example.com/product/123",
        current_price=None,
        user_id=user.id,
        owner=user,
        price_histories=[],
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    response = await async_client.delete(f"/items/{item.id}")

    assert response.status_code == 204

    query = await db_session.execute(select(Item).where(Item.id == item.id))
    deleted_item = query.scalar_one_or_none()
    assert deleted_item is None

    app.dependency_overrides.pop(get_current_user)


async def test_create_item_success(async_client, create_test_user):

    user = await create_test_user()
    app.dependency_overrides[get_current_user] = lambda: user

    payload = {
        "title": "Iphone 17",
        "url": "https://rozetka.com.ua/ua/monitor_123/p12345/",
        "target_price": "1400.00",
    }

    with (
        patch("app.api.routers.item.validate_scraper_url") as validate_url,
        patch("app.api.routers.item.scrape_item.delay") as enqueue_scrape,
    ):
        response = await async_client.post("/items/", json=payload)

    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Iphone 17"
    assert data["current_price"] is None
    assert data["target_price"] == "1400.00"
    assert data["currency"] == "UAH"
    assert data["status"] == ItemStatus.PENDING.value
    assert "id" in data
    validate_url.assert_awaited_once_with(payload["url"])
    enqueue_scrape.assert_called_once_with(data["id"])

    app.dependency_overrides.clear()


async def test_create_item_rejects_unsafe_url(
    async_client,
    create_test_user,
    db_session,
):
    user = await create_test_user()
    app.dependency_overrides[get_current_user] = lambda: user

    payload = {
        "title": "Unsafe item",
        "url": "https://rozetka.com.ua/product",
        "target_price": "1000.00",
    }

    with (
        patch(
            "app.api.routers.item.validate_scraper_url",
            side_effect=UnsafeScraperURLError("Scraper hostname is not allowed"),
        ),
        patch("app.api.routers.item.scrape_item.delay") as enqueue_scrape,
    ):
        response = await async_client.post("/items/", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "Scraper hostname is not allowed"

    query = await db_session.execute(select(Item).where(Item.user_id == user.id))
    assert query.scalar_one_or_none() is None
    enqueue_scrape.assert_not_called()

    app.dependency_overrides.pop(get_current_user, None)


async def test_get_item_history_is_paginated_newest_first(
    async_client,
    create_test_user,
    db_session,
):
    user = await create_test_user()
    app.dependency_overrides[get_current_user] = lambda: user

    item = Item(
        title="Test item",
        url="https://rozetka.com.ua/ua/product/p12345/",
        target_price=Decimal("1000.00"),
        user_id=user.id,
    )
    db_session.add(item)
    await db_session.flush()

    older_time = datetime.now(timezone.utc) - timedelta(hours=1)
    newer_time = datetime.now(timezone.utc)
    db_session.add_all(
        [
            PriceHistory(
                item_id=item.id,
                price=Decimal("1200.00"),
                currency="UAH",
                recorded_at=older_time,
            ),
            PriceHistory(
                item_id=item.id,
                price=Decimal("1100.00"),
                currency="UAH",
                recorded_at=newer_time,
            ),
        ]
    )
    await db_session.commit()

    response = await async_client.get(
        f"/items/{item.id}/history",
        params={"limit": 1, "offset": 0},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["price"] == "1100.00"

    app.dependency_overrides.pop(get_current_user, None)


async def test_get_item_history_hides_another_users_item(
    async_client,
    create_test_user,
    db_session,
):
    owner = await create_test_user()
    another_user = await create_test_user()
    item = Item(
        title="Private item",
        url="https://rozetka.com.ua/ua/product/p67890/",
        target_price=Decimal("1000.00"),
        user_id=owner.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    app.dependency_overrides[get_current_user] = lambda: another_user

    response = await async_client.get(f"/items/{item.id}/history")

    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"

    app.dependency_overrides.pop(get_current_user, None)
