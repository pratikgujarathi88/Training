"""ORM model for the expenses table."""

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    """Return the current UTC timestamp, used as the created_at default."""
    return datetime.now(timezone.utc)


class Expense(Base):
    """A submitted expense, its INR conversion, and its approval state."""

    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_expenses_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    submitted_by: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    amount_base_minor: Mapped[int] = mapped_column(nullable=False)
    fx_rate: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_by: Mapped[str | None] = mapped_column(String, default=None)
    comment: Mapped[str | None] = mapped_column(String, default=None)
