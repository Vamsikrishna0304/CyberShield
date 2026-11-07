import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Detection, Event
from app.services.ingestion import InvalidCSV, ingest_csv


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_ingestion_normalizes_scores_and_skips_duplicate(db: Session) -> None:
    content = (
        b"event_time,event_type,outcome,source_ip,action,destination_port\n"
        b"2026-01-01T00:00:00Z,authentication,failure,192.0.2.1,,22\n"
        b"2026-01-01T00:00:00Z,authentication,failure,192.0.2.1,,22\n"
    )
    batch, errors, model_status, anomalies_detected = ingest_csv(db, "events.csv", content)

    assert errors == []
    assert batch.accepted_rows == 1
    assert batch.duplicate_rows == 1
    assert model_status == "insufficient_data"
    assert anomalies_detected == 0
    event = db.scalar(select(Event))
    assert event is not None
    assert event.risk_score == 45
    assert len(list(db.scalars(select(Detection)))) == 2


def test_ingestion_rejects_unknown_columns(db: Session) -> None:
    with pytest.raises(InvalidCSV, match="Unsupported columns"):
        ingest_csv(
            db,
            "events.csv",
            b"event_time,event_type,outcome,unexpected\n2026-01-01,network,ok,x\n",
        )


def test_ingestion_rejects_non_finite_byte_counts(db: Session) -> None:
    batch, errors, model_status, anomalies_detected = ingest_csv(
        db,
        "events.csv",
        b"event_time,event_type,outcome,bytes_transferred\n"
        b"2026-01-01T00:00:00Z,network,success,NaN\n",
    )

    assert batch.accepted_rows == 0
    assert batch.rejected_rows == 1
    assert "must be between 0 and 1e15" in errors[0]
    assert model_status == "insufficient_data"
    assert anomalies_detected == 0
