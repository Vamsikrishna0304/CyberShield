export type Severity = "informational" | "low" | "medium" | "high" | "critical";

export interface DashboardSummary {
  total_events: number;
  rule_matches: number;
  ml_anomalies: number;
  high_risk_events: number;
  average_risk: number;
  severity_counts: Record<Severity, number>;
}

export interface TrendPoint {
  date: string;
  total: number;
  flagged_events: number;
}

export interface EventRecord {
  id: number;
  event_time: string;
  source_ip: string | null;
  destination_ip: string | null;
  username: string | null;
  event_type: string;
  action: string | null;
  outcome: string;
  destination_port: number | null;
  bytes_transferred: number | null;
  asset: string | null;
  risk_score: number;
  risk_level: Severity;
}

export interface DetectionRecord {
  id: number;
  event_id: number;
  event_time: string;
  source_ip: string | null;
  username: string | null;
  event_type: string;
  rule_name: string;
  severity: Severity;
  score: number;
  evidence: string;
}

export interface AnomalyRecord {
  id: number;
  event_id: number;
  event_time: string;
  source_ip: string | null;
  username: string | null;
  event_type: string;
  severity: Severity;
  risk_score: number;
  model_version: string;
  anomaly_score: number;
  evidence: string;
}

export interface ModelEvaluation {
  model_version: string;
  evaluation_scope: "synthetic";
  contamination: number;
  training_records: number;
  testing_records: number;
  actual_normal: number;
  actual_anomalies: number;
  predicted_anomalies: number;
  precision: number;
  recall: number;
  f1_score: number;
  confusion_matrix: number[][];
  class_names: string[];
  contamination_experiments: ContaminationExperiment[];
  rule_based_baseline: EvaluationMetrics;
  methodology: string;
}

export interface EvaluationMetrics {
  predicted_anomalies: number;
  precision: number;
  recall: number;
  f1_score: number;
  confusion_matrix: number[][];
}

export interface ContaminationExperiment extends EvaluationMetrics {
  contamination: number;
}

export interface IngestionResult {
  batch_id: number;
  filename: string;
  received_rows: number;
  accepted_rows: number;
  duplicate_rows: number;
  rejected_rows: number;
  errors: string[];
  anomaly_model_status: "analyzed" | "insufficient_data";
  anomalies_detected: number;
}
