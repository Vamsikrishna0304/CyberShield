import type {
  AnomalyRecord,
  DashboardSummary,
  DetectionRecord,
  EventRecord,
  IngestionResult,
  ModelEvaluation,
  TrendPoint,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export const getSummary = () => request<DashboardSummary>("/dashboard/summary");
export const getTrends = () => request<TrendPoint[]>("/dashboard/trends?days=14");
export const getEvents = (filters = new URLSearchParams()) => {
  const query = new URLSearchParams(filters);
  query.set("limit", "100");
  return request<EventRecord[]>(`/events?${query}`);
};
export const getDetections = () => request<DetectionRecord[]>("/detections?limit=5");
export const getAnomalies = (filters = new URLSearchParams()) => {
  const query = new URLSearchParams(filters);
  query.set("limit", "100");
  return request<AnomalyRecord[]>(`/analytics/anomalies?${query}`);
};
export const getEvaluation = () => request<ModelEvaluation>("/analytics/evaluation");

export async function exportFilteredAnalytics(filters: URLSearchParams): Promise<void> {
  const query = new URLSearchParams(filters);
  const response = await fetch(`/api/v1/analytics/export.csv?${query}`);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Export failed (${response.status})`);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "cybershield-analytics.csv";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function uploadCsv(file: File): Promise<IngestionResult> {
  const form = new FormData();
  form.append("file", file);
  return request<IngestionResult>("/ingest", { method: "POST", body: form });
}
