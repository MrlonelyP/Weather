"use client";

import { CloudRain } from "lucide-react";
import { RainComparisonChart } from "@/components/charts/RainComparisonChart";
import { LoadingRows } from "@/components/ui/EmptyState";
import { FreshnessTag } from "@/components/ui/FreshnessTag";
import { Panel } from "@/components/ui/Panel";
import type { NearbyResponse } from "@/types/water";
import type { LocationRef, RainComparison } from "@/types/weather";
import { fmtDayTime, fmtNum } from "@/utils/format";
import { ImpactBlock } from "./ImpactBlock";
import { LocationTabs } from "./LocationTabs";

const WINDOWS = ["1h", "3h", "6h", "12h", "24h", "48h"];

/** Rain now (observed) vs forecast (ECMWF/GFS/JMA + our consensus), then what it may mean for the water. */
export function RainPanel({ locations, location, onLocation, data, nearby }: {
  locations: LocationRef[];
  location: string;
  onLocation: (c: string) => void;
  data: RainComparison | null;
  nearby: NearbyResponse | null;
}) {
  const obsLast = data?.observed.series.at(-1);
  return (
    <Panel title="ฝน: ตรวจวัดจริง เทียบ คาดการณ์" icon={CloudRain}
      action={<LocationTabs locations={locations} value={location} onChange={onLocation} />}
      footer={<div className="flex flex-wrap gap-x-4 gap-y-1"><span className="text-[11.5px] text-muted">ตรวจวัด:</span><FreshnessTag f={data?.freshness.observed} compact /><span className="text-[11.5px] text-muted">คาดการณ์:</span><FreshnessTag f={data?.freshness.forecast[0]} compact /></div>}>
      {!data ? <LoadingRows rows={6} /> : (
        <div className="space-y-3 p-4">
          <RainComparisonChart data={data} />
          <p className="text-[11.5px] text-muted">
            แท่ง = ฝนเฉลี่ยจากสถานีวัดฝน {data.observed.stations} แห่งในรัศมี {data.observed.radius_km} กม. ({data.observed.note})
            {obsLast ? ` · ล่าสุด ${fmtNum(obsLast.mean_mm, 1)} มม./ชม. เมื่อ ${fmtDayTime(obsLast.time)}` : ""}
            {" · "}เส้น = โมเดลรอบล่าสุด {data.model_runs.map((r) => `${r.model} ${fmtDayTime(r.model_run_time)}`).join(", ")}
          </p>
          <div>
            <p className="mb-1.5 text-[12.5px] font-semibold text-ink-2">ฝนคาดการณ์สะสมข้างหน้า (พยากรณ์ของระบบ)</p>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
              {WINDOWS.map((w) => {
                const win = data.windows[`rain_${w}`];
                return (
                  <div key={w} className="rounded-lg border border-line bg-bg-1 px-2.5 py-2">
                    <p className="text-[11px] text-muted">{w.replace("h", " ชม.")}</p>
                    <p className="text-[16px] font-semibold tabular">{fmtNum(win?.consensus, 1)}<span className="ml-0.5 text-[11px] text-muted">มม.</span></p>
                    <p className="text-[10.5px] text-muted tabular">
                      {win?.min !== null && win?.min !== undefined ? `${fmtNum(win.min, 1)}–${fmtNum(win.max, 1)}` : "--"}
                      {win?.confidence !== null && win?.confidence !== undefined ? ` · มั่นใจ ${Math.round(win.confidence * 100)}%` : ""}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
          <ImpactBlock impact={nearby?.impact} title={`ผลต่อระดับน้ำบริเวณ${locations.find((l) => l.code === location)?.name_th ?? ""}`} />
        </div>
      )}
    </Panel>
  );
}
