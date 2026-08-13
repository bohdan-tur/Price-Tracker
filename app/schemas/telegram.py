from datetime import datetime

from pydantic import BaseModel, HttpUrl


class TelegramLinkResponse(BaseModel):
    deep_link: HttpUrl
    expires_at: datetime
