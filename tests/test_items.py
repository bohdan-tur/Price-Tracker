from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select

from app.api.dependencies import get_current_user
from app.main import app
from app.models.item import Item
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
    }

    with patch("app.api.routers.item.get_current_price", return_value=1500.0):
        response = await async_client.post("/items/", json=payload)

    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Iphone 17"
    assert "id" in data

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
    }

    with patch(
        "app.api.routers.item.get_current_price",
        side_effect=UnsafeScraperURLError("Scraper hostname is not allowed"),
    ):
        response = await async_client.post("/items/", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "Scraper hostname is not allowed"

    query = await db_session.execute(select(Item).where(Item.user_id == user.id))
    assert query.scalar_one_or_none() is None

    app.dependency_overrides.pop(get_current_user, None)
