from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import HttpUrl

from app.api.dependencies import db_dependency, get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.telegram import TelegramLinkResponse
from app.services.telegram_link_service import (
    build_telegram_deep_link,
    create_link_token,
)

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post(
    "/link",
    response_model=TelegramLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def create_telegram_link(
    request: Request,
    db: db_dependency,
    user: User = Depends(get_current_user),
) -> TelegramLinkResponse:

    bot_username = settings.TELEGRAM_BOT_USERNAME

    if not settings.TELEGRAM_POLLING_ENABLED or not bot_username:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram integration is unavailable",
        )

    raw_token, expires_at = await create_link_token(db, user.id)

    deep_link = build_telegram_deep_link(bot_username=bot_username, raw_token=raw_token)

    return TelegramLinkResponse(
        deep_link=HttpUrl(deep_link),
        expires_at=expires_at,
    )
