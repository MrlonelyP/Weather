import type { ISODate } from "./common";
import type { RainGaugeNear, WaterStation } from "./water";

export interface SearchArea {
  type: "district" | "province";
  name: string;
  province: string | null;
  water_stations: number;
  rain_gauges: number;
  center: { lat: number; lon: number } | null;
  bbox: [number, number, number, number] | null;
}

export interface SearchResponse {
  query: string;
  generated_at: ISODate;
  center: { lat: number; lon: number } | null;
  areas: SearchArea[];
  stations: WaterStation[];
  stations_note: string | null;
  rivers: { name: string; stations: number }[];
  reservoirs: { reservoir_code: string; name: string | null; region: string | null; lat: number | null; lon: number | null }[];
  weather_stations: { station_code: string; name: string | null; lat: number | null; lon: number | null }[];
  rain_gauges_nearby: RainGaugeNear[];
  flood_extent_nearby: { available: boolean; reason: string };
}
