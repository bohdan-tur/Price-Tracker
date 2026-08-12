from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    is_superuser: Mapped[bool] = mapped_column(default=False)

    items = relationship("Item", back_populates="owner", cascade="all, delete-orphan")
    telegram_account = relationship(
        "TelegramAccount",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    telegram_link_tokens = relationship(
        "TelegramLinkToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
