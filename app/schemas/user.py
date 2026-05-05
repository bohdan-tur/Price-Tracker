from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from datetime import datetime



class UserBase(BaseModel):
    email: EmailStr
    is_active: bool = True



class UserCreate(UserBase):
    password: str



class UserUpdate(BaseModel):

    email: Optional[EmailStr] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None



class UserResponse(UserBase):
    id: int
    created_at: datetime


    model_config = ConfigDict(from_attributes=True)