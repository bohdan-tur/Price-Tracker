from logging import DEBUG

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import os
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_async_engine(DATABASE_URL,echo=True)


AsyncSession = async_sessionmaker(bind=engine,autocommit=False,autoflush=False)



async def get_db():
    async with AsyncSession() as session:
        yield session




class Base(DeclarativeBase):
    pass
