from pydantic import BaseModel, HttpUrl, ConfigDict
from typing import Optional

class ItemBase(BaseModel):
    url: HttpUrl
    target_price: Optional[float] = None
    is_active: bool = True

class ItemCreate(ItemBase):
    pass

class ItemUpdate(BaseModel):
    target_price: Optional[float] = None
    is_active: Optional[bool] = None

class ItemResponse(ItemBase):
    id: int
    user_id: int
    name: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)
