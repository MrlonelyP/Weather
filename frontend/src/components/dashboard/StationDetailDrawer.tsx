"use client";

import { Waves } from "lucide-react";
import { useState } from "react";
import { WaterLevelChart } from "@/components/charts/WaterLevelChart";
import { Drawer } from "@/components/ui/Drawer";
import { ErrorNote, LoadingRows } from "@/components/ui/EmptyState";
import { FreshnessTag } from "@/components/ui/FreshnessTag";
import { Segmented } from "@/components/ui/Segmented";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { REFRESH_MS } from "@/config/app";
import { usePolling } from "@/hooks/usePolling";
import { waterService } from "@/services/water";
import type { RangeKey } from "@/types/water";
import { fmtDayTime, fmtDistance, fmtNum, fmtSigned, fmtTime } from "@/utils/format";
import { TREND, trendKey } from "@/utils/status";
import { StationNetworkBlock } from "./DrainageBlocks";
import { ImpactBlock } from "./ImpactBlock";

const RANGES: { value: RangeKey; label: string }[] = [
  { value: "6h", label: "6 ชม." }, { value: "24h", label: "24 ชม." }, { value: "3d", label: "3 วัน" }, { value: "7d", label: "7 วัน" },
];

/** Station detail: is the water rising fast? how far to the bank / watch level? 24 h max? */
export function StationDetailDrawer({ code, onClose }: { code: string | null; onClose: () => void }) {
  const [range, setRange] = useState<RangeKey>("24h");
  const { data, error, loading } = usePolling(
    (signal) => (code ? waterService.station(code, range, signal) : Promise.resolve(null)),
    [code, range],
    code ? REFRESH_MS : null,
  );
  const d = data && data.station_code === code ? data : null;
  const st = d?.state;
  const refName = d?.levels.warning_m !== null && d?.levels.warning_m !== undefined ? "ระดับเฝ้าระวัง" : "ระดับตลิ่ง";
  const remaining = d?.levels.warning_m !== null && d?.levels.warning_m !== undefined ? st?.distance_to_warning_m : st?.distance_to_bank_m;
  const trend = TREND[trendKey(st?.trend ?? null)];

  return (
    <Drawer open={!!code} onClose={onClose} width={560}
      title={
        <div>
          <p className="flex items-center gap-2 font-[family-name:var(--font-display)] text-[17px] font-semibold"><Waves className="size-5 text-primary" />{d?.name ?? "สถานีวัดระดับน้ำ"}</p>
          <p className="mt-0.5 text-[12.5px] text-muted">{d ? [d.river, d.amphoe && `อ.${d.amphoe}`, d.province].filter(Boolean).join(" · ") : ""}</p>
        </div>
      }>
      {!d ? (loading ? <LoadingRows rows={8} /> : <ErrorNote error={error} />) : (
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={st!.status} size="md" />
            <span className="text-[11.5px] text-muted">ระบบประเมินจากระยะถึงตลิ่งและอัตราการขึ้น (ไม่ใช่ประกาศทางราชการ)</span>
          </div>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            <Kpi label="ระดับน้ำปัจจุบัน" value={`${fmtNum(st!.current_m, 2)} ม.`} sub={`ตรวจวัด ${fmtTime(st!.observed_at)} น.`} />
            <Kpi label={refName} value={`${fmtNum(d.levels.warning_m ?? d.levels.bank_m, 2)} ม.`} sub={d.levels.warning_m !== null ? `ตลิ่ง ${fmtNum(d.levels.bank_m, 2)} ม.` : "ม.รทก."} />
            <Kpi label="เหลืออีก" value={fmtDistance(remaining)} tone={remaining !== null && remaining !== undefined && remaining <= 0 ? "#ef4444" : undefined} sub={`ถึง${refName}`} />
            <Kpi label="แนวโน้ม" value={trend.label} tone={trend.color} sub={st!.rate_cm_per_h === null ? "ข้อมูลไม่พอคำนวณ" : `${fmtSigned(st!.rate_cm_per_h, 1)} ซม./ชม.`} />
            <Kpi label="สูงสุดใน 24 ชม." value={`${fmtNum(d.stats_24h.max_m, 2)} ม.`} sub={d.stats_24h.max_at ? fmtDayTime(d.stats_24h.max_at) : "--"} />
            <Kpi label="อัตราการไหล" value={st!.discharge_m3s === null ? "--" : `${fmtNum(st!.discharge_m3s, 1)}`} sub="ลบ.ม./วินาที" />
          </div>

          <div className="rounded-xl border border-line bg-card p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[13px] font-semibold">ระดับน้ำตรวจวัด</p>
              <Segmented ariaLabel="ช่วงเวลา" value={range} onChange={setRange} options={RANGES} />
            </div>
            {d.series.length ? <WaterLevelChart detail={d} /> : <p className="py-6 text-center text-[12.5px] text-muted">ไม่มีข้อมูลในช่วงนี้</p>}
            <p className="mt-1 text-[11px] text-muted">
              {d.history_note ?? `มีข้อมูลตั้งแต่ ${fmtDayTime(d.history_available_since)}`}
              {" · "}{d.forecast_note}
            </p>
          </div>

          <ImpactBlock impact={d.impact} />
          <StationNetworkBlock net={d.network} />

          <div className="rounded-xl border border-line p-3 text-[12.5px]">
            <p className="mb-1 font-semibold text-ink-2">ค่าที่ต้นทาง (ThaiWater) กำหนด</p>
            <p className="text-muted">
              ระดับสถานการณ์: {d.source_assessment.situation_level ?? "--"}
              {d.source_assessment.diff_to_bank_text && ` · ${d.source_assessment.diff_to_bank_text} ${fmtNum(d.source_assessment.diff_to_bank_m, 2)}`}
            </p>
            <p className="mt-1 text-muted">ระดับอ้างอิง: ตลิ่ง {fmtNum(d.levels.bank_m, 2)} · เฝ้าระวัง {fmtNum(d.levels.warning_m, 2)} · วิกฤต {fmtNum(d.levels.critical_m, 2)} · พื้นดิน {fmtNum(d.levels.ground_m, 2)} ม.รทก.</p>
            {d.levels.note && <p className="mt-1 text-watch">{d.levels.note}</p>}
            <p className="mt-1 text-muted">หน่วยงาน: {d.agency ?? "--"} · รหัสสถานี {d.station_code}</p>
          </div>
          <FreshnessTag f={d.freshness} />
        </div>
      )}
    </Drawer>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-card px-3 py-2.5">
      <p className="text-[11.5px] text-muted">{label}</p>
      <p className="font-[family-name:var(--font-display)] text-[18px] font-semibold tabular" style={{ color: tone }}>{value}</p>
      {sub && <p className="text-[11px] text-muted">{sub}</p>}
    </div>
  );
}
