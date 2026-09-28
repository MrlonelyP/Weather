"use client";

import { Segmented } from "@/components/ui/Segmented";

export type MapTime = "now" | "1h" | "3h" | "6h" | "24h";
export type MapMode = "observed" | "forecast";

const TIMES: { value: MapTime; label: string }[] = [
  { value: "now", label: "ปัจจุบัน" },
  { value: "1h", label: "1 ชม." },
  { value: "3h", label: "3 ชม." },
  { value: "6h", label: "6 ชม." },
  { value: "24h", label: "24 ชม." },
];

export function MapTimeSelector({ time, mode, onTime, onMode }: {
  time: MapTime;
  mode: MapMode;
  onTime: (t: MapTime) => void;
  onMode: (m: MapMode) => void;
}) {
  return (
    <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-xl border border-line-strong bg-bg-1/92 p-1.5 shadow-xl backdrop-blur">
      <Segmented
        ariaLabel="ข้อมูลฝนที่ผ่านมาหรือคาดการณ์"
        value={mode}
        onChange={onMode}
        options={[{ value: "observed", label: "ตรวจวัด" }, { value: "forecast", label: "คาดการณ์" }]}
      />
      <Segmented ariaLabel="ช่วงเวลา" value={time} onChange={onTime} options={TIMES} />
    </div>
  );
}
