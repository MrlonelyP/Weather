import type { DashboardSummary, SourcesHealthResponse } from "@/types/dashboard";
import { apiGet } from "./api";

export const dashboardService = {
  summary: (signal?: AbortSignal) => apiGet<DashboardSummary>("/api/dashboard/summary", undefined, signal),
  sourcesHealth: (signal?: AbortSignal) => apiGet<SourcesHealthResponse>("/api/sources/health", undefined, signal),
};
