import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db.base import Base
from app.main import app
from app.models import AnomalySignal, Event
from app.services.anomaly_detection import MODEL_VERSION, detect_anomalies
from app.services.ingestion import ingest_csv


def make_events(count: int) -> list[Event]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Event(
            event_time=start + timedelta(minutes=index),
            event_type="network",
            outcome="success",
            action=None,
            destination_port=443,
            bytes_transferred=1024,
            source_ip=f"192.0.2.{index + 1}",
        )
        for index in range(count)
    ]


def test_isolation_forest_skips_batches_below_minimum() -> None:
    result = detect_anomalies(make_events(19))

    assert result.status == "insufficient_data"
    assert result.analyzed_events == 19
    assert result.anomalies == ()


def test_isolation_forest_flags_a_multifeature_outlier() -> None:
    events = make_events(39)
    outlier = Event(
        event_time=datetime(2026, 1, 1, 12, tzinfo=UTC),
        event_type="privilege",
        outcome="denied",
        action="delete",
        destination_port=65000,
        bytes_transferred=1e10,
        source_ip="203.0.113.1",
    )
    events.append(outlier)

    result = detect_anomalies(events)

    assert result.status == "analyzed"
    assert result.analyzed_events == 40
    assert any(candidate.event is outlier for candidate in result.anomalies)
    outlier_score = next(
        candidate.score for candidate in result.anomalies if candidate.event is outlier
    )
    assert outlier_score < 0


def test_ingestion_persists_model_signals_without_changing_rule_risk() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        rows = [
            "event_time,event_type,outcome,source_ip,destination_port,bytes_transferred,action"
        ]
        start = datetime(2026, 1, 1, tzinfo=UTC)
        rows.extend(
            f"{(start + timedelta(minutes=index)).isoformat()},network,success,"
            f"192.0.2.{index + 1},443,1024,"
            for index in range(39)
        )
        rows.append(
            "2026-01-01T12:00:00+00:00,privilege,denied,203.0.113.1,"
            "65000,10000000000,delete"
        )
        content = ("\n".join(rows) + "\n").encode()

        batch, errors, status, anomaly_count = ingest_csv(db, "model-test.csv", content)

        assert errors == []
        assert batch.accepted_rows == 40
        assert status == "analyzed"
        assert anomaly_count >= 1
        signals = list(db.scalars(select(AnomalySignal)))
        assert len(signals) == anomaly_count
        assert all(signal.model_version == MODEL_VERSION for signal in signals)
        outlier = db.scalar(select(Event).where(Event.source_ip == "203.0.113.1"))
        assert outlier is not None
        assert outlier.risk_score == 40
        assert outlier.risk_level == "medium"
        assert any(signal.event_id == outlier.id for signal in signals)
    engine.dispose()


def test_anomaly_ingestion_and_read_api() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        rows = [
            "event_time,event_type,outcome,source_ip,destination_port,bytes_transferred,action"
        ]
        start = datetime(2026, 1, 1, tzinfo=UTC)
        rows.extend(
            f"{(start + timedelta(minutes=index)).isoformat()},network,success,"
            f"192.0.2.{index + 1},443,1024,"
            for index in range(39)
        )
        rows.append(
            "2026-01-01T12:00:00+00:00,privilege,denied,203.0.113.1,"
            "65000,10000000000,delete"
        )
        async def exercise_api() -> None:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/ingest",
                    files={
                        "file": (
                            "synthetic-model-test.csv",
                            ("\n".join(rows) + "\n").encode(),
                        )
                    },
                )
                assert response.status_code == 201, response.text
                result = response.json()
                assert result["anomaly_model_status"] == "analyzed"
                assert result["anomalies_detected"] >= 1
                summary_response = await client.get("/api/v1/dashboard/summary")
                assert summary_response.status_code == 200
                assert summary_response.json()["ml_anomalies"] == result["anomalies_detected"]
                anomalies_response = await client.get("/api/v1/analytics/anomalies")
                assert anomalies_response.status_code == 200
                anomalies = anomalies_response.json()
                assert len(anomalies) == result["anomalies_detected"]
                assert any(item["source_ip"] == "203.0.113.1" for item in anomalies)

        asyncio.run(exercise_api())
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
