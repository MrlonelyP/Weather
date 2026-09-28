import type { LocationAnalysis } from "@/types/location";
import { apiGet } from "./api";

export const locationService = {
  analyze: (lat: number, lon: number, signal?: AbortSignal) =>
    apiGet<LocationAnalysis>("/api/location/analyze", { lat, lon }, signal),
};
