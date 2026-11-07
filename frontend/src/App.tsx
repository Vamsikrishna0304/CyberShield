import { useCallback, useEffect, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getDetections,
  getEvents,
  getAnomalies,
  getEvaluation,
  getSummary,
  getTrends,
  exportFilteredAnalytics,
  uploadCsv,
} from "./services/api";
import type {
  DashboardSummary,
  AnomalyRecord,
  DetectionRecord,
  EventRecord,
  IngestionResult,
  ModelEvaluation,
  TrendPoint,
} from "./types";

const severityOrder = ["critical", "high", "medium", "low", "informational"] as const;

function createEventFilters(startDate: string, endDate: string) {
  const filters = new URLSearchParams();
  if (startDate) filters.set("start_date", startDate);
  if (endDate) filters.set("end_date", endDate);
  return filters;
}

function createAnomalyFilters(severity: string, minScore: string, maxScore: string) {
  const filters = new URLSearchParams();
  if (severity) filters.set("severity", severity);
  if (minScore) filters.set("min_anomaly_score", minScore);
  if (maxScore) filters.set("max_anomaly_score", maxScore);
  return filters;
}

function createAnalyticsFilters(
  startDate: string,
  endDate: string,
  severity: string,
  minScore: string,
  maxScore: string,
) {
  const filters = createEventFilters(startDate, endDate);
  createAnomalyFilters(severity, minScore, maxScore).forEach((value, key) =>
    filters.set(key, value),
  );
  return filters;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function App() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [detections, setDetections] = useState<DetectionRecord[]>([]);
  const [anomalies, setAnomalies] = useState<AnomalyRecord[]>([]);
  const [evaluation, setEvaluation] = useState<ModelEvaluation | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [minScore, setMinScore] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [activeSection, setActiveSection] = useState(() => window.location.hash || "#overview");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const syncActiveSection = () => setActiveSection(window.location.hash || "#overview");
    window.addEventListener("hashchange", syncActiveSection);
    return () => window.removeEventListener("hashchange", syncActiveSection);
  }, []);

  const refresh = useCallback(async () => {
    const [nextSummary, nextTrends, nextEvents, nextDetections, nextAnomalies, nextEvaluation] = await Promise.all([
      getSummary(),
      getTrends(),
      getEvents(createEventFilters(startDate, endDate)),
      getDetections(),
      getAnomalies(createAnomalyFilters(severityFilter, minScore, maxScore)),
      getEvaluation(),
    ]);
    setSummary(nextSummary);
    setTrends(nextTrends);
    setEvents(nextEvents);
    setDetections(nextDetections);
    setAnomalies(nextAnomalies);
    setEvaluation(nextEvaluation);
    setError(null);
  }, [startDate, endDate, severityFilter, minScore, maxScore]);

  useEffect(() => {
    refresh()
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "Could not load dashboard"),
      )
      .finally(() => setLoading(false));
  }, [refresh]);

  async function handleUpload(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setUploadMessage(null);
    setError(null);
    try {
      const result: IngestionResult = await uploadCsv(file);
      setUploadMessage(
        `${result.accepted_rows} accepted · ${result.duplicate_rows} duplicates · ${result.rejected_rows} rejected · ${
          result.anomaly_model_status === "analyzed"
            ? `Isolation Forest flagged ${result.anomalies_detected}`
            : "Isolation Forest skipped: at least 20 accepted events per upload are required"
        }`,
      );
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function handleExport() {
    setError(null);
    try {
      await exportFilteredAnalytics(
        createAnalyticsFilters(startDate, endDate, severityFilter, minScore, maxScore),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "CSV export failed");
    }
  }

  const metricCards = summary
    ? [
        { label: "Events analyzed", value: summary.total_events.toLocaleString(), detail: "All ingested events", tone: "blue" },
        { label: "Rule matches", value: summary.rule_matches.toLocaleString(), detail: "Explainable evidence generated", tone: "purple" },
        { label: "ML anomaly signals", value: summary.ml_anomalies.toLocaleString(), detail: "Isolation Forest · review required", tone: "amber" },
        { label: "High-risk events", value: summary.high_risk_events.toLocaleString(), detail: "High and critical", tone: "red" },
        { label: "Average risk score", value: summary.average_risk.toFixed(1), detail: "Rule-based · out of 100", tone: "blue" },
      ]
    : [];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" aria-label="CyberShield home">
          <span className="brand-mark">C</span>
          <span>Cyber<span className="brand-light">Shield</span></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="nav-list" aria-label="Main navigation">
          <a className={`nav-item ${activeSection === "#overview" ? "active" : ""}`} href="#overview"><span>◫</span> Overview</a>
          <a className={`nav-item ${activeSection === "#events" ? "active" : ""}`} href="#events"><span>▤</span> Security events</a>
          <a className={`nav-item ${activeSection === "#detections" ? "active" : ""}`} href="#detections"><span>◉</span> Detections</a>
          <a className={`nav-item ${activeSection === "#risk" ? "active" : ""}`} href="#risk"><span>◇</span> Risk analytics</a>
          <a className={`nav-item ${activeSection === "#evaluation" ? "active" : ""}`} href="#evaluation"><span>▥</span> Model evaluation</a>
        </nav>
        <div className="sidebar-bottom">
          <div className="system-card">
            <span className="online-dot" />
            <div><strong>Analytics engine</strong><small>Local environment</small></div>
          </div>
          <div className="sidebar-note">Cyber risk intelligence<br />for informed decisions.</div>
        </div>
      </aside>

      <main className="main-content" id="overview">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> <strong>Overview</strong></div>
          <div className="topbar-actions">
            <span className="environment-badge"><span className="online-dot" /> Demo environment</span>
            <label className={`upload-button ${uploading ? "disabled" : ""}`}>
              {uploading ? "Uploading..." : "↑  Import event logs"}
              <input
                ref={fileInput}
                type="file"
                accept=".csv,text/csv"
                disabled={uploading}
                onChange={(event) => void handleUpload(event.target.files?.[0])}
              />
            </label>
          </div>
        </header>

        <section className="page-heading">
          <div>
            <p className="eyebrow">CYBER RISK INTELLIGENCE</p>
            <h1>Security overview</h1>
            <p className="subtitle">Monitor event activity, identify signals, and understand risk exposure.</p>
          </div>
          <div className="updated-label"><span className="online-dot" /> Live from local data</div>
        </section>

        {error && <div className="alert error-alert" role="alert">{error}</div>}
        {uploadMessage && <div className="alert success-alert" role="status">{uploadMessage}</div>}

        {loading ? (
          <div className="loading-panel" role="status">Loading security analytics…</div>
        ) : (
          <>
            <section className="metric-grid" aria-label="Key metrics">
              {metricCards.map((card) => (
                <article className="metric-card" key={card.label}>
                  <div className="metric-topline"><span>{card.label}</span><span className={`metric-icon ${card.tone}`}>◆</span></div>
                  <strong className="metric-value">{card.value}</strong>
                  <span className="metric-detail">{card.detail}</span>
                </article>
              ))}
            </section>

            <section className="content-grid">
              <article className="panel trend-panel">
                <div className="panel-heading">
                  <div><h2>Event activity</h2><p>Events and detections · last 14 days</p></div>
                  <span className="chart-legend"><i /> Events <i className="flagged-legend" /> Flagged</span>
                </div>
                {trends.length ? (
                  <div className="chart-wrap">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={trends} margin={{ top: 10, right: 12, bottom: 0, left: -18 }}>
                        <defs><linearGradient id="eventFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5576f6" stopOpacity={0.2} /><stop offset="95%" stopColor="#5576f6" stopOpacity={0} /></linearGradient></defs>
                        <CartesianGrid stroke="#edf0f5" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={(value: string) => value.slice(5)} tickLine={false} axisLine={false} tick={{ fill: "#8791a3", fontSize: 11 }} />
                        <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "#8791a3", fontSize: 11 }} />
                        <Tooltip />
                        <Area type="monotone" dataKey="total" name="Events" stroke="#5576f6" strokeWidth={2.5} fill="url(#eventFill)" />
                        <Line type="monotone" dataKey="flagged_events" name="Flagged events" stroke="#e99545" strokeWidth={2} dot={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                ) : <div className="empty-chart">Import a CSV log to see event activity.</div>}
              </article>

              <article className="panel severity-panel" id="risk">
                <div className="panel-heading"><div><h2>Risk distribution</h2><p>Event severity breakdown</p></div></div>
                <div className="severity-list">
                  {severityOrder.map((level) => {
                    const count = summary?.severity_counts[level] ?? 0;
                    const total = summary?.total_events ?? 0;
                    const percent = total ? (count / total) * 100 : 0;
                    return <div className="severity-row" key={level}>
                      <div className="severity-label"><span className={`severity-dot ${level}`} />{level}<strong>{count}</strong></div>
                      <div className="progress-track"><div className={`progress-fill ${level}`} style={{ width: `${percent}%` }} /></div>
                    </div>;
                  })}
                </div>
                <div className="method-note">Scores are rule-based signals, not confirmed incidents.</div>
              </article>
            </section>

            <section className="panel table-panel" id="detections">
              <div className="panel-heading table-heading">
                <div><h2>Recent detections</h2><p>Explainable rule matches requiring review</p></div>
                <a className="text-link" href="#events">View events ↓</a>
              </div>
              {detections.length ? <div className="table-scroll"><table>
                <thead><tr><th>Rule</th><th>Event type</th><th>Evidence</th><th>Severity</th><th>Score</th></tr></thead>
                <tbody>{detections.map((detection) => <tr key={detection.id}>
                  <td className="rule-name">{detection.rule_name.replaceAll("_", " ")}</td>
                  <td>{detection.event_type}</td>
                  <td className="evidence-cell">{detection.evidence}</td>
                  <td><span className={`severity-pill ${detection.severity}`}>{detection.severity}</span></td>
                  <td className="score-cell">{detection.score}</td>
                </tr>)}</tbody>
              </table></div> : <div className="empty-state">No detections yet. Import event logs to run the baseline rules.</div>}
            </section>

            <section className="panel table-panel" id="anomalies">
              <div className="panel-heading table-heading">
                <div><h2>Isolation Forest signals</h2><p>Unsupervised model leads · review in context, not confirmed incidents</p></div>
                <button className="export-button" type="button" onClick={() => void handleExport()}>Export filtered CSV</button>
              </div>
              <div className="filter-toolbar" aria-label="Anomaly filters">
                <label>Severity
                  <select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}>
                    <option value="">All severities</option>
                    {severityOrder.map((level) => <option key={level} value={level}>{level}</option>)}
                  </select>
                </label>
                <label>Min anomaly score
                  <input type="number" step="0.001" value={minScore} onChange={(event) => setMinScore(event.target.value)} />
                </label>
                <label>Max anomaly score
                  <input type="number" step="0.001" value={maxScore} onChange={(event) => setMaxScore(event.target.value)} />
                </label>
              </div>
              {anomalies.length ? <div className="table-scroll"><table>
                <thead><tr><th>Event type</th><th>Source IP</th><th>User</th><th>Severity</th><th>Model</th><th>Anomaly score</th></tr></thead>
                <tbody>{anomalies.map((anomaly) => <tr key={anomaly.id}>
                  <td className="rule-name">{anomaly.event_type}</td>
                  <td>{anomaly.source_ip ?? "—"}</td>
                  <td>{anomaly.username ?? "—"}</td>
                  <td><span className={`severity-pill ${anomaly.severity}`}>{anomaly.severity}</span></td>
                  <td>{anomaly.model_version}</td>
                  <td className="score-cell" title={anomaly.evidence}>{anomaly.anomaly_score.toFixed(4)}</td>
                </tr>)}</tbody>
              </table></div> : <div className="empty-state">No stored anomaly signals. Isolation Forest runs on uploads with at least 20 accepted, nonduplicate events.</div>}
            </section>

            <section className="panel table-panel" id="evaluation">
              <div className="panel-heading table-heading">
                <div><h2>Synthetic model evaluation</h2><p>Held-out labeled synthetic records · {evaluation?.model_version} · selected contamination {evaluation ? `${(evaluation.contamination * 100).toFixed(0)}%` : ""}</p></div>
              </div>
              {evaluation && <div className="evaluation-content">
                <div className="evaluation-stats">
                  <article><span>Precision</span><strong>{(evaluation.precision * 100).toFixed(1)}%</strong></article>
                  <article><span>Recall</span><strong>{(evaluation.recall * 100).toFixed(1)}%</strong></article>
                  <article><span>F1-score</span><strong>{(evaluation.f1_score * 100).toFixed(1)}%</strong></article>
                  <article><span>Train / test</span><strong>{evaluation.training_records} / {evaluation.testing_records}</strong></article>
                  <article><span>Predicted anomalies</span><strong>{evaluation.predicted_anomalies}</strong></article>
                </div>
                <div className="confusion-wrap">
                  <h3>Confusion matrix <span>(rows: actual · columns: predicted)</span></h3>
                  <div className="table-scroll">
                    <table className="confusion-table">
                      <thead><tr><th>Actual / predicted</th><th>Normal</th><th>Anomaly</th></tr></thead>
                      <tbody>{evaluation.confusion_matrix.map((row, index) => <tr key={evaluation.class_names[index]}>
                        <th>{evaluation.class_names[index]}</th><td>{row[0]}</td><td>{row[1]}</td>
                      </tr>)}</tbody>
                    </table>
                  </div>
                </div>
                <div className="confusion-wrap">
                  <h3>Configuration comparison <span>(same fixed test split)</span></h3>
                  <div className="table-scroll">
                    <table className="experiment-table">
                      <thead><tr><th>Detector</th><th>Contamination</th><th>Precision</th><th>Recall</th><th>F1-score</th><th>Predicted</th><th>Confusion matrix</th></tr></thead>
                      <tbody>
                        {evaluation.contamination_experiments.map((experiment) => <tr key={experiment.contamination}>
                          <td className="rule-name">{experiment.contamination === evaluation.contamination ? `${evaluation.model_version} (selected)` : "Isolation Forest"}</td>
                          <td>{(experiment.contamination * 100).toFixed(0)}%</td>
                          <td>{experiment.precision.toFixed(3)}</td>
                          <td>{experiment.recall.toFixed(3)}</td>
                          <td className="score-cell">{experiment.f1_score.toFixed(3)}</td>
                          <td>{experiment.predicted_anomalies}</td>
                          <td>[{experiment.confusion_matrix[0].join(", ")}] / [{experiment.confusion_matrix[1].join(", ")}]</td>
                        </tr>)}
                        <tr>
                          <td className="rule-name">Rule-based baseline</td><td>—</td>
                          <td>{evaluation.rule_based_baseline.precision.toFixed(3)}</td>
                          <td>{evaluation.rule_based_baseline.recall.toFixed(3)}</td>
                          <td className="score-cell">{evaluation.rule_based_baseline.f1_score.toFixed(3)}</td>
                          <td>{evaluation.rule_based_baseline.predicted_anomalies}</td>
                          <td>[{evaluation.rule_based_baseline.confusion_matrix[0].join(", ")}] / [{evaluation.rule_based_baseline.confusion_matrix[1].join(", ")}]</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
                <p className="evaluation-note">{evaluation.methodology} The test set contains {evaluation.actual_normal} normal and {evaluation.actual_anomalies} anomalous events. These measured metrics describe only this fixed synthetic split and should not be generalized.</p>
              </div>}
            </section>

            <section className="panel table-panel events-panel" id="events">
              <div className="panel-heading table-heading">
                <div><h2>Recent security events</h2><p>Latest normalized records</p></div>
              </div>
              <div className="filter-toolbar event-filters" aria-label="Security event date filters">
                <label>From date
                  <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
                </label>
                <label>Through date
                  <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
                </label>
              </div>
              {events.length ? <div className="table-scroll"><table>
                <thead><tr><th>Time</th><th>Event type</th><th>Source IP</th><th>User</th><th>Outcome</th><th>Risk</th></tr></thead>
                <tbody>{events.map((event) => <tr key={event.id}>
                  <td>{formatTime(event.event_time)}</td>
                  <td className="rule-name">{event.event_type}</td>
                  <td>{event.source_ip ?? "—"}</td>
                  <td>{event.username ?? "—"}</td>
                  <td>{event.outcome}</td>
                  <td><span className={`severity-pill ${event.risk_level}`}>{event.risk_level} · {event.risk_score}</span></td>
                </tr>)}</tbody>
              </table></div> : <div className="empty-state">No events ingested. Import a CSV file to begin.</div>}
            </section>
          </>
        )}
        <footer className="page-footer">CyberShield <span>·</span> Local analytics demo · Review signals in context</footer>
      </main>
    </div>
  );
}

export default App;
