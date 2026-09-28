"use client";

import { CloudRain, Landmark, MapPin, Search, Waves, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { searchService } from "@/services/search";
import type { SearchArea, SearchResponse } from "@/types/search";
import { fmtNum } from "@/utils/format";

export interface SearchActions {
  onArea: (a: SearchArea) => void;
  onStation: (code: string, lat: number | null, lon: number | null) => void;
  onRiver: (name: string) => void;
  onReservoir: () => void;
  onPoint: (lat: number, lon: number) => void;
}

/** Search stations, canals/rivers, dams, districts and provinces - no location needed. */
export function SearchBox(actions: SearchActions) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setRes(null);
      return;
    }
    const ctrl = new AbortController();
    const t = window.setTimeout(() => {
      setLoading(true);
      searchService.query(q.trim(), ctrl.signal).then(setRes).catch(() => undefined).finally(() => setLoading(false));
    }, 300);
    return () => {
      window.clearTimeout(t);
      ctrl.abort();
    };
  }, [q]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const pick = (fn: () => void) => {
    fn();
    setOpen(false);
  };
  const empty = res && !res.areas.length && !res.stations.length && !res.rivers.length && !res.reservoirs.length;

  return (
    <div ref={boxRef} className="relative w-full max-w-[640px]">
      <label className="flex h-11 items-center gap-2.5 rounded-xl border border-line-strong bg-bg-1 px-3.5 focus-within:border-primary">
        <Search className="size-[18px] shrink-0 text-muted" aria-hidden />
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder="ค้นหาพื้นที่ จังหวัด อำเภอ สถานี แม่น้ำ คลอง หรือเขื่อน"
          className="h-full min-w-0 flex-1 bg-transparent text-[14px] text-ink placeholder:text-muted focus:outline-none"
          aria-label="ค้นหา"
        />
        {q && (
          <button onClick={() => { setQ(""); setRes(null); }} aria-label="ล้างคำค้น" className="text-muted hover:text-ink">
            <X className="size-4" />
          </button>
        )}
      </label>

      {open && q.trim().length >= 2 && (
        <div className="scroll-thin absolute top-12 right-0 left-0 z-50 max-h-[70vh] overflow-y-auto rounded-xl border border-line-strong bg-bg-1 p-2 shadow-2xl">
          {loading && !res && <p className="px-3 py-2 text-[13px] text-muted">กำลังค้นหา…</p>}
          {empty && <p className="px-3 py-2 text-[13px] text-muted">ไม่พบผลลัพธ์สำหรับ “{q}”</p>}
          {res && (
            <div className="space-y-2">
              {res.areas.length > 0 && (
                <Group title="พื้นที่">
                  {res.areas.slice(0, 5).map((a) => (
                    <Row key={a.type + a.name + a.province} icon={MapPin} onClick={() => pick(() => actions.onArea(a))}
                      title={`${a.type === "district" ? "อำเภอ/เขต" : "จังหวัด"} ${a.name}`}
                      sub={`${a.province ?? ""} · สถานีวัดน้ำ ${a.water_stations} · สถานีวัดฝน ${a.rain_gauges}`} />
                  ))}
                </Group>
              )}
              {res.stations.length > 0 && (
                <Group title={res.stations_note ? "สถานีวัดน้ำใกล้เคียง" : "สถานีวัดน้ำ"} note={res.stations_note}>
                  {res.stations.slice(0, 8).map((s) => (
                    <Row key={s.station_code} icon={Waves}
                      onClick={() => pick(() => actions.onStation(s.station_code, s.lat, s.lon))}
                      title={s.name ?? s.station_code}
                      sub={[s.river, s.amphoe, s.province, s.distance_km !== undefined ? `ห่าง ${fmtNum(s.distance_km, 1)} กม.` : null].filter(Boolean).join(" · ")}
                      right={<StatusBadge status={s.status} />} />
                  ))}
                </Group>
              )}
              {res.rivers.length > 0 && (
                <Group title="แม่น้ำ / คลองที่เกี่ยวข้อง">
                  {res.rivers.slice(0, 6).map((r) => (
                    <Row key={r.name} icon={Waves} onClick={() => pick(() => actions.onRiver(r.name))} title={r.name} sub={`สถานีวัดน้ำ ${r.stations} แห่ง`} />
                  ))}
                </Group>
              )}
              {res.reservoirs.length > 0 && (
                <Group title="เขื่อน">
                  {res.reservoirs.map((d) => (
                    <Row key={d.reservoir_code} icon={Landmark} onClick={() => pick(actions.onReservoir)} title={d.name ?? d.reservoir_code} sub={d.region ?? ""} />
                  ))}
                </Group>
              )}
              {res.rain_gauges_nearby.length > 0 && (
                <Group title="สถานีวัดฝนใกล้เคียง">
                  {res.rain_gauges_nearby.slice(0, 5).map((g) => (
                    <Row key={g.station_code} icon={CloudRain}
                      onClick={() => g.lat !== null && g.lon !== null && pick(() => actions.onPoint(g.lat as number, g.lon as number))}
                      title={g.name ?? g.station_code}
                      sub={`ฝน 24 ชม. ${fmtNum(g.rain_24h_mm, 1)} มม. · ห่าง ${fmtNum(g.distance_km, 1)} กม.`} />
                  ))}
                </Group>
              )}
              {!res.flood_extent_nearby.available && (res.areas.length > 0 || res.stations.length > 0) && (
                <p className="px-3 pb-1 text-[11.5px] text-muted">พื้นที่น้ำท่วมใกล้เคียง: {res.flood_extent_nearby.reason}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Group({ title, note, children }: { title: string; note?: string | null; children: React.ReactNode }) {
  return (
    <div>
      <p className="px-3 pt-1 text-[11.5px] font-semibold tracking-wide text-muted">{title}</p>
      {note && <p className="px-3 pb-1 text-[11px] text-watch">{note}</p>}
      <ul>{children}</ul>
    </div>
  );
}

function Row({ icon: Icon, title, sub, right, onClick }: {
  icon: typeof Waves; title: string; sub?: string; right?: React.ReactNode; onClick: () => void;
}) {
  return (
    <li>
      <button onClick={onClick} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-bg-2">
        <Icon className="size-4 shrink-0 text-primary" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] text-ink">{title}</span>
          {sub && <span className="block truncate text-[11.5px] text-muted">{sub}</span>}
        </span>
        {right}
      </button>
    </li>
  );
}
