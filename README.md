# CyberShield

CyberShield is a local-first cybersecurity event analytics dashboard. It ingests
CSV event logs, applies transparent detection rules and event-level risk scoring,
and runs a batch-scoped Isolation Forest to surface explainable-in-context anomaly
leads in a React dashboard. It is an educational analytics project, not a
production SIEM or a substitute for incident response.

## Requirements

- Node.js 20.19+ or 22.12+ and npm
- Python 3.12 or later
- Git

Scientific package support depends on available prebuilt wheels for your Python
version. Use a supported Python version if dependency installation fails.
SQLite is bundled with Python; a separate SQLite CLI is not required.

## Run locally

### Backend

From the repository root, create and activate a virtual environment:

```powershell
py -3 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend
```

The API is available at `http://127.0.0.1:8000`; interactive API documentation
is at `http://127.0.0.1:8000/docs`. The SQLite database is created under
`data\cybershield.sqlite3` on first run.

### Frontend

In another terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Vite proxies `/api` requests to the local backend. The dashboard opens at
`http://localhost:5173`.

### Tests and checks

```powershell
python -m pytest backend\tests
cd frontend
npm.cmd run build
```

## CSV format

Upload a UTF-8 CSV with a header row. `event_time`, `event_type`, and `outcome`
are required. Optional columns are `source_ip`, `destination_ip`, `username`,
`action`, `destination_port`, `bytes_transferred`, and `asset`. Timestamps should
be ISO-8601; timezone-naive timestamps are treated as UTC. Invalid rows are
reported and skipped, duplicate events are ignored, and uploads are limited to
5 MiB.

Use the synthetic `data\sample_events.csv` to try the dashboard. Do not upload
real or sensitive security logs into an environment that is not approved to
handle them.

For Isolation Forest validation, `data\synthetic_ml_validation_events.csv`
contains 100 explicitly synthetic records: 95 normal-pattern and 5
unusual-pattern records, labeled in the `asset` column. Upload this separate
dataset once to exercise the minimum batch size and anomaly-signal display. The
labels are test fixtures, not a representative or independently validated
cybersecurity benchmark; do not infer model accuracy from this demonstration.

## Detection and risk methodology

Each event receives an explainable additive rule score: failed authentication
adds 30 points, a privileged or destructive action adds 40, and a destination
port associated with remote administration (22, 3389, or 445) adds 15. Scores
are capped at 100. Severity is informational (0), low (1–29), medium (30–59),
high (60–84), or critical (85–100). Rule names and evidence are retained with
each detection. These starter rules are illustrative and should be tuned to the
organization, data quality, and threat model before operational use.

The versioned `isolation-forest-v2` model runs separately on each upload's
accepted, nonduplicate events when that batch contains at least 20 records.
Smaller batches are explicitly reported as `insufficient_data`; they do not
silently fall back to a model result. The deterministic model uses byte volume,
destination port, outcome/action indicators, authentication-event indicator,
and cyclic time-of-day features; it uses a fixed random seed and a 10%
contamination setting. Only flagged rows are persisted in `anomaly_signals` and
returned by `GET /api/v1/analytics/anomalies`. Its decision score is model
relative (lower is more unusual), not the rule-based 0–100 risk score. Model
signals never change the rule risk score or severity and are leads for human
review, not confirmed malicious activity. Isolation Forest is not a substitute
for labeled-data evaluation, operational tuning, or incident response.

## Synthetic model evaluation

The dashboard's Model evaluation panel is computed by the backend from a fixed,
separate split: `data\ml_evaluation_train.csv` contains 240 unlabeled
normal-pattern training records; `data\ml_evaluation_test.csv` contains 90
normal and 10 labeled unusual-pattern test records. The test label column is
removed before test events are passed to the model and is used only to calculate
metrics. The three experiments use 100 trees and random seed 42, changing only
the Isolation Forest contamination setting:

| Contamination | Predicted anomalies | Precision | Recall | F1-score | Confusion matrix (actual rows, predicted columns) |
|---:|---:|---:|---:|---:|---|
| 0.05 | 5 | 0.200 | 0.100 | 0.133 | `[[86, 4], [9, 1]]` |
| 0.10 (selected) | 15 | 0.333 | 0.500 | 0.400 | `[[80, 10], [5, 5]]` |
| 0.15 | 24 | 0.250 | 0.600 | 0.353 | `[[72, 18], [4, 6]]` |
| Rule-based baseline | 0 | 0.000 | 0.000 | 0.000 | `[[90, 0], [10, 0]]` |

The 0.10 setting is used by `isolation-forest-v2` because it had the highest
F1-score among the three requested experiments on this split. It increases
recall from 0.10 to 0.50, while increasing false positives from 4 to 10. The
rule-based baseline is the existing `assess_event` detection logic applied
unchanged to these test events; none of the synthetic test rows matched its
rules. The rule and model results are compared, not combined.

Feature inspection helps explain the results. The synthetic anomaly rows have
`log1p(bytes_transferred)` from 19.34 to 19.98 versus a normal range of 6.22 to
9.38, and scaled destination ports around 0.946 versus normal values at or below
0.0068. Outcome, event-type, and action indicator features are identical across
the classes (zero). The model therefore has strong byte/port differences but
the 5% training-derived decision threshold flags only one anomaly; increasing
contamination shifts that threshold and trades precision for recall. The test
generator also gives normal records a 00:00–07:25 time-of-day range, while
training spans the full day. This distribution shift can contribute to false
positives and limits what this fixed synthetic test can establish.

These are exploratory measurements on one small, deliberately synthetic split.
Because the 0.10 setting was selected after comparing these test results, the
test split is no longer an independent final estimate of the selected model's
performance. Use a new, independently labeled validation set before drawing
performance conclusions or operationally tuning this model. The metrics do not
establish performance on real cybersecurity traffic or another organization's
environment. The synthetic label is stripped before feature extraction, and
the `asset` field is not a model feature; labels are used only for metric
calculation. Do not treat either rules or model output as confirmed incidents.

The dashboard supports severity and anomaly-score filtering for stored model
signals, inclusive date filtering for security events, and CSV export using the
selected date, severity, and score filters. Anomaly scores are Isolation Forest
decision scores (lower is more unusual); they are not the rule-based risk score.

## Data handling and limitations

The API validates an explicit CSV column allowlist, limits upload size, does
not execute uploaded content, and stores normalized values locally. The
development API has no authentication and SQLite is intended for a single-user
local demo; do not expose it to untrusted networks or treat it as a production
multi-user deployment.
