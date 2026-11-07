from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.event import Event


class AnomalySignal(Base):
    __tablename__ = "anomaly_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True, unique=True)
    model_version: Mapped[str] = mapped_column(String(50))
    anomaly_score: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    event: Mapped["Event"] = relationship(back_populates="anomaly_signal")
