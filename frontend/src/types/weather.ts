import type { Freshness, ISODate } from "./common";

export interface LocationRef {
  code: string;
  name_th: string | null;
  name_en: string;
  province_code: string | null;
  lat: number;
  lon: number;
}

export interface Condition {
  code: "heavy_rain" | "moderate_rain" | "light_rain" | "overcast" | "partly_cloudy" | "clear";
  label_th: string;
}

export interface ForecastHour {
  time: ISODate;
  temperature_c: number | null;
  feels_like_c: number | null;
  humidity_pct: number | null;
  precipitation_mm: number | null;
  rain_probability_pct: number | null;
  rain_probability_basis: "model_provided" | "model_agreement" | null;
  wind_speed_kmh: number | null;
  wind_direction_deg: number | null;
  pressure_msl_hpa: number | null;
  cloud_cover_pct: number | null;
  condition: Condition | null;
  confidence: Record<string, number | null>;
  n_models: number;
}

export interface ObservedNow {
  kind: "observed";
  source: string;
  station_code: string;
  station_name: string | null;
  distance_km: number;
  observed_at: ISODate;
  temperature_c: number | null;
  dew_point_c: number | null;
  pressure_msl_hpa: number | null;
  wind_speed_kmh: number | null;
  rain_mm: number | null;
  rain_period_hours: number | null;
}

export interface WeatherCurrent {
  location: LocationRef;
  observed: ObservedNow | null;
  forecast_now: ForecastHour | null;
  forecast_basis: string;
  hourly: ForecastHour[];
  models: { model: string; model_run_time: ISODate; fetched_at: ISODate }[];
  freshness: { observed: Freshness | null; forecast: Freshness[] };
}

export interface RainWindow {
  ecmwf?: number;
  gfs?: number;
  jma?: number;
  consensus: number | null;
  min: number | null;
  max: number | null;
  median: number | null;
  std: number | null;
  likely_range: [number, number] | null;
  confidence: number | null;
  n_models: number;
  probability_model_agreement: number | null;
  hours: number;
}

export interface RainComparison {
  location: LocationRef;
  now: ISODate;
  hour0: ISODate;
  observed: {
    radius_km: number;
    stations: number;
    series: { time: ISODate; mean_mm: number; max_mm: number; n_stations: number }[];
    note: string;
  };
  models: Record<string, { time: ISODate; mm: number | null }[]>;
  model_runs: { model: string; model_run_time: ISODate }[];
  consensus: { time: ISODate; mm: number | null; confidence: number | null }[];
  windows: Record<string, RainWindow>;
  freshness: { observed: Freshness | null; forecast: Freshness[] };
}

export type RainWindowKey = "1h" | "3h" | "6h" | "24h";

export interface RainPoint {
  station_code: string;
  name: string | null;
  province?: string | null;
  lat: number | null;
  lon: number | null;
  value_mm: number;
  window: string;
  observed_at: ISODate;
  source: string;
  kind: "observed";
}

export interface RainfallResponse {
  window: RainWindowKey;
  points: RainPoint[];
  stations: number;
  incomplete_stations: number;
  note: string | null;
  freshness: { gauges: Freshness | null; synoptic: Freshness | null };
}

export interface WeatherStationPoint {
  station_code: string;
  name: string | null;
  lat: number;
  lon: number;
  observed_at: ISODate;
  temperature_c: number | null;
  rain_mm: number | null;
  rain_period_hours: number | null;
}

export interface RainForecastPoint {
  code: string;
  name: string | null;
  lat: number;
  lon: number;
  value_mm: number;
  min: number | null;
  max: number | null;
  confidence: number | null;
  n_models: number;
  kind: "forecast";
}

export interface RainForecastResponse {
  window: string;
  kind: "forecast";
  points: RainForecastPoint[];
  note: string;
}
