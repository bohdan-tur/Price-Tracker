from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


class PriceHistoryResponse(BaseModel):
    id: int
    price: Decimal
    currency: str
    recorded_at: datetime

    @field_serializer("recorded_at")
    def format_date(self, dt: datetime, _info):

        return dt.strftime("%d.%m.%Y %H:%M:%S")

    model_config = ConfigDict(from_attributes=True)
