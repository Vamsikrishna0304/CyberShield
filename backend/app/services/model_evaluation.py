from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from app.core.config import PROJECT_ROOT
from app.models.event import Event
from app.services.anomaly_detection import (
    CONTAMINATION,
    MODEL_VERSION,
    train_and_predict,
)
from app.services.ingestion import ALLOWED_COLUMNS, REQUIRED_COLUMNS, _parse_row
from app.services.risk import assess_event

TRAINING_DATASET = PROJECT_ROOT / "data" / "ml_evaluation_train.csv"
TEST_DATASET = PROJECT_ROOT / "data" / "ml_evaluation_test.csv"
LABEL_COLUMN = "is_anomaly"
CLASS_NAMES = ("normal", "anomaly")
CONTAMINATION_EXPERIMENTS = (0.05, 0.10, 0.15)


@dataclass(frozen=True)
class EvaluationMetrics:
    predicted_anomalies: int
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: tuple[tuple[int, int], tuple[int, int]]


@dataclass(frozen=True)
class ContaminationExperiment(EvaluationMetrics):
    contamination: float


@dataclass(frozen=True)
class EvaluationResult:
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
    confusion_matrix: tuple[tuple[int, int], tuple[int, int]]
    class_names: tuple[str, str]
    contamination_experiments: tuple[ContaminationExperiment, ...]
    rule_based_baseline: EvaluationMetrics
    methodology: str


def _read_events(path: Path, *, labels_required: bool) -> tuple[list[Event], list[int] | None]:
    if not path.is_file():
        raise FileNotFoundError(f"Evaluation dataset not found: {path}")
    try:
        frame = pd.read_csv(path, dtype=object, keep_default_na=False)
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Could not parse evaluation dataset {path.name}: {exc}") from exc

    columns = {str(column).strip() for column in frame.columns}
    expected = ALLOWED_COLUMNS | REQUIRED_COLUMNS
    if labels_required:
        if LABEL_COLUMN not in columns:
            raise ValueError(f"Test dataset must include the {LABEL_COLUMN!r} label column")
        feature_columns = columns - {LABEL_COLUMN}
    else:
        if LABEL_COLUMN in columns:
            raise ValueError("Training dataset must not contain test labels")
        feature_columns = columns

    if feature_columns - expected:
        raise ValueError(
            f"Unsupported evaluation columns: {', '.join(sorted(feature_columns - expected))}"
        )
    if missing := REQUIRED_COLUMNS - feature_columns:
        raise ValueError(f"Missing required evaluation columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise ValueError(f"Evaluation dataset is empty: {path.name}")

    frame.columns = [str(column).strip() for column in frame.columns]
    labels = None
    if labels_required:
        label_values = frame.pop(LABEL_COLUMN)
        if not label_values.isin({"0", "1"}).all():
            raise ValueError(f"{LABEL_COLUMN} values must be 0 (normal) or 1 (anomaly)")
        labels = [int(value) for value in label_values]
        if set(labels) != {0, 1}:
            raise ValueError("Test dataset must contain both normal and anomaly labels")

    events: list[Event] = []
    for row_number, row in enumerate(frame.to_dict(orient="records"), start=2):
        try:
            events.append(Event(**_parse_row(row)))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid event at {path.name} row {row_number}: {exc}") from exc
    return events, labels


@lru_cache(maxsize=1)
def evaluate_synthetic_dataset() -> EvaluationResult:
    training_events, training_labels = _read_events(TRAINING_DATASET, labels_required=False)
    test_events, test_labels = _read_events(TEST_DATASET, labels_required=True)
    if training_labels is not None:
        raise ValueError("Test labels must not be used to fit the anomaly model")

    experiments = []
    selected_metrics = None
    for contamination in CONTAMINATION_EXPERIMENTS:
        predictions, _scores = train_and_predict(
            training_events, test_events, contamination=contamination
        )
        metrics = _calculate_metrics(test_labels, (predictions == -1).astype(int))
        experiments.append(
            ContaminationExperiment(contamination=contamination, **metrics.__dict__)
        )
        if contamination == CONTAMINATION:
            selected_metrics = metrics

    if selected_metrics is None:
        raise ValueError("Selected contamination must be included in the evaluation experiments")

    rule_predictions = [int(bool(assess_event(event).rules)) for event in test_events]
    rule_baseline = _calculate_metrics(test_labels, rule_predictions)
    return EvaluationResult(
        model_version=MODEL_VERSION,
        evaluation_scope="synthetic",
        contamination=CONTAMINATION,
        training_records=len(training_events),
        testing_records=len(test_events),
        actual_normal=test_labels.count(0),
        actual_anomalies=test_labels.count(1),
        **selected_metrics.__dict__,
        class_names=CLASS_NAMES,
        contamination_experiments=tuple(experiments),
        rule_based_baseline=rule_baseline,
        methodology=(
            "Trained on a separate unlabeled synthetic normal-pattern dataset; "
            "test labels are removed before feature extraction and used only to "
            "calculate metrics. Contamination settings are reported on the same "
            "fixed test split as exploratory comparisons; the selected setting "
            "requires independent validation. Results describe this synthetic split only."
        ),
    )


def _calculate_metrics(
    labels: list[int], predictions: Iterable[int]
) -> EvaluationMetrics:
    predicted_labels = [int(value) for value in predictions]
    matrix = confusion_matrix(labels, predicted_labels, labels=[0, 1])
    return EvaluationMetrics(
        predicted_anomalies=sum(predicted_labels),
        precision=float(precision_score(labels, predicted_labels, zero_division=0)),
        recall=float(recall_score(labels, predicted_labels, zero_division=0)),
        f1_score=float(f1_score(labels, predicted_labels, zero_division=0)),
        confusion_matrix=(
            (int(matrix[0, 0]), int(matrix[0, 1])),
            (int(matrix[1, 0]), int(matrix[1, 1])),
        ),
    )
