from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base


class ItemStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(index=True)
    url: Mapped[str]
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(
        String(3), default="UAH", server_default="UAH"
    )
    status: Mapped[ItemStatus] = mapped_column(
        Enum(
            ItemStatus,
            name="item_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [status.value for status in enum],
        ),
        default=ItemStatus.PENDING,
        server_default=ItemStatus.PENDING.value,
        index=True,
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    owner = relationship("User", back_populates="items")
    price_histories = relationship(
        "PriceHistory", back_populates="item", cascade="all, delete-orphan"
    )
