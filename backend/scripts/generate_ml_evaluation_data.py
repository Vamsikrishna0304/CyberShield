import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FEATURE_COLUMNS = [
    "event_time",
    "event_type",
    "outcome",
    "source_ip",
    "destination_ip",
    "username",
    "action",
    "destination_port",
    "bytes_transferred",
    "asset",
]


def build_row(index: int, start: datetime, *, unusual: bool) -> dict[str, object]:
    if unusual:
        return {
            "event_time": (start + timedelta(minutes=index * 7)).isoformat(),
            "event_type": "network",
            "outcome": "allowed",
            "source_ip": f"203.0.113.{index + 1}",
            "destination_ip": "198.51.100.250",
            "username": f"synthetic-outlier-{index + 1:02d}",
            "action": "",
            "destination_port": 62000 + index,
            "bytes_transferred": 250_000_000 + index * 25_000_000,
            "asset": "SYNTHETIC_EVALUATION",
        }

    ports = (443, 443, 443, 443, 80, 443, 443, 53)
    return {
        "event_time": (start + timedelta(minutes=index * 5)).isoformat(),
        "event_type": "network",
        "outcome": "allowed",
        "source_ip": f"192.0.2.{index % 254 + 1}",
        "destination_ip": f"198.51.100.{index % 20 + 1}",
        "username": f"synthetic-user-{index % 24 + 1:02d}",
        "action": "",
        "destination_port": ports[index % len(ports)],
        "bytes_transferred": 500 + (index * 7919 % 11_500),
        "asset": "SYNTHETIC_NORMAL",
    }


def write_dataset(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing evaluation dataset: {path}")
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    training_start = datetime(2026, 8, 1, tzinfo=UTC)
    test_start = datetime(2026, 9, 1, tzinfo=UTC)
    training_rows = [
        build_row(index, training_start, unusual=False) for index in range(240)
    ]
    test_rows = [
        {
            **build_row(index, test_start, unusual=False),
            "asset": "SYNTHETIC_EVALUATION",
            "is_anomaly": 0,
        }
        for index in range(90)
    ]
    test_rows.extend(
        {
            **build_row(index, test_start + timedelta(days=1), unusual=True),
            "is_anomaly": 1,
        }
        for index in range(10)
    )
    train_path = DATA_DIR / "ml_evaluation_train.csv"
    test_path = DATA_DIR / "ml_evaluation_test.csv"
    if train_path.exists() or test_path.exists():
        raise FileExistsError("Refusing to overwrite an existing evaluation dataset")
    write_dataset(train_path, training_rows, FEATURE_COLUMNS)
    write_dataset(test_path, test_rows, [*FEATURE_COLUMNS, "is_anomaly"])
    print(f"Created {train_path.name}: {len(training_rows)} unlabeled normal-pattern training rows")
    print(f"Created {test_path.name}: 90 labeled normal and 10 labeled anomalous test rows")


if __name__ == "__main__":
    main()
