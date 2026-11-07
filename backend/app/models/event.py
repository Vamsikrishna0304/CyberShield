from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.anomaly_signal import AnomalySignal
    from app.models.detection import Detection
    from app.models.ingestion_batch import IngestionBatch


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_events_fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("ingestion_batches.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_ip: Mapped[str | None] = mapped_column(String(45), index=True)
    destination_ip: Mapped[str | None] = mapped_column(String(45))
    username: Mapped[str | None] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(50), index=True)
    destination_port: Mapped[int | None] = mapped_column(Integer)
    bytes_transferred: Mapped[float | None] = mapped_column(Float)
    asset: Mapped[str | None] = mapped_column(String(128), index=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="informational", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    batch: Mapped["IngestionBatch"] = relationship(back_populates="events")
    detections: Mapped[list["Detection"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    anomaly_signal: Mapped["AnomalySignal | None"] = relationship(
        back_populates="event", cascade="all, delete-orphan", uselist=False
    )
