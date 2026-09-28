import type { CatchmentRain, ForecastImpact } from "./water";

export type TerrainPosition = "LOW_AREA" | "NORMAL" | "HIGH_AREA" | "MIXED" | "UNKNOWN";
export type TerrainSignal = "may_collect_water" | "neutral" | "less_likely_to_collect" | "uncertain" | "unknown";

export interface DemDatasetMeta {
  code: string;
  name: string;
  surface: "DSM" | "DTM";
  surface_note_th: string;
  vertical_datum: string;
  license: string;
  commercial_use: boolean;
  attribution: string;
}

export interface RelativeElevation {
  radius_m: number;
  relative_m: number | null;
  percentile_rank?: number | null;
  surrounding_median_m?: number | null;
  position: TerrainPosition;
  within_noise?: boolean;
}

export interface TerrainDatasetResult {
  available: boolean;
  reason?: string;
  dataset: DemDatasetMeta;
  elevation_m?: number;
  terrain_position?: TerrainPosition;
  relative_elevation?: Record<string, RelativeElevation>;
  local_depression?: { possible_local_depression: boolean | null; depth_m: number | null; area_rai?: number | null };
}

export interface TerrainResult {
  available: boolean;
  primary_dataset: string;
  elevation_m: number | null;
  terrain_position: TerrainPosition;
  terrain_position_th: string | null;
  possible_local_depression: boolean | null;
  datasets: Record<string, TerrainDatasetResult>;
  comparison: { elevation_diff_m?: number; position_agree?: boolean; note?: string | null };
  reliability: { level: "none" | "low" | "medium"; reasons: string[]; note?: string };
  limits: string[];
}

export interface WaterwayItem {
  osm_id: number;
  waterway_type: string;
  waterway_type_th: string;
  name: string | null;
  distance_m: number;
  osm_url: string;
}

export interface WaterwaysResult {
  available: boolean;
  reason?: string;
  selection_method: string;
  selection_note: string;
  attribution: string;
  nearest?: WaterwayItem | null;
  nearest_named?: WaterwayItem | null;
  items?: WaterwayItem[];
}

export interface DrainageResult {
  local_flow: {
    available: boolean;
    reliable?: boolean;
    flow_direction?: string | null;
    flow_direction_th?: string | null;
    confidence: number;
    message_th?: string | null;
    path_length_m?: number;
    reached?: { type: string; name?: string | null; waterway_type_th?: string };
    limitations: string[];
  };
  catchment: {
    available: boolean;
    catchment_id?: string;
    thai_basin?: { name: string; share: number } | null;
    confidence: number;
    confidence_note?: string;
  };
}

export interface WaterwayChoice {
  selection_method: "drainage_based" | "catchment_based" | "distance_based";
  name: string | null;
  waterway_type_th?: string;
  confidence: number | null;
  usable: boolean;
  note?: string | null;
}

export interface RelevantStation {
  selected: { station_code: string; name: string | null; river: string | null; distance_km: number | null } | null;
  selection_method: "same_waterway_and_catchment" | "same_waterway" | "same_catchment" | "nearby" | "none";
  reason_th: string;
  confidence: number;
}

export interface LocationAnalysis {
  generated_at: string;
  point: { lat: number; lon: number; in_thailand: boolean };
  summary_th: string[];
  terrain: TerrainResult;
  drainage: DrainageResult;
  relevant_waterway: { selected: WaterwayChoice | null; selection_method: string; reason_th: string; candidates: WaterwayChoice[] };
  relevant_station: RelevantStation;
  rain: { catchment: CatchmentRain | null };
  terrain_signal: { signal: TerrainSignal; label_th: string; reasons: string[]; reliability: string | null; use: string };
  waterways: WaterwaysResult;
  impact: ForecastImpact;
  flood_context: { water: string[]; rain: string[]; terrain: string[]; disclaimer: string };
  sources: { what: string; name: string; license: string | null; attribution: string }[];
}
