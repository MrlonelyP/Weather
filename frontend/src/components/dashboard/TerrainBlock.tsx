"use client";

import { ChevronDown, Mountain, Waves } from "lucide-react";
import type { LocationAnalysis, TerrainSignal } from "@/types/location";
import { fmtNum } from "@/utils/format";

const SIGNAL_COLOR: Record<TerrainSignal, string> = {
  may_collect_water: "var(--color-warning)",
  neutral: "var(--color-ink-2)",
  less_likely_to_collect: "var(--color-normal)",
  uncertain: "var(--color-watch)",
  unknown: "var(--color-unknown)",
};
const RELIABILITY_TH: Record<string, string> = { none: "ไม่มีข้อมูล", low: "ต่ำ", medium: "ปานกลาง" };

/** Terrain + nearest waterway for one point. Every line comes from /api/location/analyze. */
export function TerrainBlock({ data }: { data: LocationAnalysis }) {
  const t = data.terrain;
  const sig = data.terrain_signal;
  const color = SIGNAL_COLOR[sig.signal];
  const primary = t.datasets[t.primary_dataset];
  const ww = data.waterways;
  return (
    <div className="space-y-2.5 rounded-xl border p-3.5" style={{ borderColor: "var(--color-line-strong)" }}>
      <p className="flex items-center gap-2 text-[12px] font-semibold text-ink-2">
        <Mountain className="size-4 text-primary" aria-hidden />ภูมิประเทศของจุดนี้
      </p>
      {!t.available ? (
        <p className="text-[13px] text-muted">{sig.label_th}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-[family-name:var(--font-display)] text-[16px] font-semibold" style={{ color }}>{t.terrain_position_th}</span>
            <span className="tabular text-[12px] text-muted">พื้นสูงประมาณ {fmtNum(t.elevation_m, 1)} ม. (EGM2008)</span>
          </div>
          <p className="text-[13px] text-ink-2">{sig.label_th}</p>
          {sig.reasons.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-2">
              {sig.reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
          <p className="text-[11px] text-muted">
            ความน่าเชื่อถือ: {RELIABILITY_TH[t.reliability.level] ?? t.reliability.level} · {t.reliability.reasons.join(" · ")}
          </p>
        </>
      )}
      {ww.available && ww.nearest && (
        <div className="border-t border-line pt-2.5">
          <p className="flex items-center gap-2 text-[12.5px] text-ink">
            <Waves className="size-4 shrink-0 text-rain" aria-hidden />
            <span className="min-w-0">
              ทางน้ำใกล้ที่สุด: {ww.nearest.name ?? `${ww.nearest.waterway_type_th} (ไม่มีชื่อใน OSM)`}
              <span className="tabular text-muted"> · {ww.nearest.distance_m.toLocaleString("th-TH")} ม.</span>
            </span>
          </p>
          {ww.nearest_named && ww.nearest_named.osm_id !== ww.nearest.osm_id && (
            <p className="mt-0.5 pl-6 text-[12px] text-ink-2">
              ที่มีชื่อใกล้ที่สุด: {ww.nearest_named.name} · {ww.nearest_named.distance_m.toLocaleString("th-TH")} ม.
            </p>
          )}
          <p className="mt-0.5 pl-6 text-[11px] text-muted">{ww.selection_note}</p>
        </div>
      )}
      {t.available && (
        <details className="group text-[11.5px] text-muted">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-ink-2 hover:text-ink">
            <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden />ที่มาและข้อจำกัด
          </summary>
          <div className="mt-1.5 space-y-1.5">
            <table className="tabular w-full text-left">
              <thead><tr className="text-muted"><th className="font-normal">DEM</th><th className="font-normal">ความสูง</th><th className="font-normal">ต่างจากรอบ ๆ 500 ม.</th></tr></thead>
              <tbody>
                {Object.values(t.datasets).map((d) => (
                  <tr key={d.dataset.code} className="text-ink-2">
                    <td>{d.dataset.name} ({d.dataset.surface}){d.dataset.code === t.primary_dataset ? " ★" : ""}</td>
                    <td>{d.available ? `${fmtNum(d.elevation_m, 1)} ม.` : "—"}</td>
                    <td>{d.available ? `${fmtNum(d.relative_elevation?.["500"]?.relative_m, 1)} ม.` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {t.comparison.note && <p>{t.comparison.note}</p>}
            <ul className="list-disc space-y-0.5 pl-4">{t.limits.map((l) => <li key={l}>{l}</li>)}</ul>
            {primary && <p>{primary.dataset.surface_note_th}</p>}
            <p>{data.sources.map((s) => s.attribution).join(" · ")}</p>
          </div>
        </details>
      )}
      <p className="text-[11px] text-muted">{data.flood_context.disclaimer}</p>
    </div>
  );
}
