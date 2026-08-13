from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.telegram_account import TelegramAccount
from app.models.telegram_link_token import TelegramLinkToken
from app.services.telegram_link_service import (
    build_telegram_deep_link,
    consume_link_token,
    create_link_token,
    hash_link_token,
)


async def add_link_token(db, user_id: int, raw_token: str, expires_at: datetime):
    token = TelegramLinkToken(
        user_id=user_id,
        token_hash=hash_link_token(raw_token),
        expires_at=expires_at,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token


async def test_link_token_is_consumed_only_once(db_session, create_test_user):
    user = await create_test_user()
    user_id = user.id
    token = await add_link_token(
        db_session,
        user_id,
        "valid-link-token",
        datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    linked = await consume_link_token(
        db=db_session,
        raw_token="valid-link-token",
        telegram_user_id=101_001,
        chat_id=101_001,
        username="price_user",
    )
    reused = await consume_link_token(
        db=db_session,
        raw_token="valid-link-token",
        telegram_user_id=202_002,
        chat_id=202_002,
        username="other_user",
    )

    account = await db_session.scalar(
        select(TelegramAccount).where(TelegramAccount.user_id == user_id)
    )
    await db_session.refresh(token)

    assert linked is True
    assert reused is False
    assert token.used_at is not None
    assert account is not None
    assert account.telegram_user_id == 101_001
    assert account.chat_id == 101_001
    assert account.is_active is True


async def test_expired_link_token_is_rejected(db_session, create_test_user):
    user = await create_test_user()
    user_id = user.id
    token = await add_link_token(
        db_session,
        user_id,
        "expired-link-token",
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    linked = await consume_link_token(
        db=db_session,
        raw_token="expired-link-token",
        telegram_user_id=303_003,
        chat_id=303_003,
        username=None,
    )

    account = await db_session.scalar(
        select(TelegramAccount).where(TelegramAccount.user_id == user_id)
    )
    await db_session.refresh(token)

    assert linked is False
    assert token.used_at is None
    assert account is None


async def test_telegram_identity_cannot_be_linked_to_another_user(
    db_session,
    create_test_user,
):
    token_owner = await create_test_user()
    telegram_owner = await create_test_user()
    telegram_user_id = 404_004

    db_session.add(
        TelegramAccount(
            user_id=telegram_owner.id,
            telegram_user_id=telegram_user_id,
            chat_id=telegram_user_id,
            username="existing_owner",
            is_active=True,
        )
    )
    token = await add_link_token(
        db_session,
        token_owner.id,
        "conflicting-link-token",
        datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    linked = await consume_link_token(
        db=db_session,
        raw_token="conflicting-link-token",
        telegram_user_id=telegram_user_id,
        chat_id=505_005,
        username="conflicting_user",
    )

    await db_session.refresh(token)

    assert linked is False
    assert token.used_at is None


async def test_new_link_token_replaces_previous_unused_token(
    db_session,
    create_test_user,
):
    user = await create_test_user()

    first_raw_token, _ = await create_link_token(db_session, user.id)
    second_raw_token, expires_at = await create_link_token(db_session, user.id)

    tokens = list(
        (
            await db_session.scalars(
                select(TelegramLinkToken).where(TelegramLinkToken.user_id == user.id)
            )
        ).all()
    )

    assert first_raw_token != second_raw_token
    assert len(tokens) == 1
    assert tokens[0].token_hash == hash_link_token(second_raw_token)
    assert tokens[0].expires_at == expires_at
    assert build_telegram_deep_link(
        "price_tracker_bot",
        "token+with/slash",
    ) == ("https://t.me/price_tracker_bot?start=token%2Bwith%2Fslash")
