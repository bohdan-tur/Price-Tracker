import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Environment, settings
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.database.db import Base, get_session
from app.main import app
from app.models.user import User

if settings.ENVIRONMENT is not Environment.TEST:
    raise RuntimeError("Tests can run only with ENVIRONMENT=test")

if not settings.TEST_DATABASE_URL:
    raise RuntimeError("TEST_DATABASE_URL is required for tests")

if settings.TEST_DATABASE_URL == settings.DATABASE_URL:
    raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL")

DATABASE_URL = settings.TEST_DATABASE_URL

test_engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)

test_session = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(autouse=True, scope="session")
async def prepare_db():
    limiter.reset()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()
    limiter.reset()


@pytest_asyncio.fixture
async def db_session():
    async with test_session() as session:
        yield session


@pytest_asyncio.fixture
async def async_client(db_session):

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def create_test_user(db_session):
    async def _create_test_user(email: str = None, is_superuser: bool = False):
        if email is None:
            email = f"user_{uuid.uuid4().hex[:8]}@test.com"

        result = await db_session.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            return existing_user

        user = User(
            email=email,
            hashed_password=get_password_hash("secret123"),
            is_active=True,
            is_superuser=is_superuser,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _create_test_user
