import type {
  LocationRef,
  RainComparison,
  RainForecastResponse,
  RainfallResponse,
  RainWindowKey,
  WeatherCurrent,
  WeatherStationPoint,
} from "@/types/weather";
import { apiGet } from "./api";

export const weatherService = {
  locations: (signal?: AbortSignal) => apiGet<{ locations: LocationRef[] }>("/api/weather/locations", undefined, signal),
  current: (location: string, signal?: AbortSignal) =>
    apiGet<WeatherCurrent>("/api/weather/current", { location }, signal),
  rainfall: (window: RainWindowKey, signal?: AbortSignal) =>
    apiGet<RainfallResponse>("/api/rainfall", { window }, signal),
  comparison: (location: string, signal?: AbortSignal) =>
    apiGet<RainComparison>("/api/rainfall/comparison", { location, past_hours: 24, future_hours: 24 }, signal),
  rainForecast: (window: string, signal?: AbortSignal) =>
    apiGet<RainForecastResponse>("/api/rainfall/forecast", { window }, signal),
  stations: (signal?: AbortSignal) =>
    apiGet<{ stations: WeatherStationPoint[] }>("/api/weather/stations", undefined, signal),
};
