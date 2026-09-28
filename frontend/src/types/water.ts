import type { Freshness, ISODate } from "./common";

/** System-computed status (NOT an official warning). */
export type WaterStatus = "NORMAL" | "WATCH" | "WARNING" | "CRITICAL" | "UNKNOWN";
export type Trend = "rising" | "falling" | "steady" | null;

export interface SourceAssessment {
  situation_level: number | null;
  diff_to_bank_m: number | null;
  diff_to_bank_text: string | null;
  note?: string;
}

export interface WaterStation {
  station_id: number;
  station_code: string;
  name: string | null;
  river: string | null;
  basin: string | null;
  province: string | null;
  province_code: string | null;
  amphoe: string | null;
  agency: string | null;
  is_key_station: boolean;
  lat: number | null;
  lon: number | null;
  discharge_m3s: number | null;
  current_m: number | null;
  observed_at: ISODate | null;
  bank_m: number | null;
  distance_to_bank_m: number | null;
  warning_level_m: number | null;
  distance_to_warning_m: number | null;
  critical_level_m: number | null;
  change_1h_m: number | null;
  rate_cm_per_h: number | null;
  trend: Trend;
  trend_label_th: string;
  status: WaterStatus;
  status_label_th: string;
  status_basis: string;
  reference_note?: string | null;
  source_assessment: SourceAssessment;
  source: string;
  match?: "direct" | "nearby";
  distance_km?: number;
}

export interface WaterStationsResponse {
  generated_at: ISODate;
  counts: Record<WaterStatus, number>;
  stations: WaterStation[];
  status_basis: string;
  freshness: Freshness | null;
}

export interface FilterOption {
  value: string;
  label?: string | null;
  count: number;
}

export interface WaterFilters {
  provinces: FilterOption[];
  basins: FilterOption[];
  rivers: FilterOption[];
  statuses: FilterOption[];
}

export type RangeKey = "6h" | "24h" | "3d" | "7d";

export type ImpactOutlook = "likely_rise" | "possible_rise" | "no_signal" | "insufficient_data";

export interface ForecastImpact {
  outlook: ImpactOutlook;
  label_th: string;
  reasons: string[];
  basis: string;
  disclaimer: string;
  forecast_point: { code: string; name_th: string; distance_km: number } | null;
}

export interface StationDetail {
  station_code: string;
  name: string | null;
  river: string | null;
  basin: string | null;
  province: string | null;
  province_code: string | null;
  amphoe: string | null;
  tumbon: string | null;
  agency: string | null;
  lat: number | null;
  lon: number | null;
  source: string;
  datum: string | null;
  levels: { bank_m: number | null; warning_m: number | null; critical_m: number | null; ground_m: number | null; basis: string; note: string | null };
  state: Omit<WaterStation, "station_id" | "station_code" | "name" | "river" | "basin" | "province" | "province_code" | "amphoe" | "agency" | "is_key_station" | "lat" | "lon" | "source_assessment" | "source"> & {
    discharge_m3s: number | null;
    points_used: number;
  };
  stats_24h: { max_m: number | null; max_at: ISODate | null; min_m: number | null; min_at: ISODate | null };
  source_assessment: SourceAssessment;
  range: RangeKey;
  series: { time: ISODate; level_m: number; discharge_m3s: number | null }[];
  history_available_since: ISODate | null;
  history_note: string | null;
  forecast: null | { time: ISODate; level_m: number }[];
  forecast_note: string | null;
  impact: ForecastImpact;
  freshness: Freshness | null;
  network: StationNetwork | null;
}

export interface NearbyResponse {
  center: { lat: number; lon: number };
  radius_km: number;
  stations: WaterStation[];
  rivers: { name: string; station_codes: string[] }[];
  rain_gauges: RainGaugeNear[];
  impact: ForecastImpact;
  impact_station: string | null;
  flood_extent: { available: boolean; reason: string };
}

export interface RainGaugeNear {
  station_code: string;
  name: string | null;
  lat: number | null;
  lon: number | null;
  distance_km: number;
  rain_24h_mm: number | null;
  rain_1h_mm?: number | null;
  observed_at: ISODate | null;
}

export interface Reservoir {
  reservoir_code: string;
  name: string | null;
  region: string | null;
  lat: number | null;
  lon: number | null;
  volume_mcm: number | null;
  normal_storage_mcm: number | null;
  pct: number | null;
  pct_change: number | null;
  usable_mcm: number | null;
  usable_pct: number | null;
  inflow_mcm_day: number | null;
  outflow_mcm_day: number | null;
  outflow_change_mcm_day: number | null;
  observed_date: string;
}

export interface ReservoirsResponse {
  observed_date: string | null;
  total_pct: number | null;
  total_pct_change: number | null;
  coordinates_note: string;
  reservoirs: Reservoir[];
  freshness: Freshness | null;
}

export interface TideResponse {
  available: boolean;
  reason: string;
  stations: unknown[];
}

export interface CatchmentRainWindow {
  gauges: number;
  gauge_mean_mm: number | null;
  gauge_max_mm: number | null;
  area_weighted_mm: number | null;
  coverage: number;
}

export interface CatchmentRain {
  basis_th?: string;
  observed: { catchment_area_km2: number; windows: Record<"1h" | "3h" | "6h" | "24h", CatchmentRainWindow> } | null;
  forecast: {
    available: boolean;
    method: string | null;
    reason?: string | null;
    note?: string | null;
    windows?: Record<string, { mean_mm: number; max_mm: number; confidence: number; points: number }>;
  } | null;
}

export interface RelatedStation {
  station_code: string;
  name: string | null;
  river: string | null;
  river_distance_km: number | null;
  same_river_name: boolean | null;
  confidence: number | null;
  lag_hours: number | null;
}

export interface StationNetwork {
  source: string;
  catchment: {
    available: boolean;
    catchment_id?: string;
    thai_basin?: { name: string; share: number; stations: number } | null;
    sub_basin?: { area_km2: number } | null;
  };
  catchment_method: "reach_network" | "local_unit_only" | null;
  catchment_note: string;
  catchment_area_km2: number | null;
  river_link: { reach_method: string; osm_waterway_name: string | null; confidence: number | null; reach_distance_m: number | null } | null;
  relations: { upstream: RelatedStation[]; downstream: RelatedStation[] };
  relations_note: string;
  catchment_rain: CatchmentRain | null;
}
