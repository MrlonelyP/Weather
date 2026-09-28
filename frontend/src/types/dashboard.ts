import type { Freshness, FreshnessStatus, ISODate } from "./common";

interface Metric {
  label: string;
  value: number | null;
  unit: string;
  change?: number | null;
  change_basis?: string;
  freshness?: Freshness | null;
}

export interface DashboardSummary {
  generated_at: ISODate;
  rain_24h: Metric & { station: string | null; province: string | null; stations_reporting: number };
  critical_water: Metric & { stations_evaluated: number; status_basis: string };
  reservoirs: Metric & { count: number; observed_date: string | null };
  flood_risk: Metric & { available: boolean; reason: string };
  warnings: { active_public: number; active_aviation: number; total_48h: number; freshness: Freshness | null };
}

export interface SourceHealth {
  source: string;
  label: string;
  status: FreshnessStatus;
  source_time: ISODate | null;
  fetched_at: ISODate | null;
  age_minutes: number | null;
  age_text: string | null;
  jobs: Freshness[];
}

export interface SourcesHealthResponse {
  generated_at: ISODate;
  sources: SourceHealth[];
}
