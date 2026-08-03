import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Environment, settings
from app.core.security import get_password_hash
from app.models.user import User

logger = logging.getLogger("root")

USERS_TO_SEED = [
    {
        "email": "admin@price-tracker.com",
        "password": settings.SEED_ADMIN_PASSWORD,
        "is_superuser": True,
        "is_active": True,
    },
    {
        "email": "user4@example.com",
        "password": settings.SEED_USER_PASSWORD,
        "is_superuser": False,
        "is_active": True,
    },
    {
        "email": "user5@example.com",
        "password": settings.SEED_USER_PASSWORD,
        "is_superuser": False,
        "is_active": True,
    },
]


async def seed_database() -> None:
    if not settings.SEED_DEFAULT_USERS:
        logger.info("Default user seeding is disabled")
        return

    if settings.ENVIRONMENT is Environment.PRODUCTION:
        raise RuntimeError("Default users cannot be seeded in production")

    engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        async with async_session() as session:
            for user_data in USERS_TO_SEED:
                result = await session.execute(
                    select(User).where(User.email == user_data["email"])
                )
                existing_user = result.scalar_one_or_none()

                if existing_user:
                    logger.info("User %s already exists; skipping", user_data["email"])
                    continue

                password = user_data["password"]
                if not isinstance(password, str) or not password:
                    raise RuntimeError("Seed password is not configured")

                new_user = User(
                    email=user_data["email"],
                    hashed_password=get_password_hash(password),
                    is_superuser=user_data["is_superuser"],
                    is_active=user_data["is_active"],
                )
                session.add(new_user)
                logger.info("Seeding user: %s", user_data["email"])

            await session.commit()
            logger.info("Database seeding completed successfully")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_database())
