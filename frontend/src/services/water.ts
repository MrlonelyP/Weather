import type {
  NearbyResponse,
  RangeKey,
  ReservoirsResponse,
  StationDetail,
  TideResponse,
  WaterFilters,
  WaterStationsResponse,
} from "@/types/water";
import { apiGet } from "./api";

export interface StationQuery {
  sort?: "risk" | "level" | "trend";
  province?: string;
  basin?: string;
  river?: string;
  status?: string;
  q?: string;
  limit?: number;
}

export const waterService = {
  stations: (query: StationQuery = {}, signal?: AbortSignal) =>
    apiGet<WaterStationsResponse>("/api/water/stations", { ...query }, signal),
  filters: (signal?: AbortSignal) => apiGet<WaterFilters>("/api/water/filters", undefined, signal),
  station: (code: string, range: RangeKey, signal?: AbortSignal) =>
    apiGet<StationDetail>(`/api/water/stations/${encodeURIComponent(code)}`, { range }, signal),
  nearby: (lat: number, lon: number, radiusKm = 10, signal?: AbortSignal) =>
    apiGet<NearbyResponse>("/api/water/nearby", { lat, lon, radius_km: radiusKm }, signal),
  reservoirs: (signal?: AbortSignal) => apiGet<ReservoirsResponse>("/api/reservoirs", undefined, signal),
  tide: (signal?: AbortSignal) => apiGet<TideResponse>("/api/tide", undefined, signal),
};
