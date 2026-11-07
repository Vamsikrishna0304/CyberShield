from dataclasses import dataclass
from math import cos, log1p, pi, sin

import numpy as np
from sklearn.ensemble import IsolationForest

from app.models.event import Event

MODEL_VERSION = "isolation-forest-v2"
MINIMUM_EVENTS = 20
CONTAMINATION = 0.10


@dataclass(frozen=True)
class AnomalyCandidate:
    event: Event
    score: float


@dataclass(frozen=True)
class AnomalyResult:
    status: str
    analyzed_events: int
    anomalies: tuple[AnomalyCandidate, ...] = ()


def _features(events: list[Event]) -> np.ndarray:
    rows = []
    for event in events:
        hour = event.event_time.hour + event.event_time.minute / 60
        outcome = event.outcome.casefold()
        action = (event.action or "").casefold()
        event_type = event.event_type.casefold()
        rows.append(
            [
                log1p(event.bytes_transferred or 0),
                (event.destination_port or 0) / 65535,
                float(event.destination_port is not None),
                float(outcome in {"failure", "failed", "denied"}),
                float("auth" in event_type),
                float(action in {"delete", "disable", "grant_admin", "privilege_escalation"}),
                sin(2 * pi * hour / 24),
                cos(2 * pi * hour / 24),
            ]
        )
    return np.asarray(rows, dtype=np.float64)


def detect_anomalies(events: list[Event]) -> AnomalyResult:
    if len(events) < MINIMUM_EVENTS:
        return AnomalyResult(status="insufficient_data", analyzed_events=len(events))

    model = IsolationForest(
        n_estimators=100,
        contamination=CONTAMINATION,
        random_state=42,
    )
    matrix = _features(events)
    predictions = model.fit_predict(matrix)
    scores = model.decision_function(matrix)
    anomalies = tuple(
        AnomalyCandidate(event=event, score=float(score))
        for event, prediction, score in zip(events, predictions, scores, strict=True)
        if prediction == -1
    )
    return AnomalyResult(status="analyzed", analyzed_events=len(events), anomalies=anomalies)


def train_and_predict(
    training_events: list[Event],
    scoring_events: list[Event],
    *,
    contamination: float = CONTAMINATION,
) -> tuple[np.ndarray, np.ndarray]:
    if len(training_events) < MINIMUM_EVENTS:
        raise ValueError(f"Training requires at least {MINIMUM_EVENTS} events")
    if not scoring_events:
        raise ValueError("At least one scoring event is required")

    model = IsolationForest(
        n_estimators=100,
        contamination=contamination,
        random_state=42,
    )
    model.fit(_features(training_events))
    predictions = model.predict(_features(scoring_events))
    scores = model.decision_function(_features(scoring_events))
    return predictions, scores
