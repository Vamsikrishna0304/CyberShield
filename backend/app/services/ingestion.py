import hashlib
import io
import json
import math
from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Detection, Event, IngestionBatch
from app.models.anomaly_signal import AnomalySignal
from app.services.anomaly_detection import MODEL_VERSION, detect_anomalies
from app.services.risk import assess_event

REQUIRED_COLUMNS = {"event_time", "event_type", "outcome"}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | {
    "source_ip",
    "destination_ip",
    "username",
    "action",
    "destination_port",
    "bytes_transferred",
    "asset",
}
MAX_ROWS = 50_000
MAX_CELL_LENGTH = 2_000


class InvalidCSV(ValueError):
    pass


def _optional_text(value: object, field: str) -> str | None:
    if pd.isna(value) or str(value).strip() == "":
        return None
    text = str(value).strip()
    if len(text) > MAX_CELL_LENGTH:
        raise ValueError(f"{field} exceeds the {MAX_CELL_LENGTH}-character limit")
    return text


def _parse_row(row: dict[str, object]) -> dict[str, object]:
    timestamp = pd.to_datetime(row["event_time"], utc=True, errors="raise").to_pydatetime()
    event_type = _optional_text(row["event_type"], "event_type")
    outcome = _optional_text(row["outcome"], "outcome")
    if not event_type or not outcome:
        raise ValueError("event_type and outcome must not be empty")

    port_value = row.get("destination_port")
    port = None if pd.isna(port_value) or str(port_value).strip() == "" else int(port_value)
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("destination_port must be between 1 and 65535")

    bytes_value = row.get("bytes_transferred")
    byte_count = (
        None
        if pd.isna(bytes_value) or str(bytes_value).strip() == ""
        else float(bytes_value)
    )
    if byte_count is not None and (
        not math.isfinite(byte_count) or byte_count < 0 or byte_count > 1e15
    ):
        raise ValueError("bytes_transferred must be between 0 and 1e15")

    return {
        "event_time": timestamp,
        "source_ip": _optional_text(row.get("source_ip"), "source_ip"),
        "destination_ip": _optional_text(row.get("destination_ip"), "destination_ip"),
        "username": _optional_text(row.get("username"), "username"),
        "event_type": event_type,
        "action": _optional_text(row.get("action"), "action"),
        "outcome": outcome,
        "destination_port": port,
        "bytes_transferred": byte_count,
        "asset": _optional_text(row.get("asset"), "asset"),
    }


def _fingerprint(values: dict[str, object]) -> str:
    canonical = {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in values.items()
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def ingest_csv(
    db: Session, filename: str, content: bytes
) -> tuple[IngestionBatch, list[str], str, int]:
    try:
        frame = pd.read_csv(io.BytesIO(content), dtype=object, keep_default_na=False)
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCSV(f"Could not parse CSV: {exc}") from exc

    columns = {str(column).strip() for column in frame.columns}
    if len(columns) != len(frame.columns):
        raise InvalidCSV("CSV contains duplicate or whitespace-ambiguous column names")
    missing = REQUIRED_COLUMNS - columns
    unknown = columns - ALLOWED_COLUMNS
    if missing:
        raise InvalidCSV(f"Missing required columns: {', '.join(sorted(missing))}")
    if unknown:
        raise InvalidCSV(f"Unsupported columns: {', '.join(sorted(unknown))}")
    if len(frame) > MAX_ROWS:
        raise InvalidCSV(f"CSV exceeds the maximum of {MAX_ROWS} rows")
    if frame.empty:
        raise InvalidCSV("CSV contains no event rows")

    frame.columns = [str(column).strip() for column in frame.columns]
    batch = IngestionBatch(filename=filename[:255], status="completed", received_rows=len(frame))
    errors: list[str] = []
    accepted = duplicate = 0
    accepted_events: list[Event] = []

    try:
        db.add(batch)
        db.flush()
        for index, row in frame.iterrows():
            try:
                values = _parse_row(row.to_dict())
            except (TypeError, ValueError, OverflowError) as exc:
                if len(errors) < 100:
                    errors.append(f"Row {index + 2}: {exc}")
                continue

            fingerprint = _fingerprint(values)
            if db.scalar(select(Event.id).where(Event.fingerprint == fingerprint)) is not None:
                duplicate += 1
                continue

            event = Event(batch_id=batch.id, fingerprint=fingerprint, **values)
            assessment = assess_event(event)
            event.risk_score = assessment.score
            event.risk_level = assessment.level
            db.add(event)
            db.flush()
            accepted_events.append(event)
            for rule_name, evidence in zip(assessment.rules, assessment.evidence, strict=True):
                db.add(
                    Detection(
                        event_id=event.id,
                        rule_name=rule_name,
                        severity=assessment.level,
                        score=assessment.score,
                        evidence=evidence,
                    )
                )
            accepted += 1

        anomaly_result = detect_anomalies(accepted_events)
        for candidate in anomaly_result.anomalies:
            db.add(
                AnomalySignal(
                    event_id=candidate.event.id,
                    model_version=MODEL_VERSION,
                    anomaly_score=candidate.score,
                    evidence=(
                        "Isolation Forest identified an unusual combination of event "
                        "features; review this signal in context."
                    ),
                )
            )

        batch.accepted_rows = accepted
        batch.duplicate_rows = duplicate
        batch.rejected_rows = len(frame) - accepted - duplicate
        batch.error_summary = "\n".join(errors) or None
        db.commit()
        db.refresh(batch)
    except Exception:
        db.rollback()
        raise

    return batch, errors, anomaly_result.status, len(anomaly_result.anomalies)
