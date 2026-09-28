import type { Freshness } from "./common";

export interface FloodExtentResponse {
  available: boolean;
  reason: string | null;
  geojson: GeoJSON.FeatureCollection;
  freshness: (Freshness | null)[];
}

/** Experimental, system-computed - never an official warning. */
export interface FloodRiskResponse {
  available: boolean;
  reason?: string;
  disclaimer?: string;
  areas: unknown[];
}
