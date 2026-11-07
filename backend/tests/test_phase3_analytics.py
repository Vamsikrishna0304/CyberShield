import asyncio
import csv
import io
from datetime import UTC, datetime

import httpx
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.db.base import Base
from app.main import app
from app.models import AnomalySignal, Detection, Event, IngestionBatch
from app.services import model_evaluation
from app.services.anomaly_detection import CONTAMINATION, MODEL_VERSION
from app.services.model_evaluation import evaluate_synthetic_dataset


@pytest.fixture
def api_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        batch = IngestionBatch(
            filename="phase3-test.csv",
            received_rows=3,
            accepted_rows=3,
        )
        db.add(batch)
        db.flush()
        events = [
            Event(
                batch_id=batch.id,
                fingerprint=f"phase3-{index}",
                event_time=datetime(2026, 1, index, 12, tzinfo=UTC),
                source_ip=f"192.0.2.{index}",
                destination_ip="198.51.100.1",
                username=f"synthetic-{index}",
                event_type="network",
                action=None,
                outcome="allowed",
                destination_port=443,
                bytes_transferred=1000,
                asset="=1+1" if index == 3 else "safe",
                risk_score=score,
                risk_level=severity,
            )
            for index, (score, severity) in enumerate(
                ((75, "high"), (10, "low"), (90, "critical")), start=1
            )
        ]
        db.add_all(events)
        db.flush()
        db.add_all(
            [
                AnomalySignal(
                    event_id=events[0].id,
                    model_version="isolation-forest-v1",
                    anomaly_score=-0.2,
                    evidence="synthetic signal",
                ),
                AnomalySignal(
                    event_id=events[1].id,
                    model_version="isolation-forest-v1",
                    anomaly_score=0.1,
                    evidence="synthetic signal",
                ),
                AnomalySignal(
                    event_id=events[2].id,
                    model_version="isolation-forest-v1",
                    anomaly_score=-0.05,
                    evidence="synthetic signal",
                ),
            ]
        )
        db.add(
            Detection(
                event_id=events[2].id,
                rule_name="high_transfer",
                severity="critical",
                score=90,
                evidence="synthetic test detection",
            )
        )
        db.commit()

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    async def request(method: str, url: str):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, url)

    yield request
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_events_accept_inclusive_date_range(api_client) -> None:
    response = asyncio.run(
        api_client("GET", "/api/v1/events?start_date=2026-01-02&end_date=2026-01-02")
    )

    assert response.status_code == 200
    assert [event["username"] for event in response.json()] == ["synthetic-2"]


def test_event_date_range_rejects_reversed_dates(api_client) -> None:
    response = asyncio.run(
        api_client("GET", "/api/v1/events?start_date=2026-01-03&end_date=2026-01-01")
    )

    assert response.status_code == 422


def test_events_accept_maximum_date_as_end_boundary(api_client) -> None:
    response = asyncio.run(
        api_client("GET", "/api/v1/events?end_date=9999-12-31")
    )

    assert response.status_code == 200
    assert len(response.json()) == 3


def test_anomaly_filtering_combines_severity_and_inclusive_score_bounds(api_client) -> None:
    response = asyncio.run(
        api_client(
            "GET",
            "/api/v1/analytics/anomalies?severity=high&min_anomaly_score=-0.2"
            "&max_anomaly_score=-0.1",
        )
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["username"] == "synthetic-1"
    assert response.json()[0]["severity"] == "high"


def test_anomaly_filter_rejects_reversed_score_bounds(api_client) -> None:
    response = asyncio.run(
        api_client(
            "GET",
            "/api/v1/analytics/anomalies?min_anomaly_score=0.2&max_anomaly_score=-0.2",
        )
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "parameter"),
    [
        ("/api/v1/analytics/anomalies", "min_anomaly_score"),
        ("/api/v1/analytics/anomalies", "max_anomaly_score"),
        ("/api/v1/analytics/export.csv", "min_anomaly_score"),
        ("/api/v1/analytics/export.csv", "max_anomaly_score"),
    ],
)
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_anomaly_score_filters_are_rejected(
    api_client, path: str, parameter: str, value: str
) -> None:
    response = asyncio.run(api_client("GET", f"{path}?{parameter}={value}"))

    assert response.status_code == 422


def test_filtered_csv_export_contains_matching_rows_and_safe_cells(api_client) -> None:
    async def prepare_and_request():
        response = await api_client(
            "GET",
            "/api/v1/analytics/export.csv?start_date=2026-01-03&end_date=2026-01-03"
            "&severity=critical&min_anomaly_score=-0.1&max_anomaly_score=-0.01",
        )
        return response

    response = asyncio.run(prepare_and_request())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1
    assert rows[0]["event_type"] == "network"
    assert rows[0]["asset"] == "'=1+1"
    assert rows[0]["ml_anomaly"] == "yes"
    assert rows[0]["anomaly_score"] == "-0.05"


def test_evaluation_uses_fixed_separate_synthetic_split() -> None:
    evaluate_synthetic_dataset.cache_clear()
    result = evaluate_synthetic_dataset()

    assert result.evaluation_scope == "synthetic"
    assert result.model_version == "isolation-forest-v2"
    assert result.contamination == 0.10
    assert CONTAMINATION == 0.10
    assert result.training_records == 240
    assert result.testing_records == 100
    assert result.actual_normal == 90
    assert result.actual_anomalies == 10
    assert sum(map(sum, result.confusion_matrix)) == result.testing_records
    assert result.confusion_matrix == ((80, 10), (5, 5))
    assert result.precision == pytest.approx(1 / 3)
    assert result.recall == pytest.approx(0.5)
    assert result.f1_score == pytest.approx(0.4)
    assert [
        (
            experiment.contamination,
            experiment.predicted_anomalies,
            experiment.confusion_matrix,
        )
        for experiment in result.contamination_experiments
    ] == [
        (0.05, 5, ((86, 4), (9, 1))),
        (0.10, 15, ((80, 10), (5, 5))),
        (0.15, 24, ((72, 18), (4, 6))),
    ]
    experiment_f1_scores = [
        experiment.f1_score for experiment in result.contamination_experiments
    ]
    assert experiment_f1_scores == pytest.approx([2 / 15, 0.4, 6 / 17])
    assert result.rule_based_baseline.predicted_anomalies == 0
    assert result.rule_based_baseline.confusion_matrix == ((90, 0), (10, 0))
    assert result.rule_based_baseline.precision == 0
    assert result.rule_based_baseline.recall == 0
    assert "labels are removed before feature extraction" in result.methodology
    assert "independent validation" in result.methodology


def test_evaluation_api_returns_measured_metrics(api_client) -> None:
    evaluate_synthetic_dataset.cache_clear()
    response = asyncio.run(api_client("GET", "/api/v1/analytics/evaluation"))

    assert response.status_code == 200
    result = response.json()
    assert result["evaluation_scope"] == "synthetic"
    assert result["model_version"] == MODEL_VERSION
    assert result["contamination"] == 0.10
    assert result["precision"] == pytest.approx(1 / 3)
    assert result["recall"] == pytest.approx(0.5)
    assert result["f1_score"] == pytest.approx(0.4)
    assert result["confusion_matrix"] == [[80, 10], [5, 5]]
    assert len(result["contamination_experiments"]) == 3
    assert result["rule_based_baseline"]["confusion_matrix"] == [[90, 0], [10, 0]]


def test_evaluation_labels_are_not_passed_to_the_model(monkeypatch) -> None:
    observed = {}

    observed_contaminations = []

    def fake_train_and_predict(training_events, scoring_events, *, contamination):
        observed["training"] = training_events
        observed["scoring"] = scoring_events
        observed_contaminations.append(contamination)
        return np.ones(len(scoring_events), dtype=int), np.zeros(len(scoring_events))

    monkeypatch.setattr(model_evaluation, "train_and_predict", fake_train_and_predict)
    evaluate_synthetic_dataset.cache_clear()
    result = evaluate_synthetic_dataset()

    assert result.testing_records == 100
    assert all(not hasattr(event, "is_anomaly") for event in observed["training"])
    assert all(not hasattr(event, "is_anomaly") for event in observed["scoring"])
    assert {event.asset for event in observed["scoring"]} == {"SYNTHETIC_EVALUATION"}
    assert observed_contaminations == [0.05, 0.10, 0.15]
    evaluate_synthetic_dataset.cache_clear()
