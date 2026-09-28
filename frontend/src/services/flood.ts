import type { FloodExtentResponse, FloodRiskResponse } from "@/types/flood";
import { apiGet } from "./api";

export const floodService = {
  extent: (signal?: AbortSignal) => apiGet<FloodExtentResponse>("/api/flood/extent", undefined, signal),
  risk: (signal?: AbortSignal) => apiGet<FloodRiskResponse>("/api/flood/risk", undefined, signal),
};
