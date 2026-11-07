from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator


class IngestionResult(BaseModel):
    batch_id: int
    filename: str
    received_rows: int
    accepted_rows: int
    duplicate_rows: int
    rejected_rows: int
    errors: list[str]
    anomaly_model_status: str
    anomalies_detected: int


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_time: datetime
    source_ip: str | None
    destination_ip: str | None
    username: str | None
    event_type: str
    action: str | None
    outcome: str
    destination_port: int | None
    bytes_transferred: float | None
    asset: str | None
    risk_score: int
    risk_level: str

    @field_validator("event_time")
    @classmethod
    def mark_sqlite_timestamps_as_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class DetectionRead(BaseModel):
    id: int
    event_id: int
    event_time: datetime
    source_ip: str | None
    username: str | None
    event_type: str
    rule_name: str
    severity: str
    score: int
    evidence: str

    @field_validator("event_time")
    @classmethod
    def mark_sqlite_timestamps_as_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class AnomalyRead(BaseModel):
    id: int
    event_id: int
    event_time: datetime
    source_ip: str | None
    username: str | None
    event_type: str
    severity: str
    risk_score: int
    model_version: str
    anomaly_score: float
    evidence: str

    @field_validator("event_time")
    @classmethod
    def mark_sqlite_timestamps_as_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class DashboardSummary(BaseModel):
    total_events: int
    rule_matches: int
    ml_anomalies: int
    high_risk_events: int
    average_risk: float
    severity_counts: dict[str, int]


class EvaluationMetricsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    predicted_anomalies: int
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: list[list[int]]


class ContaminationExperimentRead(EvaluationMetricsRead):
    contamination: float


class ModelEvaluationRead(BaseModel):
    model_version: str
    evaluation_scope: str
    contamination: float
    training_records: int
    testing_records: int
    actual_normal: int
    actual_anomalies: int
    predicted_anomalies: int
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: list[list[int]]
    class_names: list[str]
    contamination_experiments: list[ContaminationExperimentRead]
    rule_based_baseline: EvaluationMetricsRead
    methodology: str


class TrendPoint(BaseModel):
    date: str
    total: int
    flagged_events: int
