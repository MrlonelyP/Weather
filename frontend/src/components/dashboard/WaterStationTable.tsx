"use client";

import { ArrowUpDown, Search, Waves } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { FreshnessTag } from "@/components/ui/FreshnessTag";
import { Panel } from "@/components/ui/Panel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { WaterFilters, WaterStation, WaterStationsResponse, WaterStatus } from "@/types/water";
import { fmtDistance, fmtNum, fmtTime } from "@/utils/format";
import { WATER_STATUS } from "@/utils/status";
import { TrendCell } from "./TrendCell";

export interface TableFilter {
  province: string;
  basin: string;
  river: string;
  statuses: WaterStatus[];
  q: string;
}
export const EMPTY_FILTER: TableFilter = { province: "", basin: "", river: "", statuses: [], q: "" };

type SortKey = "risk" | "level" | "remaining" | "trend";

const sorters: Record<SortKey, (a: WaterStation, b: WaterStation) => number> = {
  risk: (a, b) => WATER_STATUS[a.status].rank - WATER_STATUS[b.status].rank || (a.distance_to_bank_m ?? 99) - (b.distance_to_bank_m ?? 99),
  level: (a, b) => (b.current_m ?? -99) - (a.current_m ?? -99),
  remaining: (a, b) => (a.distance_to_bank_m ?? 99) - (b.distance_to_bank_m ?? 99),
  trend: (a, b) => (b.rate_cm_per_h ?? -99) - (a.rate_cm_per_h ?? -99),
};

/** Watch list: every station with filters (province, basin, river, status, search) and sorting. */
export function WaterStationTable({ data, filters, filter, onFilter, onSelect }: {
  data: WaterStationsResponse | null;
  filters: WaterFilters | null;
  filter: TableFilter;
  onFilter: (f: TableFilter) => void;
  onSelect: (code: string) => void;
}) {
  const [sort, setSort] = useState<SortKey>("risk");
  const [limit, setLimit] = useState(25);

  const rows = useMemo(() => {
    const q = filter.q.trim().toLowerCase();
    return (data?.stations ?? [])
      .filter((s) =>
        (!filter.province || s.province_code === filter.province) &&
        (!filter.basin || s.basin === filter.basin) &&
        (!filter.river || s.river === filter.river) &&
        (filter.statuses.length === 0 || filter.statuses.includes(s.status)) &&
        (!q || [s.name, s.river, s.basin, s.province, s.amphoe].some((v) => v?.toLowerCase().includes(q))))
      .sort(sorters[sort]);
  }, [data, filter, sort]);

  const set = (patch: Partial<TableFilter>) => {
    setLimit(25);
    onFilter({ ...filter, ...patch });
  };
  const toggleStatus = (st: WaterStatus) =>
    set({ statuses: filter.statuses.includes(st) ? filter.statuses.filter((x) => x !== st) : [...filter.statuses, st] });

  const Th = ({ k, children, className = "" }: { k?: SortKey; children: React.ReactNode; className?: string }) => (
    <th className={`px-3 py-2 text-left text-[11.5px] font-semibold whitespace-nowrap text-muted ${className}`}>
      {k ? (
        <button onClick={() => setSort(k)} className={`inline-flex items-center gap-1 ${sort === k ? "text-primary" : ""}`}>
          {children}<ArrowUpDown className="size-3" />
        </button>
      ) : children}
    </th>
  );

  return (
    <Panel title="ระดับน้ำ: สถานีที่ต้องจับตา (ทั่วประเทศ)" icon={Waves}
      action={<span className="text-[12px] text-muted">{data ? `${rows.length} / ${data.stations.length} สถานี` : ""}</span>}
      footer={<div className="flex flex-wrap items-center justify-between gap-2"><FreshnessTag f={data?.freshness} /><span className="text-[11px] text-muted">สถานะ = ระบบประเมินจากระยะถึงตลิ่งและอัตราการขึ้น ไม่ใช่ประกาศทางราชการ</span></div>}>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        <label className="flex h-9 min-w-[200px] flex-1 items-center gap-2 rounded-lg border border-line bg-bg-1 px-2.5">
          <Search className="size-4 text-muted" aria-hidden />
          <input value={filter.q} onChange={(e) => set({ q: e.target.value })} placeholder="ค้นหาสถานี แม่น้ำ คลอง อำเภอ"
            className="min-w-0 flex-1 bg-transparent text-[13px] focus:outline-none" aria-label="ค้นหาในตาราง" />
        </label>
        <Select label="จังหวัด" value={filter.province} onChange={(v) => set({ province: v })}
          options={(filters?.provinces ?? []).map((p) => ({ value: p.value, label: `${p.label ?? p.value} (${p.count})` }))} />
        <Select label="ลุ่มน้ำ" value={filter.basin} onChange={(v) => set({ basin: v })}
          options={(filters?.basins ?? []).map((p) => ({ value: p.value, label: `${p.value} (${p.count})` }))} />
        <Select label="แม่น้ำ/คลอง" value={filter.river} onChange={(v) => set({ river: v })}
          options={(filters?.rivers ?? []).map((p) => ({ value: p.value, label: `${p.value} (${p.count})` }))} />
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="กรองตามสถานะ">
          {(["CRITICAL", "WARNING", "WATCH", "NORMAL"] as const).map((st) => {
            const on = filter.statuses.includes(st);
            const c = WATER_STATUS[st].color;
            return (
              <button key={st} onClick={() => toggleStatus(st)} aria-pressed={on}
                className="rounded-full px-2.5 py-1 text-[12px] font-semibold"
                style={{ color: on ? "#071525" : c, background: on ? c : `${c}1a`, boxShadow: `inset 0 0 0 1px ${c}66` }}>
                {WATER_STATUS[st].label} {data ? data.counts[st] : ""}
              </button>
            );
          })}
        </div>
        {(filter.province || filter.basin || filter.river || filter.statuses.length || filter.q) && (
          <button onClick={() => onFilter(EMPTY_FILTER)} className="text-[12px] text-primary hover:underline">ล้างตัวกรอง</button>
        )}
      </div>
      {!data ? <LoadingRows rows={6} /> : rows.length === 0 ? (
        <EmptyState title="ไม่พบสถานีตามตัวกรอง" />
      ) : (
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[860px] text-[13px]">
            <thead className="border-b border-line bg-bg-1/60">
              <tr>
                <Th>สถานี</Th><Th>แม่น้ำ/คลอง</Th><Th k="level" className="text-right">ระดับน้ำ (ม.)</Th>
                <Th className="text-right">ตลิ่ง (ม.)</Th><Th k="remaining" className="text-right">เหลือถึงตลิ่ง</Th>
                <Th k="trend">แนวโน้ม / อัตรา</Th><Th>อัปเดต</Th><Th k="risk">สถานะ</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.slice(0, limit).map((s) => (
                <tr key={s.station_code} onClick={() => onSelect(s.station_code)} className="cursor-pointer hover:bg-bg-2">
                  <td className="px-3 py-2"><span className="block max-w-[220px] truncate">{s.name}</span><span className="block text-[11px] text-muted">{[s.amphoe, s.province].filter(Boolean).join(", ")}</span></td>
                  <td className="max-w-[180px] truncate px-3 py-2 text-ink-2">{s.river ?? "--"}</td>
                  <td className="px-3 py-2 text-right tabular">{fmtNum(s.current_m, 2)}</td>
                  <td className="px-3 py-2 text-right tabular text-ink-2">{fmtNum(s.bank_m, 2)}</td>
                  <td className="px-3 py-2 text-right tabular" style={{ color: s.distance_to_bank_m !== null && s.distance_to_bank_m <= 0 ? "#ef4444" : undefined }}>{fmtDistance(s.distance_to_bank_m)}</td>
                  <td className="px-3 py-2"><TrendCell trend={s.trend} rate={s.rate_cm_per_h} /></td>
                  <td className="px-3 py-2 text-ink-2 tabular">{fmtTime(s.observed_at)}</td>
                  <td className="px-3 py-2"><StatusBadge status={s.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > limit && (
            <div className="p-3 text-center">
              <button onClick={() => setLimit((l) => l + 50)} className="rounded-lg border border-line px-4 py-1.5 text-[12.5px] text-ink-2 hover:bg-bg-2">
                แสดงเพิ่ม ({rows.length - limit} สถานี)
              </button>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

function Select({ label, value, options, onChange }: {
  label: string; value: string; options: { value: string; label: string }[]; onChange: (v: string) => void;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}
      className="h-9 max-w-[190px] rounded-lg border border-line bg-bg-1 px-2 text-[12.5px] text-ink-2">
      <option value="">{label}: ทั้งหมด</option>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}
