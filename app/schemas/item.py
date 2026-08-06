from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models.item import ItemStatus


class ItemBase(BaseModel):
    title: str
    url: HttpUrl


class ItemCreate(ItemBase):
    target_price: Decimal = Field(
        gt=Decimal("0"),
        max_digits=12,
        decimal_places=2,
    )


class ItemResponse(ItemBase):
    id: int
    current_price: Decimal | None
    target_price: Decimal | None
    currency: str
    status: ItemStatus
    last_checked_at: datetime | None
    last_error: str | None
    user_id: int

    model_config = ConfigDict(from_attributes=True)
