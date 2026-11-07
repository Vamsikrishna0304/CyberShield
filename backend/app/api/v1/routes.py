import csv
import io
from datetime import UTC, datetime, timedelta
from datetime import date as Date
from datetime import time as Time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models import AnomalySignal, Detection, Event
from app.schemas import (
    AnomalyRead,
    DashboardSummary,
    DetectionRead,
    EventRead,
    IngestionResult,
    ModelEvaluationRead,
    TrendPoint,
)
from app.services.ingestion import InvalidCSV, ingest_csv
from app.services.model_evaluation import evaluate_synthetic_dataset

router = APIRouter()
SEVERITIES = ("informational", "low", "medium", "high", "critical")


def _validate_date_range(start_date: Date | None, end_date: Date | None) -> None:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")


def _event_date_filters(statement, start_date: Date | None, end_date: Date | None):
    if start_date:
        start = datetime.combine(start_date, Time.min, tzinfo=UTC).replace(tzinfo=None)
        statement = statement.where(Event.event_time >= start)
    if end_date:
        if end_date == Date.max:
            end = datetime.combine(end_date, Time.max, tzinfo=UTC).replace(tzinfo=None)
            statement = statement.where(Event.event_time <= end)
        else:
            end = datetime.combine(end_date + timedelta(days=1), Time.min, tzinfo=UTC).replace(
                tzinfo=None
            )
            statement = statement.where(Event.event_time < end)
    return statement


def _safe_csv_cell(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ingest", response_model=IngestionResult, status_code=201)
async def upload_events(
    file: Annotated[UploadFile, File(...)], db: Annotated[Session, Depends(get_db)]
) -> IngestionResult:
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only CSV uploads are supported")

    content = await file.read(get_settings().max_upload_bytes + 1)
    if len(content) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds the 5 MiB limit")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded CSV is empty")

    try:
        batch, errors, anomaly_model_status, anomalies_detected = ingest_csv(
            db, filename, content
        )
    except InvalidCSV as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return IngestionResult(
        batch_id=batch.id,
        filename=batch.filename,
        received_rows=batch.received_rows,
        accepted_rows=batch.accepted_rows,
        duplicate_rows=batch.duplicate_rows,
        rejected_rows=batch.rejected_rows,
        errors=errors,
        anomaly_model_status=anomaly_model_status,
        anomalies_detected=anomalies_detected,
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(db: Annotated[Session, Depends(get_db)]) -> DashboardSummary:
    total = db.scalar(select(func.count(Event.id))) or 0
    rule_matches = db.scalar(select(func.count(Detection.id))) or 0
    ml_anomalies = db.scalar(select(func.count(AnomalySignal.id))) or 0
    high_risk = db.scalar(
        select(func.count(Event.id)).where(Event.risk_level.in_(("high", "critical")))
    ) or 0
    average = db.scalar(select(func.avg(Event.risk_score))) or 0
    grouped = db.execute(select(Event.risk_level, func.count()).group_by(Event.risk_level))
    counts = dict(grouped.all())
    return DashboardSummary(
        total_events=total,
        rule_matches=rule_matches,
        ml_anomalies=ml_anomalies,
        high_risk_events=high_risk,
        average_risk=round(float(average), 1),
        severity_counts={severity: counts.get(severity, 0) for severity in SEVERITIES},
    )


@router.get("/dashboard/trends", response_model=list[TrendPoint])
def dashboard_trends(
    db: Annotated[Session, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> list[TrendPoint]:
    since = datetime.now(UTC) - timedelta(days=days - 1)
    event_date = func.strftime("%Y-%m-%d", Event.event_time)
    rows = db.execute(
        select(
            event_date.label("date"),
            func.count(Event.id).label("total"),
            func.sum(case((Event.risk_score > 0, 1), else_=0)).label("flagged_events"),
        )
        .where(Event.event_time >= since.replace(tzinfo=None))
        .group_by(event_date)
        .order_by(event_date)
    ).all()
    return [
        TrendPoint(date=date, total=total, flagged_events=flagged_events or 0)
        for date, total, flagged_events in rows
    ]


@router.get("/events", response_model=list[EventRead])
def list_events(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    risk_level: Annotated[
        str | None, Query(pattern="^(informational|low|medium|high|critical)$")
    ] = None,
    start_date: Date | None = None,
    end_date: Date | None = None,
) -> list[Event]:
    _validate_date_range(start_date, end_date)
    statement = _event_date_filters(select(Event), start_date, end_date)
    if risk_level:
        statement = statement.where(Event.risk_level == risk_level)
    statement = statement.order_by(Event.event_time.desc(), Event.id.desc())
    return list(db.scalars(statement.offset(offset).limit(limit)).all())


@router.get("/detections", response_model=list[DetectionRead])
def list_detections(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    rows = db.execute(
        select(Detection, Event)
        .join(Event, Detection.event_id == Event.id)
        .order_by(Detection.created_at.desc(), Detection.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": detection.id,
            "event_id": event.id,
            "event_time": event.event_time,
            "source_ip": event.source_ip,
            "username": event.username,
            "event_type": event.event_type,
            "rule_name": detection.rule_name,
            "severity": detection.severity,
            "score": detection.score,
            "evidence": detection.evidence,
        }
        for detection, event in rows
    ]


@router.get("/analytics/anomalies", response_model=list[AnomalyRead])
def list_anomalies(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    severity: Annotated[
        str | None, Query(pattern="^(informational|low|medium|high|critical)$")
    ] = None,
    min_anomaly_score: Annotated[float | None, Query(allow_inf_nan=False)] = None,
    max_anomaly_score: Annotated[float | None, Query(allow_inf_nan=False)] = None,
) -> list[dict[str, object]]:
    if (
        min_anomaly_score is not None
        and max_anomaly_score is not None
        and min_anomaly_score > max_anomaly_score
    ):
        raise HTTPException(
            status_code=422,
            detail="min_anomaly_score must be less than or equal to max_anomaly_score",
        )
    statement = (
        select(AnomalySignal, Event)
        .join(Event, AnomalySignal.event_id == Event.id)
    )
    if severity:
        statement = statement.where(Event.risk_level == severity)
    if min_anomaly_score is not None:
        statement = statement.where(AnomalySignal.anomaly_score >= min_anomaly_score)
    if max_anomaly_score is not None:
        statement = statement.where(AnomalySignal.anomaly_score <= max_anomaly_score)
    rows = db.execute(
        statement.order_by(AnomalySignal.anomaly_score, AnomalySignal.id).limit(limit)
    )
    return [
        {
            "id": signal.id,
            "event_id": event.id,
            "event_time": event.event_time,
            "source_ip": event.source_ip,
            "username": event.username,
            "event_type": event.event_type,
            "severity": event.risk_level,
            "risk_score": event.risk_score,
            "model_version": signal.model_version,
            "anomaly_score": signal.anomaly_score,
            "evidence": signal.evidence,
        }
        for signal, event in rows
    ]


@router.get("/analytics/evaluation", response_model=ModelEvaluationRead)
def model_evaluation() -> ModelEvaluationRead:
    return ModelEvaluationRead(**evaluate_synthetic_dataset().__dict__)


@router.get("/analytics/export.csv")
def export_filtered_analytics(
    db: Annotated[Session, Depends(get_db)],
    start_date: Date | None = None,
    end_date: Date | None = None,
    severity: Annotated[
        str | None, Query(pattern="^(informational|low|medium|high|critical)$")
    ] = None,
    min_anomaly_score: Annotated[float | None, Query(allow_inf_nan=False)] = None,
    max_anomaly_score: Annotated[float | None, Query(allow_inf_nan=False)] = None,
) -> Response:
    _validate_date_range(start_date, end_date)
    if (
        min_anomaly_score is not None
        and max_anomaly_score is not None
        and min_anomaly_score > max_anomaly_score
    ):
        raise HTTPException(
            status_code=422,
            detail="min_anomaly_score must be less than or equal to max_anomaly_score",
        )

    statement = (
        select(Event, AnomalySignal)
        .outerjoin(AnomalySignal, AnomalySignal.event_id == Event.id)
    )
    statement = _event_date_filters(statement, start_date, end_date)
    if severity:
        statement = statement.where(Event.risk_level == severity)
    if min_anomaly_score is not None:
        statement = statement.where(AnomalySignal.anomaly_score >= min_anomaly_score)
    if max_anomaly_score is not None:
        statement = statement.where(AnomalySignal.anomaly_score <= max_anomaly_score)

    results = db.execute(statement.order_by(Event.event_time, Event.id)).all()
    event_ids = [event.id for event, _ in results]
    detections_by_event: dict[int, list[str]] = {event_id: [] for event_id in event_ids}
    if event_ids:
        detection_rows = db.execute(
            select(Detection.event_id, Detection.rule_name)
            .where(Detection.event_id.in_(event_ids))
            .order_by(Detection.event_id, Detection.id)
        )
        for event_id, rule_name in detection_rows:
            detections_by_event[event_id].append(rule_name)

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "event_id",
            "event_time",
            "event_type",
            "outcome",
            "source_ip",
            "destination_ip",
            "username",
            "asset",
            "risk_score",
            "severity",
            "rule_detections",
            "ml_anomaly",
            "anomaly_score",
            "model_version",
        ]
    )
    for event, signal in results:
        writer.writerow(
            [
                event.id,
                event.event_time,
                _safe_csv_cell(event.event_type),
                _safe_csv_cell(event.outcome),
                _safe_csv_cell(event.source_ip or ""),
                _safe_csv_cell(event.destination_ip or ""),
                _safe_csv_cell(event.username or ""),
                _safe_csv_cell(event.asset or ""),
                event.risk_score,
                event.risk_level,
                _safe_csv_cell(";".join(detections_by_event[event.id])),
                "yes" if signal else "no",
                signal.anomaly_score if signal else "",
                signal.model_version if signal else "",
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cybershield-analytics.csv"'},
    )
