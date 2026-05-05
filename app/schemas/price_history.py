from pydantic import BaseModel, ConfigDict
from datetime import datetime

class PriceHistoryResponse(BaseModel):
    id: int
    item_id: int
    price: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
