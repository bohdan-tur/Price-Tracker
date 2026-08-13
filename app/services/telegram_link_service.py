import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram_account import TelegramAccount
from app.models.telegram_link_token import TelegramLinkToken
from app.models.user import User

TELEGRAM_LINK_TOKEN_TTL = timedelta(minutes=10)


def hash_link_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_link_token() -> tuple[str, str]:

    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_link_token(raw_token)

    return raw_token, token_hash


async def create_link_token(db: AsyncSession, user_id: int) -> tuple[str, datetime]:

    now = datetime.now(timezone.utc)
    expires_at = now + TELEGRAM_LINK_TOKEN_TTL
    raw_token, token_hash = generate_link_token()

    try:
        await db.execute(select(User.id).where(User.id == user_id).with_for_update())

        await db.execute(
            delete(TelegramLinkToken).where(
                TelegramLinkToken.user_id == user_id,
                TelegramLinkToken.used_at.is_(None),
            )
        )

        db.add(
            TelegramLinkToken(
                user_id=user_id, token_hash=token_hash, expires_at=expires_at
            )
        )

        await db.commit()

    except Exception:
        await db.rollback()
        raise

    return raw_token, expires_at


def build_telegram_deep_link(bot_username: str, raw_token: str) -> str:

    query = urlencode({"start": raw_token})

    return f"https://t.me/{bot_username}?{query}"


async def consume_link_token(
    db: AsyncSession,
    raw_token: str,
    telegram_user_id: int,
    chat_id: int,
    username: str | None,
) -> bool:
    now = datetime.now(timezone.utc)
    token_hash = hash_link_token(raw_token)

    try:
        token_user_id = await db.scalar(
            select(TelegramLinkToken.user_id).where(
                TelegramLinkToken.token_hash == token_hash
            )
        )

        if token_user_id is None:
            await db.rollback()
            return False

        locked_user_id = await db.scalar(
            select(User.id).where(User.id == token_user_id).with_for_update()
        )
        if locked_user_id is None:
            await db.rollback()
            return False

        token = await db.scalar(
            select(TelegramLinkToken)
            .where(TelegramLinkToken.token_hash == token_hash)
            .with_for_update()
        )
        if token is None or token.used_at is not None or token.expires_at <= now:
            await db.rollback()
            return False

        conflicting_account = await db.scalar(
            select(TelegramAccount)
            .where(
                TelegramAccount.user_id != token.user_id,
                TelegramAccount.telegram_user_id == telegram_user_id,
            )
            .with_for_update()
        )
        if conflicting_account is not None:
            await db.rollback()
            return False

        account = await db.scalar(
            select(TelegramAccount)
            .where(TelegramAccount.user_id == token.user_id)
            .with_for_update()
        )
        if account is None:
            db.add(
                TelegramAccount(
                    user_id=token.user_id,
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    username=username,
                    is_active=True,
                    linked_at=now,
                )
            )
        else:
            account.telegram_user_id = telegram_user_id
            account.chat_id = chat_id
            account.username = username
            account.is_active = True
            account.linked_at = now

        token.used_at = now
        await db.commit()
        return True

    except IntegrityError:
        await db.rollback()
        return False
    except Exception:
        await db.rollback()
        raise
