import type { FreshnessStatus } from "@/types/common";
import type { Severity } from "@/types/warning";
import type { ImpactOutlook, Trend, WaterStatus } from "@/types/water";

/** System-computed water status. Colours: green / yellow / orange / red. */
export const WATER_STATUS: Record<WaterStatus, { label: string; color: string; rank: number }> = {
  CRITICAL: { label: "วิกฤต", color: "#ef4444", rank: 0 },
  WARNING: { label: "เสี่ยงสูง", color: "#fb923c", rank: 1 },
  WATCH: { label: "เฝ้าระวัง", color: "#facc15", rank: 2 },
  NORMAL: { label: "ปกติ", color: "#22c55e", rank: 3 },
  UNKNOWN: { label: "ไม่ทราบระดับตลิ่ง", color: "#64748b", rank: 4 },
};

export const TREND: Record<"rising" | "falling" | "steady" | "none", { label: string; color: string }> = {
  rising: { label: "สูงขึ้น", color: "#fb923c" },
  falling: { label: "ลดลง", color: "#38bdf8" },
  steady: { label: "ทรงตัว", color: "#94a3b8" },
  none: { label: "ข้อมูลไม่พอ", color: "#64748b" },
};
export const trendKey = (t: Trend) => (t ?? "none") as keyof typeof TREND;

export const FRESHNESS: Record<FreshnessStatus, { label: string; color: string }> = {
  LIVE: { label: "ล่าสุด", color: "#22c55e" },
  DELAYED: { label: "ล่าช้า", color: "#facc15" },
  STALE: { label: "ข้อมูลเก่า", color: "#fb923c" },
  OFFLINE: { label: "ออฟไลน์", color: "#ef4444" },
  NO_API_KEY: { label: "รอ API key", color: "#94a3b8" },
  NOT_CONFIGURED: { label: "ยังไม่ตั้งค่า", color: "#94a3b8" },
  DISABLED: { label: "ปิดอยู่", color: "#64748b" },
  NO_DATA: { label: "ยังไม่มีข้อมูล", color: "#94a3b8" },
  NOT_CONNECTED: { label: "ยังไม่เชื่อมต่อ", color: "#64748b" },
};

export const SEVERITY: Record<Severity, { label: string; color: string; bg: string }> = {
  critical: { label: "วิกฤต", color: "#ef4444", bg: "rgba(239,68,68,0.14)" },
  warning: { label: "เตือนภัย", color: "#fb923c", bg: "rgba(251,146,60,0.14)" },
  watch: { label: "เฝ้าระวัง", color: "#facc15", bg: "rgba(250,204,21,0.12)" },
  info: { label: "ข้อมูล", color: "#38bdf8", bg: "rgba(56,189,248,0.12)" },
};

export const IMPACT: Record<ImpactOutlook, { color: string }> = {
  likely_rise: { color: "#fb923c" },
  possible_rise: { color: "#facc15" },
  no_signal: { color: "#22c55e" },
  insufficient_data: { color: "#94a3b8" },
};
