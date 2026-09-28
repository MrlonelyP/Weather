"use client";

import { GitBranch, Route } from "lucide-react";
import type { LocationAnalysis } from "@/types/location";
import type { CatchmentRain, RelatedStation, StationNetwork } from "@/types/water";
import { fmtNum } from "@/utils/format";

const pct = (v: number | null | undefined) => (v == null ? "--" : `${Math.round(v * 100)}%`);

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2 py-1 text-[12.5px]">
      <span className="text-muted">{label}</span>
      <span className="min-w-0 text-ink-2">{children}</span>
    </div>
  );
}

/** Rain over the catchment: first window with reporting gauges; never fills gaps. */
function CatchmentRainLine({ rain }: { rain: CatchmentRain | null | undefined }) {
  const obs = rain?.observed?.windows;
  const w = obs && (["3h", "1h", "6h", "24h"] as const).find((k) => obs[k]?.gauges);
  const f6 = rain?.forecast?.available ? rain.forecast.windows?.rain_6h : undefined;
  return (
    <>
      <Row label="ฝนพื้นที่รับน้ำ">
        {w && obs ? `${w.replace("h", " ชม.")}: เฉลี่ย ${fmtNum(obs[w].gauge_mean_mm, 1)} · สูงสุด ${fmtNum(obs[w].gauge_max_mm, 1)} มม. (${obs[w].gauges} สถานี, ครอบคลุม ${pct(obs[w].coverage)})`
          : "ไม่มีค่าฝนล่าสุดจากสถานีวัดฝนในพื้นที่รับน้ำ"}
      </Row>
      <Row label="ฝนคาดการณ์ 6 ชม.">
        {f6 ? `~${fmtNum(f6.mean_mm, 1)} มม. (ความมั่นใจ ${pct(f6.confidence)})${rain?.forecast?.method === "proxy_nearest_point" ? " · จุดพยากรณ์ใกล้เคียง" : ""}`
          : rain?.forecast?.reason ?? "ไม่มีข้อมูล"}
      </Row>
    </>
  );
}

/** Location: drainage area, relevant waterway / station and how each was chosen. */
export function LocationDrainageBlock({ data }: { data: LocationAnalysis }) {
  const flow = data.drainage.local_flow;
  const catchment = data.drainage.catchment;
  const ww = data.relevant_waterway;
  const st = data.relevant_station;
  return (
    <div className="rounded-xl border p-3.5" style={{ borderColor: "var(--color-line-strong)" }}>
      <p className="mb-1 flex items-center gap-2 text-[12px] font-semibold text-ink-2">
        <Route className="size-4 text-primary" aria-hidden />การระบายน้ำของจุดนี้
      </p>
      <Row label="พื้นที่ระบายน้ำ">
        {catchment.available ? `${catchment.thai_basin?.name ?? "ลุ่มน้ำไม่ทราบชื่อ"} · ${catchment.catchment_id}` : "ไม่มีข้อมูลลุ่มน้ำ"}
      </Row>
      <Row label="ทิศทางน้ำ">
        {flow.reliable ? `ไปทาง${flow.flow_direction_th} (ความมั่นใจ ${pct(flow.confidence)})` : <span className="text-watch">{flow.message_th ?? "ไม่มีข้อมูล"}</span>}
      </Row>
      <Row label="ทางน้ำที่เกี่ยวข้อง">
        {ww.selected ? (ww.selected.name ?? `${ww.selected.waterway_type_th ?? "ทางน้ำ"} (ไม่มีชื่อ)`) : "--"}
        <span className="block text-[11px] text-muted">เหตุผล: {ww.reason_th}</span>
      </Row>
      <Row label="สถานีที่ใช้ประเมิน">
        {st.selected ? `${st.selected.name ?? st.selected.station_code}${st.selected.river ? ` (${st.selected.river})` : ""}` : "--"}
        <span className="block text-[11px] text-muted">เหตุผล: {st.reason_th} · ความมั่นใจ {pct(st.confidence)}</span>
      </Row>
      <CatchmentRainLine rain={data.rain.catchment} />
      <p className="mt-1.5 text-[11px] text-muted">ทิศทางน้ำคำนวณจากภูมิประเทศเท่านั้น ไม่รวมท่อระบายน้ำ เครื่องสูบน้ำ และประตูระบายน้ำ</p>
    </div>
  );
}

function StationList({ title, items }: { title: string; items: RelatedStation[] }) {
  if (!items.length) return <Row label={title}>ไม่พบในเครือข่ายแม่น้ำ</Row>;
  return (
    <Row label={title}>
      <ul className="space-y-0.5">
        {items.slice(0, 3).map((s) => (
          <li key={s.station_code}>
            {s.name ?? s.station_code} <span className="tabular text-muted">· {s.river_distance_km != null && s.river_distance_km < 1 ? "ไม่ถึง 1" : fmtNum(s.river_distance_km, 0)} กม. ตามลำน้ำ{s.same_river_name ? "" : " · ต่างชื่อลำน้ำ"}</span>
          </li>
        ))}
      </ul>
    </Row>
  );
}

const REACH_TH: Record<string, string> = {
  name_and_distance: "ชื่อลำน้ำตรงกับ OSM และอยู่ใกล้",
  distance_only: "เลือกจากระยะทาง (ไม่พบชื่อลำน้ำตรงกัน)",
  none: "ลำน้ำขนาดเล็ก ไม่อยู่ในเครือข่าย HydroRIVERS",
};

/** Station: catchment, river-network link, upstream / downstream stations, catchment rain. */
export function StationNetworkBlock({ net }: { net: StationNetwork | null }) {
  if (!net) return null;
  return (
    <div className="rounded-xl border border-line p-3">
      <p className="mb-1 flex items-center gap-2 text-[13px] font-semibold">
        <GitBranch className="size-4 text-primary" aria-hidden />พื้นที่รับน้ำและลำน้ำ
      </p>
      <Row label="พื้นที่รับน้ำ">
        {net.catchment.thai_basin?.name ?? "--"}
        {net.catchment_area_km2 ? ` · ~${fmtNum(net.catchment_area_km2, 0)} ตร.กม.` : ""}
        <span className="block text-[11px] text-muted">{net.catchment_note}</span>
      </Row>
      <Row label="ผูกกับลำน้ำ">
        {net.river_link ? REACH_TH[net.river_link.reach_method] ?? net.river_link.reach_method : "--"}
        {net.river_link?.confidence != null && <span className="text-muted"> · ความมั่นใจ {pct(net.river_link.confidence)}</span>}
      </Row>
      <StationList title="สถานีต้นน้ำ" items={net.relations.upstream} />
      <StationList title="สถานีปลายน้ำ" items={net.relations.downstream} />
      <CatchmentRainLine rain={net.catchment_rain} />
      <p className="mt-1 text-[11px] text-muted">{net.relations_note}</p>
    </div>
  );
}
