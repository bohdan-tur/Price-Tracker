from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.enums import ChatType
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import get_current_user
from app.bot.application import (
    create_bot,
    create_dispatcher,
    run_telegram_polling,
)
from app.bot.handlers import (
    build_list_messages,
    handle_help,
    handle_list,
    handle_start,
    handle_status,
    handle_unlink,
    router,
)
from app.core.config import settings
from app.main import app
from app.models.item import Item, ItemStatus
from app.models.telegram_account import TelegramAccount


def make_message(
    *,
    telegram_user_id: int = 700_001,
    username: str | None = "telegram_user",
):
    return SimpleNamespace(
        chat=SimpleNamespace(type=ChatType.PRIVATE, id=telegram_user_id),
        from_user=SimpleNamespace(
            id=telegram_user_id,
            username=username,
        ),
        answer=AsyncMock(),
    )


def make_session_factory(
    db_session: AsyncSession,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def test_telegram_link_endpoint_returns_deep_link(
    async_client,
    create_test_user,
    monkeypatch,
):
    user = await create_test_user()
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(settings, "TELEGRAM_POLLING_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "price_tracker_bot")

    response = await async_client.post("/telegram/link")

    assert response.status_code == 201
    assert response.json()["deep_link"].startswith(
        "https://t.me/price_tracker_bot?start="
    )
    assert response.json()["expires_at"] is not None


async def test_telegram_link_endpoint_is_unavailable_when_polling_is_disabled(
    async_client,
    create_test_user,
    monkeypatch,
):
    user = await create_test_user()
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(settings, "TELEGRAM_POLLING_ENABLED", False)

    response = await async_client.post("/telegram/link")

    assert response.status_code == 503
    assert response.json()["detail"] == "Telegram integration is unavailable"


async def test_start_handler_consumes_token_and_answers_successfully():
    message = make_message()
    command = SimpleNamespace(args="one-time-token")
    db = object()

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    with (
        patch(
            "app.bot.handlers.AsyncSessionLocal",
            new=fake_session_factory,
        ),
        patch(
            "app.bot.handlers.consume_link_token",
            new=AsyncMock(return_value=True),
        ) as consume_token,
    ):
        await handle_start(message, command)

    consume_token.assert_awaited_once_with(
        db=db,
        raw_token="one-time-token",
        telegram_user_id=message.from_user.id,
        chat_id=message.chat.id,
        username=message.from_user.username,
    )
    message.answer.assert_awaited_once_with(
        "Your Telegram account has been linked successfully."
    )


async def test_list_handler_returns_only_linked_users_items(
    db_session,
    create_test_user,
):
    owner = await create_test_user()
    other_user = await create_test_user()
    telegram_id = 700_002
    db_session.add_all(
        [
            TelegramAccount(
                user_id=owner.id,
                telegram_user_id=telegram_id,
                chat_id=telegram_id,
                is_active=True,
            ),
            Item(
                title="Owned item",
                url="https://rozetka.com.ua/ua/owned_item/",
                current_price=Decimal("900.00"),
                target_price=Decimal("1000.00"),
                currency="UAH",
                status=ItemStatus.ACTIVE,
                user_id=owner.id,
            ),
            Item(
                title="Another user's item",
                url="https://rozetka.com.ua/ua/other_item/",
                current_price=Decimal("800.00"),
                target_price=Decimal("850.00"),
                currency="UAH",
                status=ItemStatus.ACTIVE,
                user_id=other_user.id,
            ),
        ]
    )
    await db_session.commit()
    message = make_message(telegram_user_id=telegram_id)

    with patch(
        "app.bot.handlers.AsyncSessionLocal",
        new=make_session_factory(db_session),
    ):
        await handle_list(message)

    response_text = message.answer.await_args.args[0]
    assert "Owned item" in response_text
    assert "Another user's item" not in response_text


async def test_status_help_and_unlink_handlers(
    db_session,
    create_test_user,
):
    user = await create_test_user()
    telegram_id = 700_003
    account = TelegramAccount(
        user_id=user.id,
        telegram_user_id=telegram_id,
        chat_id=telegram_id,
        is_active=True,
    )
    db_session.add(account)
    await db_session.commit()
    message = make_message(telegram_user_id=telegram_id)

    with patch(
        "app.bot.handlers.AsyncSessionLocal",
        new=make_session_factory(db_session),
    ):
        await handle_help(message)
        await handle_status(message)
        await handle_unlink(message)

    await db_session.refresh(account)

    assert message.answer.await_count == 3
    assert "Available commands:" in message.answer.await_args_list[0].args[0]
    assert "notifications are active" in message.answer.await_args_list[1].args[0]
    assert "unlinked successfully" in message.answer.await_args_list[2].args[0]
    assert account.is_active is False


def test_list_messages_respect_telegram_limit():
    messages = build_list_messages(["x" * 5000])

    assert len(messages) == 2
    assert all(len(message) <= 4000 for message in messages)


def test_application_factories_require_token_and_include_router(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        create_bot()

    dispatcher = create_dispatcher()

    assert router in dispatcher.sub_routers


async def test_run_polling_uses_registered_update_types():
    bot = object()
    dispatcher = SimpleNamespace(
        resolve_used_update_types=MagicMock(return_value=["message"]),
        start_polling=AsyncMock(),
    )

    with (
        patch("app.bot.application.create_bot", return_value=bot),
        patch(
            "app.bot.application.create_dispatcher",
            return_value=dispatcher,
        ),
    ):
        await run_telegram_polling()

    dispatcher.start_polling.assert_awaited_once_with(
        bot,
        handle_signals=False,
        allowed_updates=["message"],
    )
