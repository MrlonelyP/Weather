import type { Freshness, ISODate } from "./common";

export type Severity = "critical" | "warning" | "watch" | "info";

export interface OfficialWarning {
  id: number;
  agency_code: string;
  agency_name: string;
  official: true;
  type: string | null;
  type_label: string;
  severity: Severity;
  severity_basis: string;
  title: string;
  area_text: string | null;
  area_geojson: GeoJSON.Polygon | null;
  issued_at: ISODate | null;
  valid_from: ISODate | null;
  valid_to: ISODate | null;
  active: boolean;
  bulletin_header: string | null;
  body: string;
}

export interface WarningsResponse {
  warnings: OfficialWarning[];
  active_public: number;
  active_aviation: number;
  note: string;
  freshness: Freshness | null;
}
