from fastapi.security import OAuth2PasswordBearer

from typing import Annotated
from fastapi import Depends
from app.backend.db import AsyncSession,get_db

db_dependency = Annotated[AsyncSession,Depends(get_db)]
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")



crypt_context = CryptContext(schemes=["argon2"], deprecated="auto")





async def get_current_user(db:db_dependency,token:Annotated[str,Depends(oauth2_scheme)]):

