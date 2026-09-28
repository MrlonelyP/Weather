"use client";

import { Eye } from "lucide-react";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { FreshnessTag } from "@/components/ui/FreshnessTag";
import { Panel } from "@/components/ui/Panel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { WaterStationsResponse } from "@/types/water";
import { fmtDistance, fmtNum } from "@/utils/format";
import { TrendCell } from "./TrendCell";

/** Compact "stations to watch" next to the map (highest system risk first). */
export function WatchListPanel({ data, onSelect }: { data: WaterStationsResponse | null; onSelect: (code: string) => void }) {
  const top = (data?.stations ?? []).filter((s) => s.status !== "NORMAL" && s.status !== "UNKNOWN").slice(0, 8);
  return (
    <Panel title="สถานีที่ต้องจับตา" icon={Eye}
      action={<a href="#water" className="text-[12px] text-primary hover:underline">ดูทั้งหมด</a>}
      footer={<FreshnessTag f={data?.freshness} />}>
      {!data ? <LoadingRows rows={5} /> : top.length === 0 ? (
        <EmptyState title="ยังไม่มีสถานีที่ต้องเฝ้าระวัง" detail="ทุกสถานีที่มีข้อมูลอยู่ในเกณฑ์ปกติตามการประเมินของระบบ" />
      ) : (
        <ul className="divide-y divide-line">
          {top.map((s) => (
            <li key={s.station_code}>
              <button onClick={() => onSelect(s.station_code)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-bg-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13.5px] text-ink">{s.name}</p>
                  <p className="truncate text-[11.5px] text-muted">{[s.river, s.province].filter(Boolean).join(" · ")}</p>
                </div>
                <div className="text-right">
                  <p className="text-[13px] tabular">{fmtNum(s.current_m, 2)} ม.</p>
                  <p className="text-[11px] text-muted">{s.distance_to_bank_m !== null && s.distance_to_bank_m <= 0 ? fmtDistance(s.distance_to_bank_m) : `เหลือ ${fmtDistance(s.distance_to_bank_m)}`}</p>
                </div>
                <div className="flex w-[86px] flex-col items-end gap-1">
                  <StatusBadge status={s.status} />
                  <TrendCell trend={s.trend} rate={s.rate_cm_per_h} />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
