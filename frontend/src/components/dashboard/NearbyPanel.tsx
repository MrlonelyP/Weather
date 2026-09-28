"use client";

import { MapPin, X } from "lucide-react";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { LocationAnalysis } from "@/types/location";
import type { NearbyResponse } from "@/types/water";
import { fmtDistance, fmtNum } from "@/utils/format";
import { ImpactBlock } from "./ImpactBlock";
import { TerrainBlock } from "./TerrainBlock";
import { TrendCell } from "./TrendCell";

/** Optional: what matters around the user's location. */
export function NearbyPanel({ data, analysis, onSelect, onClose }: {
  data: NearbyResponse | null;
  analysis: LocationAnalysis | null;
  onSelect: (code: string) => void;
  onClose: () => void;
}) {
  return (
    <Panel title="ใกล้ตำแหน่งของคุณ" icon={MapPin}
      action={<button onClick={onClose} className="rounded p-1 text-muted hover:text-ink" aria-label="ปิด"><X className="size-4" /></button>}>
      {!data ? <LoadingRows rows={4} /> : (
        <div className="space-y-3 p-4">
          {data.stations.length === 0 ? (
            <EmptyState title={`ไม่มีสถานีวัดน้ำในรัศมี ${data.radius_km} กม.`} />
          ) : (
            <ul className="space-y-1.5">
              {data.stations.slice(0, 4).map((s) => (
                <li key={s.station_code}>
                  <button onClick={() => onSelect(s.station_code)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-bg-2">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px]">{s.name}</span>
                      <span className="block text-[11px] text-muted">{s.river ?? ""} · ห่าง {fmtNum(s.distance_km, 1)} กม. · เหลือ {fmtDistance(s.distance_to_bank_m)}</span>
                    </span>
                    <span className="flex flex-col items-end gap-0.5"><StatusBadge status={s.status} /><TrendCell trend={s.trend} rate={s.rate_cm_per_h} /></span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {data.rivers.length > 0 && <p className="text-[12px] text-ink-2">แม่น้ำ/คลองที่เกี่ยวข้อง: {data.rivers.map((r) => r.name).join(", ")}</p>}
          {data.rain_gauges.length > 0 && (
            <p className="text-[12px] text-ink-2">ฝน 24 ชม. ใกล้เคียง: {data.rain_gauges.slice(0, 3).map((g) => `${g.name} ${fmtNum(g.rain_24h_mm, 1)} มม.`).join(" · ")}</p>
          )}
          <ImpactBlock impact={data.impact} />
          {analysis && <TerrainBlock data={analysis} />}
        </div>
      )}
    </Panel>
  );
}
