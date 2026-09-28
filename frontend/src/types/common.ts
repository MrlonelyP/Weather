/** ISO-8601 timestamp string as returned by the FastAPI backend (UTC). */
export type ISODate = string;

export type FreshnessStatus =
  | "LIVE"
  | "DELAYED"
  | "STALE"
  | "OFFLINE"
  | "NO_API_KEY"
  | "NOT_CONFIGURED"
  | "DISABLED"
  | "NO_DATA"
  | "NOT_CONNECTED";

/** How new a data block is. Attached by the backend to every block. */
export interface Freshness {
  job: string;
  source: string;
  status: FreshnessStatus;
  basis: "data" | "model_run" | "data_date" | "fetch";
  source_time: ISODate | null;
  fetched_at: ISODate | null;
  age_minutes: number | null;
  age_text: string | null;
  expected_update: string | null;
  note: string | null;
}

/** A block the backend cannot provide yet (no source / no key). */
export interface Unavailable {
  available: false;
  reason: string;
}
